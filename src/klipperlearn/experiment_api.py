"Minimal experiment-contract facade.\n\nThe API neither controls printers nor interprets paths inside metadata or\nevidence. ExperimentStore remains the authority for persisted input validation\nand scoring.\n"

from __future__ import annotations

import asyncio
import hmac
import json
import math
import re
import threading
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import Response

from .experiment_store import ExperimentStore


class ExperimentAPI:
    """Expose the experiment contract without coupling it to UI or hardware."""

    def __init__(self, root: str | Path) -> None:
        self.store = ExperimentStore(root)

    def create_trial(
        self,
        context: dict,
        parameters: dict,
        objective_score: float | None = None,
        evidence: dict | None = None,
    ) -> dict:
        return self.store.create_trial(context, parameters, objective_score, evidence)

    def rate_trial(self, trial_id: str, ratings: dict, comment: str = "") -> dict:
        # The facade does not inspect or reinterpret a user's rating payload.
        return self.store.rate_trial(trial_id, ratings, comment)

    def get_trial(self, id: str) -> dict:
        return self.store.get_trial(id)

    def list_trials(self, limit: int = 50, offset: int = 0) -> list:
        return self.store.list_trials(limit, offset)

    def recent_trials(self, limit: int = 50, offset: int = 0) -> list:
        return self.store.recent_trials(limit, offset)

    def export_jsonl(self) -> str:
        return self.store.export_jsonl()

    def backup(self, destination: str | Path) -> Path:
        return self.store.backup(destination)


__all__ = ["ExperimentAPI", "ExperimentStore", "install_experiment_api"]

_BODY_LIMIT = 256 * 1024
_PHOTO_LIMIT = 8 * 1024 * 1024
_IDENTIFIER = re.compile(r"[0-9a-f]{32}", re.ASCII)
_SHA256 = re.compile(r"[0-9a-fA-F]{64}", re.ASCII)
_CONTEXT_REQUIRED = {"printer_id", "model_sha256", "material", "nozzle_mm", "session_id"}
_RATINGS = {"speed", "surface", "geometry"}
_NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _invalid():
    return HTTPException(422, "The experiment data are invalid")


def _validate_json(value, depth=0):
    if depth > 64:
        raise ValueError("JSON depth")
    if isinstance(value, str):
        value.encode("utf-8", errors="strict")
    elif value is None or isinstance(value, bool):
        return
    elif isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError("Non-finite JSON number")
    elif isinstance(value, list):
        for item in value:
            _validate_json(item, depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON key")
            _validate_json(key, depth + 1)
            _validate_json(item, depth + 1)
    else:
        raise ValueError("JSON value")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("Non-finite JSON constant")


async def _read_json(request):
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise HTTPException(415, "application/json is required")
    lengths = request.headers.getlist("content-length")
    if lengths:
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,12}", lengths[0]):
            raise _invalid()
        if int(lengths[0]) > _BODY_LIMIT:
            raise HTTPException(413, "The request body exceeds 256 KiB")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _BODY_LIMIT:
            raise HTTPException(413, "The request body exceeds 256 KiB")
        body.extend(chunk)
    try:
        value = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        _validate_json(value)
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise _invalid() from None
    if not isinstance(value, dict):
        raise _invalid()
    return value


def _number(value, minimum, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid()
    try:
        valid = math.isfinite(value) and value >= minimum
        if maximum is not None:
            valid = valid and value <= maximum
    except (ValueError, OverflowError):
        valid = False
    if not valid:
        raise _invalid()
    return value


def _text(value, maximum):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise _invalid()
    return value


def _identifier(value):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise HTTPException(404, "Experimento no encontrado")
    return value


def _create_values(payload):
    if not {"context", "parameters"} <= payload.keys() or payload.keys() - {
        "context",
        "parameters",
        "objective_score",
        "evidence",
    }:
        raise _invalid()
    context = payload["context"]
    if not isinstance(context, dict) or not _CONTEXT_REQUIRED <= context.keys():
        raise _invalid()
    _text(context["printer_id"], 128)
    _text(context["session_id"], 128)
    _text(context["material"], 128)
    if not isinstance(context["model_sha256"], str) or not _SHA256.fullmatch(
        context["model_sha256"]
    ):
        raise _invalid()
    if _number(context["nozzle_mm"], 0) <= 0:
        raise _invalid()
    if not isinstance(payload["parameters"], dict):
        raise _invalid()
    objective = payload.get("objective_score")
    if objective is not None:
        _number(objective, 0, 100)
    evidence = payload.get("evidence")
    if evidence is not None and not isinstance(evidence, dict):
        raise _invalid()
        # Manual objective/evidence never become validated or training-ready data.
    evidence = {
        "provenance": "user_supplied",
        "validated": False,
        "training_eligible": False,
        "data": evidence,
    }
    return context, payload["parameters"], objective, evidence


def _rating_values(payload):
    if "ratings" not in payload or payload.keys() - {"ratings", "comment"}:
        raise _invalid()
    ratings = payload["ratings"]
    if not isinstance(ratings, dict) or set(ratings) != _RATINGS:
        raise _invalid()
    for value in ratings.values():
        if type(value) is not int:
            raise _invalid()
        _number(value, 0, 5)
    comment = payload.get("comment", "")
    if not isinstance(comment, str) or len(comment) > 4096:
        raise _invalid()
    return ratings, comment


def _pagination(request):
    if set(request.query_params) - {"limit", "offset"}:
        raise _invalid()
    values = {}
    for name, default, minimum, maximum in (("limit", "50", 1, 200), ("offset", "0", 0, 1_000_000)):
        entries = request.query_params.getlist(name)
        if len(entries) > 1:
            raise _invalid()
        raw = entries[0] if entries else default
        if not re.fullmatch(r"[0-9]{1,7}", raw):
            raise _invalid()
        value = int(raw)
        if not minimum <= value <= maximum:
            raise _invalid()
        values[name] = value
    return values


def install_experiment_api(app, token, root="data/experiments"):
    """Install authenticated local routes; caller owns static-mount ordering."""
    if not isinstance(token, str) or not token:
        raise ValueError("A local authentication token is required")
    expected = token.encode("utf-8")
    root_path = Path(root)
    store_holder = {}
    initialization_lock = threading.Lock()

    def authorize(request):
        candidates = request.headers.getlist("x-klipperlearn-token")
        if len(candidates) != 1 or not hmac.compare_digest(candidates[0].encode("utf-8"), expected):
            raise HTTPException(401, "Unauthorized")

    def store():
        with initialization_lock:
            if "value" not in store_holder:
                store_holder["value"] = ExperimentStore(root_path)
            return store_holder["value"]

    async def invoke(method, *args, **kwargs):
        def work():
            try:
                instance = store()
            except Exception:
                raise HTTPException(503, "The experiment store is unavailable") from None
            try:
                if method == "suggest":
                    from .experiment_learning import propose_from_history

                    records = []
                    for offset in range(0, 1001, 200):
                        page = instance.list_trials(limit=200, offset=offset)
                        records.extend(page)
                        if len(records) > 1000:
                            raise ValueError("History requires offline processing")
                        if len(page) < 200:
                            break
                    result = propose_from_history(records, **kwargs)
                else:
                    result = getattr(instance, method)(*args, **kwargs)
                if method in {"get_trial", "rate_trial"} and result is None:
                    raise FileNotFoundError()
            except (FileNotFoundError, KeyError):
                if method in {"get_trial", "rate_trial"}:
                    raise HTTPException(404, "Experimento no encontrado") from None
                raise HTTPException(503, "The store could not be queried") from None
            except (ValueError, TypeError):
                raise _invalid() from None
            except Exception:
                raise HTTPException(503, "The local operation could not be completed") from None
            try:
                if method == "export_jsonl":
                    if not isinstance(result, str):
                        raise ValueError()
                    return result.encode("utf-8")
                _validate_json(result)
                return json.dumps({"result": result}, ensure_ascii=False, allow_nan=False).encode(
                    "utf-8"
                )
            except (ValueError, TypeError, OverflowError, RecursionError):
                raise HTTPException(503, "The store response is unavailable") from None

        return await asyncio.to_thread(work)

    @app.get("/mobile/api/experiments")
    async def list_experiments(request: Request):
        authorize(request)
        body = await invoke("list_trials", **_pagination(request))
        return Response(body, media_type="application/json", headers=_NO_STORE)

    @app.post("/mobile/api/experiments", status_code=201)
    async def create_experiment(request: Request):
        authorize(request)
        context, parameters, objective, evidence = _create_values(await _read_json(request))
        body = await invoke(
            "create_trial", context, parameters, objective_score=objective, evidence=evidence
        )
        return Response(body, status_code=201, media_type="application/json", headers=_NO_STORE)

    @app.get("/mobile/api/experiments/recent")
    async def recent_experiments(request: Request):
        authorize(request)
        body = await invoke("recent_trials", **_pagination(request))
        return Response(body, media_type="application/json", headers=_NO_STORE)

    @app.post("/mobile/api/experiments/suggest")
    async def suggest_experiment(request: Request):
        authorize(request)
        payload = await _read_json(request)
        if set(payload) != {"anchor_id", "parameter", "bounds", "maximum_step", "current"}:
            raise _invalid()
        _identifier(payload["anchor_id"])
        body = await invoke("suggest", **payload)
        return Response(body, media_type="application/json", headers=_NO_STORE)

        # Static export before the dynamic identifier routes.

    @app.get("/mobile/api/experiments/export/jsonl")
    async def export_experiments(request: Request):
        authorize(request)
        body = await invoke("export_jsonl")
        return Response(
            body,
            media_type="application/x-ndjson",
            headers={
                **_NO_STORE,
                "Content-Disposition": 'attachment; filename="experiments.jsonl"',
            },
        )

    @app.get("/mobile/api/experiments/{trial_id}")
    async def get_experiment(trial_id: str, request: Request):
        authorize(request)
        body = await invoke("get_trial", _identifier(trial_id))
        return Response(body, media_type="application/json", headers=_NO_STORE)

    @app.post("/mobile/api/experiments/{trial_id}/ratings")
    async def rate_experiment(trial_id: str, request: Request):
        authorize(request)
        _identifier(trial_id)
        ratings, comment = _rating_values(await _read_json(request))
        body = await invoke("rate_trial", trial_id, ratings, comment=comment)
        return Response(body, media_type="application/json", headers=_NO_STORE)

    @app.put("/mobile/api/experiments/{trial_id}/photos")
    async def add_experiment_photo(trial_id: str, request: Request):
        authorize(request)
        _identifier(trial_id)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "image/jpeg":
            raise HTTPException(415, "A JPEG photograph is required")
        name = request.headers.get("x-klipperlearn-filename", "photo.jpg")
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 255
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
        ):
            raise _invalid()
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > _PHOTO_LIMIT:
                raise HTTPException(413, "The photograph exceeds 8 MiB")
            content.extend(chunk)
        body = await invoke("add_photo", trial_id, bytes(content), original_name=name)
        return Response(body, media_type="application/json", headers=_NO_STORE)

    return app
