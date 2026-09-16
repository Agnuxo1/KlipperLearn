"""Optional authenticated phone console; separate from evidence collection."""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import tempfile
import time
import threading
from pathlib import Path
from typing import Any

import httpx
from fastapi import Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from starlette.routing import Mount

from .trial_telemetry import TrialTelemetryError, validate_trial_telemetry
from .request_safety import install_request_safety, read_json_object, token_matches


_MODEL_EXTENSIONS = (".gcode", ".gco", ".g", ".g3d")
_HOME_STATES = {"standby", "complete", "cancelled", "error"}
_ACTIVE_PRINT_STATES = {"printing", "paused"}
_STREAM_GRACE_SECONDS = 30.0
_CAPABILITIES_QUERY = "/printer/objects/query?configfile&webhooks&print_stats&extruder"
_TELEMETRY_TRIAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_TELEMETRY_ACTIVE_FILENAME = "trial-telemetry-active.json"
_ACCELEROMETER_OBJECTS = (
    "adxl345",
    "lis2dw",
    "lis2dw12",
    "lis3dh",
    "mpu9250",
    "mpu6050",
    "mpu6500",
    "icm20948",
    "icm42688",
    "bmi160",
    "bmi088",
)


def _is_safe_model_path(path):
    if not isinstance(path, str) or not path:
        return False
    if any(ord(character) < 32 or ord(character) == 127 for character in path):
        return False
    if "\\" in path or ":" in path or path.startswith("/"):
        return False
    parts = path.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        return False
    return path.casefold().endswith(_MODEL_EXTENSIONS)


def _finite_temperature(value, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        numeric = float(value)
    except (OverflowError, ValueError):
        return False
    return math.isfinite(numeric) and 0 <= numeric <= maximum


def _finite_positive_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        numeric = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric <= 0:
        return None
    return numeric


def _finite_json_value(value):
    if value is None or isinstance(value, (bool, str)):
        return True
    if isinstance(value, (int, float)):
        try:
            return math.isfinite(float(value))
        except (OverflowError, ValueError):
            return False
    if isinstance(value, list):
        return all(_finite_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _finite_json_value(item) for key, item in value.items())
    return False


def _invalid_moonraker_response():
    raise HTTPException(503, "Invalid Moonraker response")


def _object_names(data):
    if not isinstance(data, dict):
        _invalid_moonraker_response()
    result = data.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("objects"), list):
        _invalid_moonraker_response()
    objects = result["objects"]
    if any(not isinstance(name, str) or not name for name in objects):
        _invalid_moonraker_response()
    return objects


def _webhooks_connected(webhooks):
    if not isinstance(webhooks, dict):
        _invalid_moonraker_response()
    state = webhooks.get("state")
    if not isinstance(state, str) or not state:
        _invalid_moonraker_response()
    if "ready" in webhooks and not isinstance(webhooks["ready"], bool):
        _invalid_moonraker_response()
    return state == "ready"


def _object_matches(name, marker):
    tokens = name.casefold().split()
    return bool(tokens) and tokens[0] == marker.casefold()


def _has_accelerometer(objects):
    return any(
        _object_matches(name, marker) for name in objects for marker in _ACCELEROMETER_OBJECTS
    )


def _printer_snapshot(data):
    if not isinstance(data, dict):
        _invalid_moonraker_response()
    result = data.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("status"), dict):
        _invalid_moonraker_response()
    status = result["status"]
    webhooks = status.get("webhooks")
    print_stats = status.get("print_stats")
    extruder_status = status.get("extruder")
    if not isinstance(print_stats, dict) or not isinstance(extruder_status, dict):
        _invalid_moonraker_response()
    printer_state = print_stats.get("state")
    if not isinstance(printer_state, str) or not printer_state:
        _invalid_moonraker_response()
    return status, _webhooks_connected(webhooks), printer_state


def _configured_limits(status):
    configfile = status.get("configfile")
    if not isinstance(configfile, dict):
        _invalid_moonraker_response()
    settings = configfile.get("settings")
    if not isinstance(settings, dict):
        _invalid_moonraker_response()

    extruder = settings.get("extruder")
    heater_bed = settings.get("heater_bed")
    printer = settings.get("printer")
    if not all(isinstance(section, dict) for section in (extruder, heater_bed, printer)):
        _invalid_moonraker_response()

    configured_extruder_max = _finite_positive_number(extruder.get("max_temp"))
    configured_bed_max = _finite_positive_number(heater_bed.get("max_temp"))
    max_velocity = _finite_positive_number(printer.get("max_velocity"))
    max_accel = _finite_positive_number(printer.get("max_accel"))
    if any(
        value is None
        for value in (
            configured_extruder_max,
            configured_bed_max,
            max_velocity,
            max_accel,
        )
    ):
        _invalid_moonraker_response()

    extruder_max = min(275.0, configured_extruder_max - 5.0)
    bed_max = min(110.0, configured_bed_max - 5.0)
    if not math.isfinite(extruder_max) or extruder_max <= 0:
        _invalid_moonraker_response()
    if not math.isfinite(bed_max) or bed_max <= 0:
        _invalid_moonraker_response()

    input_shaper = settings.get("input_shaper")
    if input_shaper is not None and (
        not isinstance(input_shaper, dict) or not _finite_json_value(input_shaper)
    ):
        _invalid_moonraker_response()

    return {
        "extruder_max": extruder_max,
        "bed_max": bed_max,
        "max_velocity": max_velocity,
        "max_accel": max_accel,
        "input_shaper": None if input_shaper is None else dict(input_shaper),
    }


def _temperature_text(value):
    if isinstance(value, int) or value.is_integer():
        return str(int(value))
    return str(value)


def _keep_mobile_static_mount_last(app):
    routes = app.router.routes
    for index, route in enumerate(routes):
        if isinstance(route, Mount) and route.path == "/mobile" and route.name == "mobile":
            routes.append(routes.pop(index))
            return


async def _iter_live_frames(
    request,
    latest,
    *,
    clock=time.monotonic,
    sleep=asyncio.sleep,
    grace_seconds=_STREAM_GRACE_SECONDS,
):
    """Emit fresh frames only; tolerate gaps without replaying stale camera data."""
    sequence = -1
    while latest["jpeg"] is not None and latest.get("active", True):
        if await request.is_disconnected():
            return
        now = clock()
        age = now - latest["at"]
        if age < 0 or age > grace_seconds:
            return
        if latest["seq"] != sequence and age <= 5.0:
            sequence = latest["seq"]
            jpeg = latest["jpeg"]
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                + str(len(jpeg)).encode()
                + b"\r\n\r\n"
                + jpeg
                + b"\r\n"
            )
        await sleep(0.2)


def _is_safe_trial_id(value: object) -> bool:
    return isinstance(value, str) and _TELEMETRY_TRIAL_ID.fullmatch(value) is not None


class _TrialTelemetryStore:
    """Persist validated phone snapshots below the experiment asset tree."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = threading.RLock()

    @staticmethod
    def _is_link(path: Path) -> bool:
        return path.is_symlink() or getattr(path, "is_junction", lambda: False)()

    @classmethod
    def _assert_no_links(cls, path: Path) -> None:
        for candidate in (path, *path.parents):
            if cls._is_link(candidate):
                raise OSError("telemetry path contains a symlink or junction")

    @classmethod
    def _ensure_directory(cls, path: Path) -> Path:
        cls._assert_no_links(path)
        path.mkdir(parents=True, exist_ok=True)
        cls._assert_no_links(path)
        if not path.is_dir():
            raise OSError("telemetry path is not a directory")
        return path

    def _telemetry_directory(self, *, create: bool) -> Path | None:
        if create:
            root = self._ensure_directory(self.root)
            assets = self._ensure_directory(root / "assets")
            return self._ensure_directory(assets / "telemetry")

        self._assert_no_links(self.root)
        if not self.root.exists():
            return None
        if not self.root.is_dir():
            raise OSError("experiment root is not a directory")
        assets = self.root / "assets"
        self._assert_no_links(assets)
        if not assets.exists():
            return None
        if not assets.is_dir():
            raise OSError("experiment assets path is not a directory")
        telemetry = assets / "telemetry"
        self._assert_no_links(telemetry)
        if not telemetry.exists():
            return None
        if not telemetry.is_dir():
            raise OSError("telemetry path is not a directory")
        return telemetry

    @staticmethod
    def _filename(trial_id: str) -> str:
        # UUID-like ids remain inspectable; ids with Windows-special characters
        # use a digest while retaining the canonical id inside the JSON payload.
        if re.fullmatch(r"[A-Za-z0-9._-]{1,120}", trial_id):
            return trial_id + ".json"
        return hashlib.sha256(trial_id.encode("utf-8")).hexdigest() + ".json"

    @classmethod
    def _atomic_write_json(cls, target: Path, value: dict[str, Any]) -> None:
        directory = target.parent
        cls._assert_no_links(directory)
        if cls._is_link(target) or (target.exists() and not target.is_file()):
            raise OSError("telemetry target is not a regular file")
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        temporary: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{target.stem}.",
                suffix=".tmp",
                dir=str(directory),
            )
            temporary = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _counts(snapshot: dict[str, Any], trial_id: str) -> dict[str, Any]:
        samples = snapshot.get("samples")
        if not isinstance(samples, dict):
            raise OSError("validated telemetry has no samples")
        return {
            "trial_id": trial_id,
            "counts": {
                "motion": len(samples.get("motion", [])),
                "audio_features": len(samples.get("audio_features", [])),
                "orientation": len(samples.get("orientation", [])),
            },
        }

    def set_active(self, trial_id: str | None) -> dict[str, Any]:
        with self._lock:
            self._ensure_directory(self.root)
            self._atomic_write_json(
                self.root / _TELEMETRY_ACTIVE_FILENAME,
                {"trial_id": trial_id},
            )
            return {"trial_id": trial_id}

    def claim_if_empty(self, trial_id: str) -> bool:
        with self._lock:
            if self.get_active().get("trial_id") is not None:
                return False
            self.set_active(trial_id)
            return True

    def release_if_owner(self, trial_id: str) -> bool:
        with self._lock:
            if self.get_active().get("trial_id") != trial_id:
                return False
            self.set_active(None)
            return True

    def get_active(self) -> dict[str, Any]:
        with self._lock:
            self._assert_no_links(self.root)
            if not self.root.exists():
                return {"trial_id": None}
            if not self.root.is_dir():
                raise OSError("experiment root is not a directory")
            target = self.root / _TELEMETRY_ACTIVE_FILENAME
            self._assert_no_links(target)
            if not target.exists():
                return {"trial_id": None}
            if not target.is_file():
                raise OSError("active telemetry target is not a regular file")
            try:
                state = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, TypeError, ValueError, RecursionError) as exc:
                raise OSError("stored active telemetry is invalid") from exc
            trial_id = state.get("trial_id") if isinstance(state, dict) else object()
            if trial_id is not None and not _is_safe_trial_id(trial_id):
                raise OSError("stored active telemetry trial id is invalid")
            if not isinstance(state, dict) or set(state) != {"trial_id"}:
                raise OSError("stored active telemetry has an invalid shape")
            return {"trial_id": trial_id}

    def save_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        trial_id = snapshot.get("trial_id")
        if not _is_safe_trial_id(trial_id):
            raise ValueError("trial_id no tiene un formato seguro")
        with self._lock:
            directory = self._telemetry_directory(create=True)
            if directory is None:
                raise OSError("Telemetry directory is unavailable")
            target = directory / self._filename(trial_id)
            # Immutable, content-addressed uploads: retries are idempotent and
            # later snapshots must never erase the evidence already collected.
            chunks = self._ensure_directory(directory / (self._filename(trial_id) + ".chunks"))
            if target.exists():
                self._assert_no_links(target)
                previous = json.loads(target.read_text(encoding="utf-8"))
                encoded_previous = json.dumps(previous, sort_keys=True, allow_nan=False)
                previous_id = hashlib.sha256(encoded_previous.encode()).hexdigest()
                if not (chunks / (previous_id + ".json")).exists():
                    self._atomic_write_json(chunks / (previous_id + ".json"), previous)
            encoded_snapshot = json.dumps(snapshot, sort_keys=True, allow_nan=False)
            chunk_id = hashlib.sha256(encoded_snapshot.encode()).hexdigest()
            if not (chunks / (chunk_id + ".json")).exists():
                self._atomic_write_json(chunks / (chunk_id + ".json"), snapshot)
            self._atomic_write_json(target, snapshot)
            return self._counts(snapshot, trial_id)

    def summary(self, trial_id: str) -> dict[str, Any]:
        if not _is_safe_trial_id(trial_id):
            raise ValueError("trial_id no tiene un formato seguro")
        with self._lock:
            directory = self._telemetry_directory(create=False)
            if directory is None:
                return self._counts({"samples": {}}, trial_id)
            target = directory / self._filename(trial_id)
            self._assert_no_links(target)
            if not target.exists():
                return self._counts({"samples": {}}, trial_id)
            if not target.is_file():
                raise OSError("telemetry target is not a regular file")
            try:
                snapshot = json.loads(target.read_text(encoding="utf-8"))
                normalized = validate_trial_telemetry(snapshot)
            except (OSError, TypeError, ValueError, RecursionError) as exc:
                raise OSError("stored telemetry is invalid") from exc
            if normalized.get("trial_id") != trial_id:
                raise OSError("stored telemetry trial id mismatch")
                # Include acknowledged windows as well as legacy cumulative uploads.
                # A collector restart resets t_ms, so its UTC origin is part of the
                # identity. Repeated/overlapping uploads must not inflate evidence.
            chunks = directory / (self._filename(trial_id) + ".chunks")
            self._assert_no_links(chunks)
            seen = {key: set() for key in ("motion", "orientation", "audio_features")}

            def include(value):
                if value.get("trial_id") != trial_id:
                    raise OSError("stored telemetry trial id mismatch")
                origin = value["started_at_utc"]
                for key in seen:
                    for sample in value["samples"][key]:
                        seen[key].add((origin, json.dumps(sample, sort_keys=True, allow_nan=False)))

            include(normalized)
            if chunks.exists():
                if not chunks.is_dir():
                    raise OSError("telemetry chunks path is not a directory")
                for path in chunks.glob("*.json"):
                    self._assert_no_links(path)
                    try:
                        include(
                            validate_trial_telemetry(json.loads(path.read_text(encoding="utf-8")))
                        )
                    except (TypeError, ValueError, RecursionError) as exc:
                        raise OSError("stored telemetry chunk is invalid") from exc
            return {
                "trial_id": trial_id,
                "counts": {key: len(values) for key, values in seen.items()},
            }


def install_companion(
    app,
    token,
    moonraker="http://127.0.0.1:7125",
    transport=None,
    camera_cache_path=None,
    experiments_root="data/experiments",
    local_connect_origin=None,
    local_connect_networks=(),
    enable_learning=False,
    enable_automatic_print=False,
):
    install_request_safety(app)
    if not isinstance(token, str) or not token or not token.isascii():
        raise ValueError("A non-empty ASCII authentication token is required")
    networks = tuple(ipaddress.ip_network(value) for value in local_connect_networks)
    viewer = hmac.new(token.encode(), b"camera-view-only-v1", hashlib.sha256).hexdigest()
    camera_cache = Path(camera_cache_path) if camera_cache_path is not None else None
    telemetry_store = _TrialTelemetryStore(experiments_root)
    try:
        cached = None
        if camera_cache is not None:
            with camera_cache.open("rb") as cached_file:
                cached = cached_file.read(1024 * 1024 + 1)
            if len(cached) > 1024 * 1024:
                cached = None
        if cached is not None and not (
            cached.startswith(b"\xff\xd8") and cached.endswith(b"\xff\xd9")
        ):
            cached = None
    except OSError:
        cached = None
    latest = {
        "jpeg": cached,
        "at": 0.0,
        "seq": 0,
        "active": False,
        "client_version": "unknown",
        "owner": None,
    }

    def authorize(candidate, expected=token):
        if not token_matches(candidate, expected):
            raise HTTPException(401, "Unauthorized")

    @app.post("/mobile/api/connect")
    async def connect_local(request: Request):
        # Explicitly enabled for the owner's LAN only. Exact Origin + Host and
        # a custom header prevent cross-site forms and DNS rebinding bootstrap.
        if not local_connect_origin or not networks:
            raise HTTPException(403, "Local connection is not configured on this server")
        from urllib.parse import urlsplit

        expected = urlsplit(local_connect_origin)
        if (
            request.headers.get("origin") != local_connect_origin
            or request.headers.get("host") != expected.netloc
            or request.headers.get("x-klipperlearn-connect") != "1"
            or request.headers.get("sec-fetch-site", "same-origin") != "same-origin"
        ):
            raise HTTPException(403, "Open KlipperLearn directly on the printer network")
        try:
            peer = ipaddress.ip_address(request.client.host)
        except (ValueError, AttributeError):
            raise HTTPException(403, "Cliente local no reconocido") from None
        if not any(peer in network for network in networks):
            raise HTTPException(403, "Connect to the printer Wi-Fi network")
        return Response(
            json.dumps({"result": {"token": token}}),
            media_type="application/json",
            headers={"Cache-Control": "no-store", "Vary": "Origin"},
        )

    async def printer(path, method="GET", payload=None):
        try:
            async with httpx.AsyncClient(timeout=5, trust_env=False, transport=transport) as client:
                request_options = {} if payload is None else {"json": payload}
                result = await client.request(method, moonraker + path, **request_options)
                result.raise_for_status()
                data = result.json()
                if isinstance(data, dict) and "error" in data:
                    raise HTTPException(409, "Klipper ha rechazado la orden")
                return data
        except HTTPException:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(503, "Unable to connect to Moonraker") from exc

    async def printer_state():
        data = await printer("/printer/objects/query?webhooks&print_stats")
        try:
            state = data["result"]["status"]
            webhooks = state["webhooks"]
            print_stats = state["print_stats"]
            webhooks_state = webhooks["state"]
            print_state = print_stats["state"]
        except (KeyError, TypeError) as exc:
            raise HTTPException(503, "Invalid Moonraker response") from exc
        return state, webhooks_state, print_state

    async def require_printer_state(allowed_states=None, forbidden_states=()):
        state, webhooks_state, print_state = await printer_state()
        if webhooks_state != "ready":
            raise HTTPException(409, "The printer state does not permit this action")
        if allowed_states is not None and print_state not in allowed_states:
            raise HTTPException(409, "The printer state does not permit this action")
        if print_state in forbidden_states:
            raise HTTPException(409, "The printer state does not permit this action")
        return state

    async def json_object(request):
        limit = 8 * 1024 * 1024 if "/trial-telemetry" in request.url.path else 256 * 1024
        return await read_json_object(request, limit)

    def authorize_request(request):
        candidates = request.headers.getlist("x-klipperlearn-token")
        if len(candidates) != 1:
            raise HTTPException(401, "Unauthorized")
        authorize(candidates[0])

    async def telemetry_call(method, *args):
        try:
            return await asyncio.to_thread(getattr(telemetry_store, method), *args)
        except (OSError, TypeError, ValueError, RecursionError):
            raise HTTPException(503, "Local telemetry could not be accessed") from None

    async def persist_trial_telemetry(request, expected_trial_id=None):
        authorize_request(request)
        if expected_trial_id is not None and not _is_safe_trial_id(expected_trial_id):
            raise HTTPException(422, "trial_id no tiene un formato seguro")
        payload = await json_object(request)
        try:
            snapshot = validate_trial_telemetry(payload)
        except TrialTelemetryError as exc:
            raise HTTPException(422, str(exc)) from None
        if expected_trial_id is not None and snapshot["trial_id"] != expected_trial_id:
            raise HTTPException(422, "trial_id de la ruta no coincide con el snapshot")
        return {"result": await telemetry_call("save_snapshot", snapshot)}

    @app.get("/mobile/api/trial-telemetry/active")
    async def get_active_trial(request: Request):
        authorize_request(request)
        return {"result": await telemetry_call("get_active")}

    @app.post("/mobile/api/trial-telemetry/active")
    async def set_active_trial(request: Request):
        authorize_request(request)
        payload = await json_object(request)
        if set(payload) != {"trial_id"}:
            raise HTTPException(422, "trial_id is required")
        trial_id = payload["trial_id"]
        if trial_id is not None and not _is_safe_trial_id(trial_id):
            raise HTTPException(422, "trial_id no tiene un formato seguro")
        return {"result": await telemetry_call("set_active", trial_id)}

    @app.post("/mobile/api/trial-telemetry")
    async def save_trial_telemetry(request: Request):
        return await persist_trial_telemetry(request)

    @app.post("/mobile/api/trial-telemetry/{trial_id}/snapshot")
    async def save_trial_telemetry_snapshot(trial_id: str, request: Request):
        return await persist_trial_telemetry(request, trial_id)

    @app.get("/mobile/api/trial-telemetry/{trial_id}/summary")
    async def trial_telemetry_summary(trial_id: str, request: Request):
        authorize_request(request)
        if not _is_safe_trial_id(trial_id):
            raise HTTPException(404, "Telemetry not found")
        return {"result": await telemetry_call("summary", trial_id)}

    async def model_files():
        data = await printer("/server/files/list?root=gcodes")
        try:
            entries = data["result"]
        except (KeyError, TypeError) as exc:
            raise HTTPException(503, "Invalid Moonraker response") from exc
        if not isinstance(entries, list):
            raise HTTPException(503, "Invalid Moonraker response")
        return sorted(
            (
                entry
                for entry in entries
                if isinstance(entry, dict) and _is_safe_model_path(entry.get("path"))
            ),
            key=lambda entry: entry["path"],
        )

    async def read_only_printer(path):
        try:
            return await printer(path)
        except HTTPException as exc:
            if exc.status_code == 409:
                raise HTTPException(503, "Invalid Moonraker response") from exc
            raise

    async def capability_snapshot():
        data = await read_only_printer(_CAPABILITIES_QUERY)
        status, connected, print_state = _printer_snapshot(data)
        return status, connected, print_state, _configured_limits(status)

    @app.get("/mobile/api/printer/status")
    async def status(x_klipperlearn_token: str | None = Header(default=None)):
        authorize(x_klipperlearn_token)
        return await printer(
            "/printer/objects/query?webhooks&print_stats&extruder&heater_bed&virtual_sdcard"
        )

    @app.get("/mobile/api/printer/print-context")
    async def print_context(
        filename: str | None = None, x_klipperlearn_token: str | None = Header(default=None)
    ):
        authorize(x_klipperlearn_token)
        if filename is not None and not _is_safe_model_path(filename):
            raise HTTPException(422, "Invalid print file")
        from .print_context import fetch_print_context

        try:
            result = await fetch_print_context(moonraker, filename=filename, transport=transport)
        except ValueError:
            raise HTTPException(503, "The print context could not be queried") from None
        return {"result": result}

    @app.get("/mobile/api/printer/capabilities")
    async def capabilities(x_klipperlearn_token: str | None = Header(default=None)):
        authorize(x_klipperlearn_token)
        objects = _object_names(await read_only_printer("/printer/objects/list"))
        status, connected, print_state, limits = await capability_snapshot()
        extruder = status["extruder"]
        object_names = {name.casefold() for name in objects}
        return {
            "result": {
                "connected": connected,
                "printer_state": print_state,
                "machine": {"name": "Klipper"},
                "limits": {
                    "extruder_max": limits["extruder_max"],
                    "bed_max": limits["bed_max"],
                    "max_velocity": limits["max_velocity"],
                    "max_accel": limits["max_accel"],
                },
                "features": {
                    "input_shaper": "input_shaper" in object_names,
                    "resonance_tester": "resonance_tester" in object_names,
                    "accelerometer": _has_accelerometer(objects),
                    "pressure_advance": "pressure_advance" in extruder,
                },
                "input_shaper": limits["input_shaper"],
                "calibration": {
                    "automatic_available": False,
                    "model_trained": False,
                },
            }
        }

    @app.get("/mobile/api/printer/files")
    async def files(x_klipperlearn_token: str | None = Header(default=None)):
        authorize(x_klipperlearn_token)
        return {"result": await model_files()}

    @app.post("/mobile/api/printer/home")
    async def home(x_klipperlearn_token: str | None = Header(default=None)):
        authorize(x_klipperlearn_token)
        await require_printer_state(allowed_states=_HOME_STATES)
        return await printer("/printer/gcode/script", "POST", {"script": "G28"})

    @app.post("/mobile/api/printer/temperature")
    async def temperature(
        request: Request,
        x_klipperlearn_token: str | None = Header(default=None),
    ):
        authorize(x_klipperlearn_token)
        payload = await json_object(request)
        if set(payload) != {"extruder", "bed"}:
            raise HTTPException(422, "extruder and bed are required")
        extruder = payload["extruder"]
        bed = payload["bed"]
        _, connected, print_state, limits = await capability_snapshot()
        if not _finite_temperature(extruder, limits["extruder_max"]) or not _finite_temperature(
            bed, limits["bed_max"]
        ):
            raise HTTPException(422, "Objetivo de temperatura fuera de rango")
        if not connected or print_state not in _HOME_STATES:
            raise HTTPException(409, "The printer state does not permit this action")
        script = f"M104 S{_temperature_text(extruder)}\nM140 S{_temperature_text(bed)}"
        return await printer("/printer/gcode/script", "POST", {"script": script})

    @app.post("/mobile/api/printer/cool")
    async def cool(x_klipperlearn_token: str | None = Header(default=None)):
        authorize(x_klipperlearn_token)
        await require_printer_state(allowed_states=_HOME_STATES)
        return await printer("/printer/gcode/script", "POST", {"script": "M104 S0\nM140 S0"})

    @app.post("/mobile/api/printer/start")
    async def start(
        request: Request,
        x_klipperlearn_token: str | None = Header(default=None),
    ):
        authorize(x_klipperlearn_token)
        payload = await json_object(request)
        if set(payload) != {"filename"} or not isinstance(payload["filename"], str):
            raise HTTPException(422, "A valid filename is required")
        filename = payload["filename"]
        if not _is_safe_model_path(filename):
            raise HTTPException(422, "Filename no permitido")
        await require_printer_state(allowed_states={"standby", "complete", "cancelled"})
        entries = await model_files()
        if not any(entry["path"] == filename for entry in entries):
            raise HTTPException(404, "File not found")
        if enable_automatic_print:
            learning = getattr(app.state, "klipperlearn_learning", None)
            if learning is None:
                raise HTTPException(503, "Learning is unavailable; no print has been started")
            manager = learning.automatic
            if (learning.setting("automatic_preferences") or {}).get(
                "enabled"
            ) is False and not filename.startswith("KlipperLearn-six-zones-"):
                unfinished = manager.pending()
                if unfinished and unfinished["phase"] not in ("restored", "not_started"):
                    raise HTTPException(
                        409, "Restoration of the previous trial must be verified first"
                    )
                return await printer("/printer/print/start", "POST", {"filename": filename})
            if manager.lock.locked():
                raise HTTPException(409, "A print is already being prepared")
            async with manager.lock:
                try:
                    async with asyncio.timeout(50):
                        async with httpx.AsyncClient(
                            base_url=moonraker, timeout=15, trust_env=False, transport=transport
                        ) as client:
                            response = await client.get(
                                "/printer/objects/query?webhooks&print_stats&extruder&gcode_move&toolhead&configfile"
                            )
                            response.raise_for_status()
                            operation = await manager.prepare(
                                client, filename, response.json()["result"]["status"]
                            )
                            await require_printer_state(
                                allowed_states={"standby", "complete", "cancelled"}
                            )
                            operation["phase"] = "start_sent"
                            manager.save(operation)
                            # Persist intent before this single physical request. Lost responses
                            # leave an unresolved operation, never an automatic duplicate start.
                            return await printer(
                                "/printer/print/start", "POST", {"filename": operation["filename"]}
                            )
                except ValueError as error:
                    raise HTTPException(409, str(error)) from None
                except (httpx.HTTPError, TimeoutError, UnicodeError, KeyError):
                    raise HTTPException(
                        503, "The trial could not be verified; check its state before retrying"
                    ) from None
        return await printer("/printer/print/start", "POST", {"filename": filename})

    @app.post("/mobile/api/printer/{action}")
    async def action(action: str, x_klipperlearn_token: str | None = Header(default=None)):
        authorize(x_klipperlearn_token)
        states = {"pause": {"printing"}, "resume": {"paused"}, "cancel": {"printing", "paused"}}
        if action not in states:
            raise HTTPException(404, "Action unavailable")
        await require_printer_state(allowed_states=states[action])
        return await printer("/printer/print/" + action, "POST")

    @app.put("/mobile/api/live/frame")
    async def frame(
        request: Request,
        x_klipperlearn_token: str | None = Header(default=None),
        x_klipperlearn_client_version: str | None = Header(default=None),
        x_klipperlearn_camera_session: str | None = Header(default=None),
    ):
        authorize(x_klipperlearn_token)
        if request.headers.get("content-type", "").split(";")[0] != "image/jpeg":
            raise HTTPException(415, "JPEG is required")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1024 * 1024:
                raise HTTPException(413, "Image too large")
        if not body.startswith(b"\xff\xd8") or not body.endswith(b"\xff\xd9"):
            raise HTTPException(422, "Invalid JPEG")
        owner = camera_owner(request, x_klipperlearn_camera_session)
        if latest["active"] and time.monotonic() - latest["at"] < 15 and latest["owner"] != owner:
            raise HTTPException(409, "Another device or tab owns the camera stream")
        client_version = x_klipperlearn_client_version or "unknown"
        if not re.fullmatch(r"console-[0-9]{1,4}", client_version):
            client_version = "unknown"
        latest.update(
            jpeg=bytes(body),
            at=time.monotonic(),
            seq=latest["seq"] + 1,
            client_version=client_version,
            owner=owner,
        )
        try:
            if camera_cache is not None:
                camera_cache.parent.mkdir(parents=True, exist_ok=True)
                temporary = camera_cache.with_suffix(".tmp")
                temporary.write_bytes(bytes(body))
                temporary.replace(camera_cache)
        except OSError:
            pass
        latest["active"] = True
        return {"received": True, "sequence": latest["seq"]}

    def camera_owner(request, session):
        if session is not None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", session):
                raise HTTPException(422, "Invalid camera identifier")
            return session
            # Legacy clients remain usable but cannot erase a current client's stream.
        return "legacy:" + (request.client.host if request.client else "unknown")

    @app.delete("/mobile/api/live/frame")
    async def stop(
        request: Request,
        x_klipperlearn_token: str | None = Header(default=None),
        x_klipperlearn_camera_session: str | None = Header(default=None),
    ):
        authorize(x_klipperlearn_token)
        if latest["owner"] is not None and latest["owner"] != camera_owner(
            request, x_klipperlearn_camera_session
        ):
            raise HTTPException(409, "This tab does not own the camera stream")
        latest.update(jpeg=None, at=0.0, active=False, owner=None, seq=latest["seq"] + 1)
        return {"stopped": True}

    def available():
        age = time.monotonic() - latest["at"]
        return latest["jpeg"] is not None and latest["active"] and 0 <= age <= 5.0

    @app.get("/mobile/api/live/snapshot")
    async def snapshot(x_klipperlearn_viewer: str | None = Header(default=None)):
        authorize(x_klipperlearn_viewer, viewer)
        if not available():
            raise HTTPException(503, "Phone camera disconnected")
        return Response(
            latest["jpeg"],
            media_type="image/jpeg",
            headers={
                "Cache-Control": "no-store",
                "X-KlipperLearn-Camera": "live"
                if latest["active"] and time.monotonic() - latest["at"] < 5
                else "last-frame",
                "X-KlipperLearn-Client-Version": latest["client_version"],
            },
        )

    @app.get("/mobile/api/live/stream")
    async def stream(request: Request, x_klipperlearn_viewer: str | None = Header(default=None)):
        authorize(x_klipperlearn_viewer, viewer)
        if not available():
            raise HTTPException(503, "Phone camera disconnected")

        async def frames():
            async for frame_bytes in _iter_live_frames(request, latest):
                yield frame_bytes

        return StreamingResponse(
            frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store"},
        )

    from .calibration_api import install_calibration_api

    install_calibration_api(app, token, moonraker, transport=transport)
    from .experiment_api import install_experiment_api

    install_experiment_api(app, token, experiments_root)
    from .photo_pair import install_photo_pair

    install_photo_pair(app, token, experiments_root)
    from .printer_cameras import install_printer_cameras

    install_printer_cameras(app, token, moonraker, experiments_root, transport=transport)
    if enable_learning:
        try:
            from .learning_service import install_learning_service

            learning_service = install_learning_service(
                app, token, moonraker, experiments_root, telemetry_store, transport=transport
            )
            learning_service.automatic_configured = enable_automatic_print
        except (OSError, ImportError, ValueError):
            # Learning storage/dependencies must not take down printer control.
            import logging

            logging.getLogger(__name__).warning(
                "Learning unavailable; printer control remains available"
            )
    _keep_mobile_static_mount_last(app)
    app.state.klipperlearn_companion_installed = True
    return viewer
