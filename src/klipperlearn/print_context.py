"""Read-only print context from Moonraker.

The helper in this module deliberately does not infer a material, a nozzle,
or a model identity.  It only combines the live Klipper status with the
metadata Moonraker already has for the selected G-code file.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx


_OBJECTS_QUERY = "/printer/objects/query?print_stats&configfile&toolhead&extruder&gcode_move"
_METADATA_PATH = "/server/files/metadata"
_GCODE_EXTENSIONS = (".gcode", ".gco", ".g", ".g3d")
_MAX_RESPONSE_BYTES = 512 * 1024

# These are the only file metadata values that can be copied into the result.
# In particular, thumbnails and arbitrary slicer extensions are not exposed.
_METADATA_FIELDS = frozenset(
    {
        "filament_name",
        "filament_type",
        "filament_colors",
        "extruder_colors",
        "filament_temps",
        "filament_total",
        "filament_weight_total",
        "filament_weights",
        "nozzle_diameter",
        "slicer",
        "slicer_version",
        "estimated_time",
        "print_start_time",
        "layer_height",
        "first_layer_height",
        "first_layer_extr_temp",
        "first_layer_bed_temp",
        "object_height",
        "printer_vendor",
        "printer_model",
        "printer_variant",
        "profile_version",
    }
)


def _error(message: str) -> ValueError:
    """Return a stable, non-sensitive error for callers and API adapters."""

    return ValueError(message)


def _base_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error("moonraker_url is invalid")
    try:
        parsed = httpx.URL(value)
    except (httpx.InvalidURL, TypeError, ValueError) as exc:
        raise _error("moonraker_url is invalid") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise _error("moonraker_url is invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise _error("moonraker_url is invalid")
    return str(parsed).rstrip("/")


def _is_safe_gcode_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return False
        # Query and fragment characters would make the value ambiguous if it were
        # ever assembled into a URL.  They are not needed in a Moonraker filename.
    if "?" in value or "#" in value:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme or parsed.netloc:
        return False

        # Check both the literal spelling and percent-decoded spelling.  The latter
        # prevents encoded slash/dot traversal from reaching the metadata endpoint.
    decoded = unquote(value)
    for candidate in (value, decoded):
        if (
            "\\" in candidate
            or ":" in candidate
            or candidate.startswith("/")
            or candidate.startswith("//")
        ):
            return False
        parts = candidate.split("/")
        if any(not part or part in {".", ".."} for part in parts):
            return False

    return decoded.casefold().endswith(_GCODE_EXTENSIONS)


def _finite(value: Any, *, positive: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(number) or (positive and number <= 0.0):
        return None
    return number


def _safe_text(value: Any, *, maximum: int = 256) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return None
    return value[:maximum]


def _safe_text_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value:
        text = _safe_text(item, maximum=128)
        if text is None:
            return None
        result.append(text)
    return result


def _safe_number_list(value: Any) -> list[float] | None:
    if not isinstance(value, list):
        return None
    result: list[float] = []
    for item in value:
        number = _finite(item)
        if number is None:
            return None
        result.append(number)
    return result


def _safe_metadata(value: Any) -> dict[str, Any]:
    """Copy only bounded, finite, documented metadata fields."""

    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in _METADATA_FIELDS:
        if key not in value:
            continue
        raw = value[key]
        if key in {
            "filament_name",
            "filament_type",
            "slicer",
            "slicer_version",
            "printer_vendor",
            "printer_model",
            "printer_variant",
            "profile_version",
        }:
            normalized = _safe_text(raw)
        elif key in {"filament_colors", "extruder_colors"}:
            normalized = _safe_text_list(raw)
        elif key in {"filament_temps", "filament_weights"}:
            normalized = _safe_number_list(raw)
        else:
            normalized = _finite(raw)
        if normalized is not None:
            result[key] = normalized
    return result


def _material_metadata(metadata: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalize the material portion without inventing missing values."""

    material: dict[str, Any] = {}
    mappings = (
        ("filament_name", "name"),
        ("filament_type", "type"),
        ("filament_colors", "colors"),
        ("extruder_colors", "extruder_colors"),
        ("filament_temps", "temperatures_c"),
        ("filament_total", "total_mm"),
        ("filament_weight_total", "weight_g"),
        ("filament_weights", "weights_g"),
    )
    for source, target in mappings:
        if source in metadata:
            material[target] = metadata[source]
    return material or None


def _status(data: Any) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise _error("Invalid Moonraker response")
    result = data.get("result")
    status = result.get("status") if isinstance(result, Mapping) else None
    if not isinstance(status, Mapping):
        raise _error("Invalid Moonraker response")

    required_objects = ("print_stats", "configfile", "toolhead", "extruder", "gcode_move")
    if any(not isinstance(status.get(name), Mapping) for name in required_objects):
        raise _error("Invalid Moonraker response")
    return dict(status)


def _selected_filename(
    print_stats: Mapping[str, Any], explicit: str | None
) -> tuple[str | None, str]:
    if explicit is not None:
        if not _is_safe_gcode_path(explicit):
            raise _error("filename is not a valid relative G-code path")
        return explicit, "argument.filename"

    raw = print_stats.get("filename")
    if raw in (None, ""):
        return None, "print_stats.filename"
    if not _is_safe_gcode_path(raw):
        raise _error("filename is not a valid relative G-code path")
    return raw, "print_stats.filename"


def _configured_nozzle(status: Mapping[str, Any]) -> float | None:
    configfile = status["configfile"]
    settings = configfile.get("settings") if isinstance(configfile, Mapping) else None
    extruder = settings.get("extruder") if isinstance(settings, Mapping) else None
    return (
        _finite(extruder.get("nozzle_diameter"), positive=True)
        if isinstance(extruder, Mapping)
        else None
    )


def _metadata_result(data: Any) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise _error("Invalid Moonraker metadata response")
    result = data.get("result")
    if not isinstance(result, Mapping):
        raise _error("Invalid Moonraker metadata response")
    return result


async def _get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    metadata: bool = False,
) -> Any | None:
    try:
        response = await client.get(url, params=params)
        if metadata and response.status_code == 404:
            return None
        response.raise_for_status()
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise _error("Respuesta de Moonraker demasiado grande")
        data = response.json()
    except ValueError:
        raise
    except httpx.HTTPError as exc:
        message = (
            "Moonraker metadata could not be queried"
            if metadata
            else "Moonraker could not be queried"
        )
        raise _error(message) from exc
    except (TypeError, KeyError) as exc:
        raise _error("Invalid Moonraker response") from exc

    if not isinstance(data, Mapping) or "error" in data:
        message = (
            "Invalid Moonraker metadata response" if metadata else "Invalid Moonraker response"
        )
        raise _error(message)
    return data


async def fetch_print_context(
    moonraker_url: str,
    filename: str | None = None,
    transport=None,
) -> dict[str, Any]:
    """Fetch a finite, provenance-bearing snapshot without changing the printer.

    ``filename`` is optional only because an active ``print_stats.filename``
    can supply it.  A missing file or a 404 metadata response remains unknown;
    it is never filled with a PLA, nozzle, machine, or model default.
    """

    base_url = _base_url(moonraker_url)
    if filename is not None and not _is_safe_gcode_path(filename):
        raise _error("filename is not a valid relative G-code path")

    try:
        async with httpx.AsyncClient(timeout=5, trust_env=False, transport=transport) as client:
            query_data = await _get_json(client, base_url + _OBJECTS_QUERY)
            status = _status(query_data)
            print_stats = status["print_stats"]
            selected, filename_source = _selected_filename(print_stats, filename)

            metadata_data = None
            metadata_status = "unknown"
            metadata_reason = "no_filename"
            if selected is not None:
                metadata_data = await _get_json(
                    client,
                    base_url + _METADATA_PATH,
                    params={"filename": selected},
                    metadata=True,
                )
                if metadata_data is None:
                    metadata_reason = "not_found"
                else:
                    metadata_status = "available"
                    metadata_reason = None

    except ValueError:
        raise
    except httpx.HTTPError as exc:
        raise _error("Moonraker could not be queried") from exc
    except (TypeError, KeyError) as exc:
        raise _error("Invalid Moonraker response") from exc

    metadata = _safe_metadata(_metadata_result(metadata_data)) if metadata_data is not None else {}
    material = _material_metadata(metadata)
    nozzle_mm = _finite(metadata.get("nozzle_diameter"), positive=True)
    configured_nozzle_mm = _configured_nozzle(status)

    conflicts: list[str] = []
    if (
        nozzle_mm is not None
        and configured_nozzle_mm is not None
        and not math.isclose(nozzle_mm, configured_nozzle_mm, rel_tol=0.0, abs_tol=1e-6)
    ):
        conflicts.append("nozzle_mm")

    extruder = status["extruder"]
    toolhead = status["toolhead"]
    gcode_move = status["gcode_move"]
    printer_state = _safe_text(print_stats.get("state"), maximum=64)

    parameters = {
        "pressure_advance": _finite(extruder.get("pressure_advance")),
        "accel_mm_s2": _finite(toolhead.get("max_accel")),
        "extrude_factor": _finite(gcode_move.get("extrude_factor")),
    }

    metadata_provenance: dict[str, Any] = {
        "source": "server.files.metadata",
        "status": metadata_status,
    }
    if metadata_reason is not None:
        metadata_provenance["reason"] = metadata_reason
    if metadata_status == "available":
        metadata_provenance["fields"] = metadata

    provenance = {
        "filename": filename_source,
        "printer_state": "print_stats.state",
        "material": "server.files.metadata.filament_type" if material is not None else "unknown",
        "nozzle_mm": "server.files.metadata.nozzle_diameter"
        if nozzle_mm is not None
        else "unknown",
        "configured_nozzle_mm": "configfile.settings.extruder.nozzle_diameter"
        if configured_nozzle_mm is not None
        else "unknown",
        "parameters": {
            "pressure_advance": "extruder.pressure_advance"
            if parameters["pressure_advance"] is not None
            else "unknown",
            "accel_mm_s2": "toolhead.max_accel"
            if parameters["accel_mm_s2"] is not None
            else "unknown",
            "extrude_factor": "gcode_move.extrude_factor"
            if parameters["extrude_factor"] is not None
            else "unknown",
        },
        "metadata": metadata_provenance,
    }

    return {
        "material": material,
        "nozzle_mm": nozzle_mm,
        "configured_nozzle_mm": configured_nozzle_mm,
        "parameters": parameters,
        "filename": selected,
        "printer_state": printer_state,
        "provenance": provenance,
        "conflicts": conflicts,
        "effective_verified": False,
    }


__all__ = ["fetch_print_context"]
