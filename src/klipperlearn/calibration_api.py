"""Authenticated, manual calibration workflow endpoints for the local console.

The endpoints deliberately keep the physical-printer boundary narrow: chart generation
only writes local artifacts, photo analysis only reads a local upload, and adjustment
application is available solely through an explicit confirmed action.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from .request_safety import token_matches
import importlib
import json
import math
import re
import secrets
import uuid
from pathlib import Path
from typing import Any, Mapping

import httpx
from fastapi import Header, HTTPException, Request
from fastapi.responses import Response


_MACHINE_QUERY = "/printer/objects/query?configfile&toolhead&webhooks&print_stats"
_CHART_FILES = {
    "chart.json": ("application/json",),
    "chart.svg": ("image/svg+xml",),
    "chart.gcode": ("text/plain; charset=utf-8",),
}
_CHART_ID = re.compile(r"^[0-9a-f]{16,64}$")
_PROPOSAL_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_PHOTO_ID = re.compile(r"^[0-9a-f]{32}$")
_BODY_LIMIT = 8 * 1024 * 1024
_JPEG_LIMIT = 5 * 1024 * 1024
_IDLE_PRINT_STATES = {"standby", "complete", "cancelled"}
_ADJUSTMENT_PARAMETERS = frozenset({"pressure_advance", "accel_mm_s2", "extrusion_factor"})
_SPEC_KEYS = {
    "bed_width_mm",
    "bed_depth_mm",
    "origin_x_mm",
    "origin_y_mm",
    "size_mm",
    "nozzle_mm",
    "layer_height_mm",
    "line_width_mm",
    "filament_diameter_mm",
    "print_speed_mm_s",
    "travel_speed_mm_s",
    "hotend_temp_c",
    "bed_temp_c",
    "max_hotend_temp_c",
    "max_bed_temp_c",
    "max_velocity_mm_s",
    "max_volumetric_mm3_s",
}
_MACHINE_OVERRIDE_KEYS = {
    "bed_width_mm",
    "bed_depth_mm",
    "max_hotend_temp_c",
    "max_bed_temp_c",
    "max_velocity_mm_s",
}
_REQUIRED_USER_KEYS = _SPEC_KEYS - _MACHINE_OVERRIDE_KEYS


def _error(status_code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail[:360])


def _authorize(candidate: str | None, expected: str) -> None:
    if not token_matches(candidate, expected):
        raise _error(401, "Unauthorized")


def _finite_number(value: Any, *, minimum: float | None = None) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    if not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        return None
    return number


def _json_safe(value: Any) -> bool:
    if value is None or isinstance(value, (bool, str, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_json_safe(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_safe(item) for key, item in value.items())
    return False


def _safe_status_message(value: Any) -> str:
    if not isinstance(value, str):
        return ""
        # Keep the operator-facing message, but remove control characters before it reaches
        # a JSON/HTML client and cap it so a malformed firmware message cannot flood the UI.
    return "".join(character for character in value if character in "\t" or ord(character) >= 32)[
        :300
    ]


def _invalid_moonraker_response() -> HTTPException:
    return _error(503, "Invalid Moonraker response")


def _object_number(
    section: Mapping[str, Any] | None, key: str, minimum: float | None = None
) -> float | None:
    if not isinstance(section, Mapping):
        return None
    return _finite_number(section.get(key), minimum=minimum)


def _heater_limit(section: Mapping[str, Any] | None, key: str, cap: float) -> float | None:
    configured = _object_number(section, key, minimum=0)
    if configured is None or configured <= 5.0:
        return None
    safe_limit = min(cap, configured - 5.0)
    return safe_limit if math.isfinite(safe_limit) and safe_limit > 0.0 else None


def _axis_value(section: Mapping[str, Any] | None, key: str, index: int) -> float | None:
    if not isinstance(section, Mapping):
        return None
    values = section.get(key)
    if not isinstance(values, (list, tuple)) or len(values) <= index:
        return None
    return _finite_number(values[index])


def _machine_snapshot(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise _invalid_moonraker_response()
    result = data.get("result")
    status = result.get("status") if isinstance(result, dict) else None
    if not isinstance(status, dict):
        raise _invalid_moonraker_response()

    webhooks = status.get("webhooks")
    if not isinstance(webhooks, dict) or not isinstance(webhooks.get("state"), str):
        raise _invalid_moonraker_response()
    webhooks_state = webhooks["state"]
    status_message = _safe_status_message(webhooks.get("state_message"))

    print_stats = status.get("print_stats")
    printer_state = print_stats.get("state") if isinstance(print_stats, dict) else None
    if not isinstance(printer_state, str) or not printer_state:
        printer_state = None

    configfile = status.get("configfile")
    settings = configfile.get("settings") if isinstance(configfile, dict) else None
    extruder = settings.get("extruder") if isinstance(settings, dict) else None
    heater_bed = settings.get("heater_bed") if isinstance(settings, dict) else None
    printer = settings.get("printer") if isinstance(settings, dict) else None
    toolhead = status.get("toolhead")

    axis_min_x = _axis_value(toolhead, "axis_minimum", 0)
    axis_min_y = _axis_value(toolhead, "axis_minimum", 1)
    axis_max_x = _axis_value(toolhead, "axis_maximum", 0)
    axis_max_y = _axis_value(toolhead, "axis_maximum", 1)
    # Negative homing travel is not additional printable bed.
    bed_width = (
        axis_max_x - max(0.0, axis_min_x)
        if axis_max_x is not None and axis_min_x is not None
        else None
    )
    bed_depth = (
        axis_max_y - max(0.0, axis_min_y)
        if axis_max_y is not None and axis_min_y is not None
        else None
    )
    if bed_width is not None and bed_width <= 0:
        bed_width = None
    if bed_depth is not None and bed_depth <= 0:
        bed_depth = None

    configured_min_extrude_temp = (
        _object_number(extruder, "min_extrude_temp", minimum=0)
        if isinstance(extruder, Mapping) and "min_extrude_temp" in extruder
        else 170.0
    )
    machine = {
        "bed_width_mm": bed_width,
        "bed_depth_mm": bed_depth,
        "origin_x_mm": max(0.0, axis_min_x) if axis_min_x is not None else None,
        "origin_y_mm": max(0.0, axis_min_y) if axis_min_y is not None else None,
        "max_hotend_temp_c": _heater_limit(extruder, "max_temp", 275.0),
        "max_bed_temp_c": _heater_limit(heater_bed, "max_temp", 110.0),
        "max_velocity_mm_s": _object_number(printer, "max_velocity", minimum=1e-12),
        "nozzle_mm": _object_number(extruder, "nozzle_diameter", minimum=1e-12),
        "filament_diameter_mm": _object_number(extruder, "filament_diameter", minimum=1e-12),
        "min_extrude_temp_c": configured_min_extrude_temp,
    }

    reasons: list[str] = []
    if webhooks_state != "ready":
        reasons.append("The printer is not ready.")
    if printer_state is None:
        reasons.append("The print state is unknown.")
    elif printer_state not in _IDLE_PRINT_STATES:
        reasons.append("This operation is available only between prints.")
    missing = [key for key, value in machine.items() if value is None]
    if missing:
        reasons.append("Machine configuration values are missing.")
    if (axis_min_x is not None and axis_min_x > 1e-9) or (
        axis_min_y is not None and axis_min_y > 1e-9
    ):
        reasons.append("This chart does not yet support a non-zero bed origin.")

    ready = not reasons
    # The UI needs a stable, non-secret status object even when the printer is in
    # shutdown.  Do not expose the complete webhooks object or any Moonraker keys.
    return {
        "ready": ready,
        "webhooks_state": webhooks_state[:64],
        "status_message": status_message,
        "printer_state": printer_state[:64] if printer_state else None,
        "machine": machine,
        "capabilities": dict(machine),
        "material_config": {
            "nozzle_mm": machine["nozzle_mm"],
            "filament_diameter_mm": machine["filament_diameter_mm"],
            "min_extrude_temp_c": machine["min_extrude_temp_c"],
            "source": "Klipper configuration; not a measurement of the physical hardware or material.",
        },
        "reasons": reasons,
    }


def _validate_chart_id(chart_id: str) -> None:
    if not isinstance(chart_id, str) or not _CHART_ID.fullmatch(chart_id):
        raise _error(404, "Carta no encontrada")


def _validate_proposal_id(proposal_id: Any) -> str:
    if not isinstance(proposal_id, str) or not _PROPOSAL_ID.fullmatch(proposal_id):
        raise _error(422, "Invalid proposal")
    return proposal_id


async def _request_json(request: Request, *, limit: int = _BODY_LIMIT) -> dict[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > limit:
                raise _error(413, "The request body is too large")
        except ValueError as exc:
            raise _error(422, "The request body is invalid") from exc
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise _error(413, "The request body is too large")
    try:
        value = json.loads(bytes(body))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _error(422, "The body must be a valid JSON object") from exc
    if not isinstance(value, dict):
        raise _error(422, "The body must be a valid JSON object")
    return value


def _validate_input_spec(payload: Mapping[str, Any]) -> dict[str, float]:
    unexpected = set(payload) - _SPEC_KEYS
    if unexpected:
        raise _error(422, "The chart contains unsupported fields")
    missing = _REQUIRED_USER_KEYS - set(payload)
    if missing:
        raise _error(422, "Calibration chart fields are missing")
    validated: dict[str, float] = {}
    for key, value in payload.items():
        number = _finite_number(value)
        if number is None:
            raise _error(422, "Chart values must be finite numbers")
        validated[key] = number
    for key in (
        "size_mm",
        "layer_height_mm",
        "line_width_mm",
        "nozzle_mm",
        "filament_diameter_mm",
        "print_speed_mm_s",
        "travel_speed_mm_s",
        "max_volumetric_mm3_s",
    ):
        if validated.get(key, 0) <= 0:
            raise _error(422, "Geometry and speed values must be positive")
    for key in ("origin_x_mm", "origin_y_mm", "hotend_temp_c", "bed_temp_c"):
        if validated.get(key, 0) < 0:
            raise _error(422, "Origin and temperature values must not be negative")
    return validated


def _effective_spec(
    input_spec: Mapping[str, float], machine: Mapping[str, Any]
) -> dict[str, float]:
    actual = machine.get("machine")
    if not isinstance(actual, Mapping) or any(
        actual.get(key) is None for key in _SPEC_KEYS & _MACHINE_OVERRIDE_KEYS
    ):
        raise _error(409, "The actual machine configuration is not available yet")

    for key in ("nozzle_mm", "filament_diameter_mm"):
        requested = input_spec.get(key)
        configured = _finite_number(actual.get(key), minimum=0)
        if (
            requested is None
            or configured is None
            or not math.isclose(requested, configured, abs_tol=1e-6, rel_tol=0)
        ):
            label = "boquilla" if key == "nozzle_mm" else "filamento"
            raise _error(
                422, f"The measurement of {label} does not match the machine configuration"
            )

    effective = {key: float(input_spec[key]) for key in _SPEC_KEYS if key in input_spec}
    for key in _MACHINE_OVERRIDE_KEYS:
        effective[key] = float(actual[key])

    width = effective["bed_width_mm"]
    depth = effective["bed_depth_mm"]
    if (
        effective["origin_x_mm"] + effective["size_mm"] > width
        or effective["origin_y_mm"] + effective["size_mm"] > depth
    ):
        raise _error(422, "The chart is outside the configured bed")
    if effective["size_mm"] > min(width, depth) or effective["size_mm"] > 1000:
        raise _error(422, "The chart dimensions are not permitted for this bed")
    if (
        effective["print_speed_mm_s"] > effective["max_velocity_mm_s"]
        or effective["travel_speed_mm_s"] > effective["max_velocity_mm_s"]
    ):
        raise _error(422, "The requested speed exceeds the machine limit")
    if (
        effective["hotend_temp_c"] > effective["max_hotend_temp_c"]
        or effective["bed_temp_c"] > effective["max_bed_temp_c"]
    ):
        raise _error(422, "The requested temperature exceeds the configured limit")
    minimum_extrude_temp = _finite_number(actual.get("min_extrude_temp_c"), minimum=0)
    if minimum_extrude_temp is None:
        raise _error(409, "The configured minimum extrusion temperature is unavailable")
    if effective["hotend_temp_c"] < minimum_extrude_temp:
        raise _error(422, "The hotend temperature is below min_extrude_temp")
    return effective


def _component(module_name: str, attribute: str, unavailable_message: str):
    try:
        module = importlib.import_module(f"{__package__}.{module_name}")
        component = getattr(module, attribute)
    except (ImportError, AttributeError) as exc:
        raise _error(503, unavailable_message) from exc
    if not callable(component):
        raise _error(503, unavailable_message)
    return component


def _text_result(value: Any) -> str:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _error(503, "The generator returned invalid text") from exc
    if not isinstance(value, str):
        raise _error(503, "The generator returned an invalid file")
    return value


def _chart_dir(root: Path, chart_id: str) -> Path:
    _validate_chart_id(chart_id)
    root_resolved = root.resolve()
    candidate = (root / chart_id).resolve()
    if candidate.parent != root_resolved:
        raise _error(404, "Carta no encontrada")
    if not candidate.is_dir():
        raise _error(404, "Carta no encontrada")
    return candidate


def _analysis_corners(value: Any) -> list[list[float]]:
    if not isinstance(value, list) or len(value) != 4:
        raise _error(422, "Four corners in TL, TR, BR, BL order are required")
    corners: list[list[float]] = []
    for point in value:
        if isinstance(point, Mapping):
            point = [point.get("x"), point.get("y")]
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise _error(422, "Each corner must contain x and y coordinates")
        x = _finite_number(point[0], minimum=0)
        y = _finite_number(point[1], minimum=0)
        if x is None or y is None:
            raise _error(422, "The corner coordinates are invalid")
        corners.append([x, y])
    if len({(point[0], point[1]) for point in corners}) != 4:
        raise _error(422, "The four corners must be distinct")
    return corners


def _decode_jpeg(value: Any) -> bytes:
    if not isinstance(value, str) or not value:
        raise _error(422, "Falta la imagen JPEG")
    encoded = value.strip()
    if encoded.startswith("data:"):
        try:
            metadata, encoded = encoded.split(",", 1)
        except ValueError as exc:
            raise _error(422, "The JPEG image is invalid") from exc
        if ";base64" not in metadata.casefold():
            raise _error(422, "The JPEG image is invalid")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _error(422, "The JPEG image is invalid") from exc
    if len(decoded) > _JPEG_LIMIT:
        raise _error(413, "The JPEG image is too large")
    if len(decoded) < 4 or not decoded.startswith(b"\xff\xd8") or not decoded.endswith(b"\xff\xd9"):
        raise _error(422, "The JPEG image is invalid")
    return decoded


def _normalized_bounds(value: Any) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise _error(422, "Specify a valid current range")
    minimum_number = _finite_number(value[0])
    maximum_number = _finite_number(value[1])
    if minimum_number is None or maximum_number is None or minimum_number > maximum_number:
        raise _error(422, "Specify a valid current range")
    return [minimum_number, maximum_number]


def _controller_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not _json_safe(value):
        raise _error(503, "Experimental control returned an invalid response")
    return value


def _operation_response(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": "manual experimental",
        "automatic": False,
        "result": result,
        **result,
    }


def install_calibration_api(
    app,
    token: str,
    moonraker: str,
    transport=None,
    root: str | Path = Path("data/calibration"),
):
    """Install the authenticated calibration API on an existing FastAPI app."""

    root_path = Path(root)
    controller_holder: dict[str, Any] = {"value": None}

    async def authorize_header(x_klipperlearn_token: str | None) -> None:
        _authorize(x_klipperlearn_token, token)

    async def moonraker_get(path: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False, transport=transport) as client:
                response = await client.get(moonraker.rstrip("/") + path)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise _error(503, "Unable to query Moonraker") from exc
        if not isinstance(data, dict) or "error" in data:
            raise _invalid_moonraker_response()
        return data

    async def machine_info() -> dict[str, Any]:
        return _machine_snapshot(await moonraker_get(_MACHINE_QUERY))

    async def require_ready() -> dict[str, Any]:
        snapshot = await machine_info()
        if not snapshot["ready"]:
            message = (
                snapshot.get("status_message")
                or (snapshot.get("reasons") or ["The printer is not ready."])[0]
            )
            raise _error(409, f"The printer is not ready: {message}")
        return snapshot

    def chart_path(chart_id: str, filename: str) -> Path:
        if filename not in _CHART_FILES:
            raise _error(404, "Calibration chart file not found")
        directory = _chart_dir(root_path, chart_id)
        candidate = (directory / filename).resolve()
        if candidate.parent != directory or not candidate.is_file():
            raise _error(404, "Calibration chart file not found")
        return candidate

    def new_chart_dir() -> tuple[str, Path]:
        try:
            root_path.mkdir(parents=True, exist_ok=True)
            for _ in range(8):
                chart_id = secrets.token_hex(16)
                directory = root_path / chart_id
                try:
                    directory.mkdir(mode=0o700)
                    return chart_id, directory
                except FileExistsError:
                    continue
        except OSError as exc:
            raise _error(500, "The chart could not be saved") from exc
        raise _error(500, "A chart identifier could not be created")

    def controller():
        if controller_holder["value"] is None:
            try:
                controller_class = _component(
                    "calibration_control",
                    "CalibrationController",
                    "Experimental control is unavailable",
                )
                root_path.mkdir(parents=True, exist_ok=True)
                controller_holder["value"] = controller_class(
                    moonraker,
                    root_path / "adjustments.jsonl",
                    transport=transport,
                )
            except HTTPException:
                raise
            except (OSError, TypeError, ValueError) as exc:
                raise _error(503, "Experimental control could not be prepared") from exc
        return controller_holder["value"]

    @app.get("/mobile/api/calibration/info")
    async def calibration_info(x_klipperlearn_token: str | None = Header(default=None)):
        await authorize_header(x_klipperlearn_token)
        return {"result": await machine_info()}

    @app.post("/mobile/api/calibration/charts", status_code=201)
    async def create_chart(
        request: Request, x_klipperlearn_token: str | None = Header(default=None)
    ):
        await authorize_header(x_klipperlearn_token)
        payload = await _request_json(request)
        input_spec = _validate_input_spec(payload)
        snapshot = await require_ready()
        effective = _effective_spec(input_spec, snapshot)
        builder = _component(
            "calibration_chart", "build_chart", "The calibration chart generator is unavailable"
        )
        try:
            built = await asyncio.to_thread(builder, dict(effective))
        except HTTPException:
            raise
        except (ImportError, ModuleNotFoundError) as exc:
            raise _error(503, "The calibration chart generator is unavailable") from exc
        except (TypeError, ValueError, OSError) as exc:
            raise _error(422, "The requested chart could not be validated") from exc
        except (
            Exception
        ) as exc:  # pragma: no cover - protects the HTTP boundary from plugin details.
            raise _error(503, "The chart could not be generated") from exc
        if not isinstance(built, Mapping) or not {"manifest", "svg", "gcode"}.issubset(built):
            raise _error(503, "The generator returned an incomplete chart")
        svg = _text_result(built["svg"])
        gcode = _text_result(built["gcode"])
        chart_id, directory = new_chart_dir()
        try:
            (directory / "chart.json").write_text(
                json.dumps(built["manifest"], ensure_ascii=False, allow_nan=False, indent=2),
                encoding="utf-8",
            )
            (directory / "metadata.json").write_text(
                json.dumps(
                    {"chart_id": chart_id, "spec": effective},
                    ensure_ascii=False,
                    allow_nan=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (directory / "chart.svg").write_text(svg, encoding="utf-8")
            (directory / "chart.gcode").write_text(gcode, encoding="utf-8")
        except (OSError, TypeError, ValueError) as exc:
            raise _error(500, "The chart could not be saved") from exc
        base = f"/mobile/api/calibration/charts/{chart_id}"
        return {
            "chart_id": chart_id,
            "spec": effective,
            "manifest": built["manifest"],
            "files": {
                "json": f"{base}/chart.json",
                "svg": f"{base}/chart.svg",
                "gcode": f"{base}/chart.gcode",
            },
        }

    @app.get("/mobile/api/calibration/charts/{chart_id}/{filename}")
    async def chart_file(
        chart_id: str,
        filename: str,
        x_klipperlearn_token: str | None = Header(default=None),
    ):
        await authorize_header(x_klipperlearn_token)
        path = chart_path(chart_id, filename)
        media_type = _CHART_FILES[filename][0]
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise _error(404, "Calibration chart file not found") from exc
        return Response(
            content=content,
            media_type=media_type,
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/mobile/api/calibration/charts/{chart_id}/analyze")
    async def analyze_chart(
        chart_id: str,
        request: Request,
        x_klipperlearn_token: str | None = Header(default=None),
    ):
        await authorize_header(x_klipperlearn_token)
        payload = await _request_json(request)
        if set(payload) != {"image_base64", "corners_px", "polarity"}:
            raise _error(422, "The analysis request is invalid")
        image = _decode_jpeg(payload["image_base64"])
        corners = _analysis_corners(payload["corners_px"])
        polarity = payload["polarity"]
        if not isinstance(polarity, str) or polarity not in {"light", "dark"}:
            raise _error(422, "The specified polarity is invalid")
        directory = _chart_dir(root_path, chart_id)
        try:
            chart_record = json.loads((directory / "chart.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise _error(404, "Carta no encontrada") from exc
        if not isinstance(chart_record, dict):
            raise _error(503, "The calibration chart manifest is invalid")
        manifest = chart_record
        if not _json_safe(manifest):
            raise _error(503, "The calibration chart manifest is invalid")

        photo_id = uuid.uuid4().hex
        photo_path = directory / f"photo-{photo_id}.jpg"
        try:
            photo_path.write_bytes(image)
        except OSError as exc:
            raise _error(500, "The photograph could not be saved") from exc
        analyzer = _component("chart_vision", "analyze_chart", "Visual analysis is unavailable")
        try:
            report = await asyncio.to_thread(analyzer, str(photo_path), manifest, corners, polarity)
        except HTTPException:
            raise
        except (ImportError, ModuleNotFoundError) as exc:
            raise _error(503, "Visual analysis is unavailable") from exc
        except (TypeError, ValueError) as exc:
            raise _error(422, "The photograph or corners cannot be analyzed") from exc
        except Exception as exc:  # pragma: no cover - plugin failures stay sanitized.
            raise _error(503, "The photograph could not be analyzed") from exc
        if not isinstance(report, dict) or not _json_safe(report):
            raise _error(503, "Visual analysis returned an invalid report")
        report_record = {
            "photo_id": photo_id,
            "human_review_required": True,
            "automatic_validation": False,
            "report": report,
        }
        try:
            (directory / f"report-{photo_id}.json").write_text(
                json.dumps(report_record, ensure_ascii=False, allow_nan=False, indent=2),
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError) as exc:
            raise _error(500, "The report could not be saved") from exc
        return {
            "chart_id": chart_id,
            "photo_id": photo_id,
            "human_review_required": True,
            "automatic_validation": False,
            "report": report,
        }

    @app.post("/mobile/api/calibration/adjustments/preview")
    async def preview_adjustment(
        request: Request,
        x_klipperlearn_token: str | None = Header(default=None),
    ):
        await authorize_header(x_klipperlearn_token)
        payload = await _request_json(request, limit=1024 * 1024)
        if set(payload) != {"parameter", "value", "bounds", "maximum_step"}:
            raise _error(422, "The adjustment proposal is invalid")
        parameter = payload["parameter"]
        if not isinstance(parameter, str) or parameter.casefold() not in _ADJUSTMENT_PARAMETERS:
            raise _error(422, "This parameter is not permitted")
        value = _finite_number(payload["value"])
        maximum_step = _finite_number(payload["maximum_step"], minimum=0)
        bounds = _normalized_bounds(payload["bounds"])
        if (
            value is None
            or maximum_step is None
            or maximum_step <= 0
            or not bounds[0] <= value <= bounds[1]
        ):
            raise _error(422, "The value and step must be within the specified range")
        await require_ready()
        try:
            result = await controller().preview(
                parameter.casefold(),
                value,
                bounds,
                maximum_step,
            )
        except HTTPException:
            raise
        except (ValueError, TypeError, OSError) as exc:
            raise _error(422, "The manual proposal could not be prepared") from exc
        except (
            Exception
        ) as exc:  # pragma: no cover - controller details never cross the API boundary.
            raise _error(503, "The manual proposal could not be prepared") from exc
        return _operation_response(_controller_result(result))

    async def confirmed_adjustment(request: Request, action: str):
        payload = await _request_json(request, limit=1024 * 1024)
        if set(payload) != {"proposal_id", "confirmed"} or payload.get("confirmed") is not True:
            raise _error(422, "This manual action requires confirmed=true")
        proposal_id = _validate_proposal_id(payload["proposal_id"])
        await require_ready()
        try:
            method = getattr(controller(), action)
            result = await method(proposal_id, True)
        except HTTPException:
            raise
        except (ValueError, TypeError, OSError) as exc:
            raise _error(422, "The manual proposal is invalid") from exc
        except Exception as exc:  # pragma: no cover
            raise _error(503, "The manual action could not be completed") from exc
        return _operation_response(_controller_result(result))

    @app.post("/mobile/api/calibration/adjustments/apply")
    async def apply_adjustment(
        request: Request, x_klipperlearn_token: str | None = Header(default=None)
    ):
        await authorize_header(x_klipperlearn_token)
        return await confirmed_adjustment(request, "apply")

    @app.post("/mobile/api/calibration/adjustments/restore")
    async def restore_adjustment(
        request: Request, x_klipperlearn_token: str | None = Header(default=None)
    ):
        await authorize_header(x_klipperlearn_token)
        return await confirmed_adjustment(request, "restore")

    app.state.klipperlearn_calibration_api_installed = True
    return app
