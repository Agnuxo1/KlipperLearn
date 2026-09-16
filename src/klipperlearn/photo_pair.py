"""Authenticated, persistent queue for automatic torch-off/torch-on photos.

The browser uploads the two JPEGs through the existing experiment photo route.
This module only coordinates the pair and records its result; it never talks to
Moonraker or changes printer state.
"""

from __future__ import annotations

import asyncio
import datetime as _datetime
import hmac
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import uuid
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import Response

from .experiment_store import ExperimentStore


__all__ = ["install_photo_pair"]


_BODY_LIMIT = 32 * 1024
_ERROR_LIMIT = 2048
_TTL_SECONDS = 120
_TRIAL_ID = re.compile(r"[0-9a-f]{32}", re.ASCII)
_JOB_ID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.ASCII,
)
_NO_STORE = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
_LIGHT_MODES = ("torch-off", "torch-on")
_JOB_STATUSES = {"pending", "running", "complete", "completed", "error", "expired"}


def _now_epoch() -> float:
    return time.time()


def _utc_timestamp(epoch: float | None = None) -> str:
    value = _now_epoch() if epoch is None else epoch
    return (
        _datetime.datetime.fromtimestamp(value, _datetime.timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _invalid() -> HTTPException:
    return HTTPException(422, "The capture data are invalid")


def _validate_json(value: Any, *, depth: int = 0, nodes: list[int] | None = None) -> None:
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if nodes[0] > 1024 or depth > 32:
        raise ValueError("json bounds")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        value.encode("utf-8", errors="strict")
        if len(value) > _ERROR_LIMIT:
            raise ValueError("text bounds")
        return
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite number")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item, depth=depth + 1, nodes=nodes)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("json key")
            _validate_json(key, depth=depth + 1, nodes=nodes)
            _validate_json(item, depth=depth + 1, nodes=nodes)
        return
    raise ValueError("json value")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite json constant")


async def _read_json(request: Request) -> dict[str, Any]:
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
            raise HTTPException(413, "The request body exceeds the permitted limit")
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _BODY_LIMIT:
            raise HTTPException(413, "The request body exceeds the permitted limit")
        body.extend(chunk)
    try:
        payload = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
        _validate_json(payload)
    except (UnicodeError, ValueError, TypeError, OverflowError, RecursionError):
        raise _invalid() from None
    if not isinstance(payload, dict):
        raise _invalid()
    return payload


def _safe_error(value: Any, token: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > _ERROR_LIMIT
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise _invalid()
    return value.replace(token, "[oculto]")


def _job_id(value: str) -> str:
    if not isinstance(value, str) or not _JOB_ID.fullmatch(value):
        raise HTTPException(404, "Captura no encontrada")
    return value


def _trial_id(value: Any) -> str:
    if not isinstance(value, str) or not _TRIAL_ID.fullmatch(value):
        raise HTTPException(404, "Experimento no encontrado")
    return value


def _response(result: Any, *, status_code: int = 200) -> Response:
    try:
        content = json.dumps(
            {"result": result},
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(503, "The response could not be prepared") from None
    return Response(
        content, status_code=status_code, media_type="application/json", headers=_NO_STORE
    )


class _PhotoPairManager:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.pair_root = self.root / "photo-pairs"
        self._lock = threading.RLock()
        self._store: ExperimentStore | None = None

    def _experiment_store(self) -> ExperimentStore:
        if self._store is None:
            self._store = ExperimentStore(self.root)
        return self._store

    def _read_jobs_locked(self) -> list[dict[str, Any]]:
        if not self.pair_root.exists():
            return []
        if self.pair_root.is_symlink() or not self.pair_root.is_dir():
            raise OSError("photo pair directory unavailable")
        jobs: list[dict[str, Any]] = []
        for path in sorted(self.pair_root.iterdir(), key=lambda item: item.name):
            if path.suffix != ".json" or path.is_symlink() or not path.is_file():
                continue
            try:
                if path.stat().st_size > 256 * 1024:
                    continue
                value = json.loads(path.read_text(encoding="utf-8"))
                if (
                    not isinstance(value, dict)
                    or not isinstance(value.get("id"), str)
                    or not _JOB_ID.fullmatch(value["id"])
                    or path.stem != value["id"]
                    or value.get("status") not in _JOB_STATUSES
                ):
                    continue
                jobs.append(value)
            except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return jobs

    def _write_job_locked(self, job: dict[str, Any]) -> None:
        self.pair_root.mkdir(parents=True, exist_ok=True)
        if self.pair_root.is_symlink() or not self.pair_root.is_dir():
            raise OSError("photo pair directory unavailable")
        target = self.pair_root / f"{job['id']}.json"
        temporary = self.pair_root / f".{job['id']}.{uuid.uuid4().hex}.tmp"
        try:
            encoded = json.dumps(
                job,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _public_job(job: dict[str, Any]) -> dict[str, Any]:
        result = dict(job)
        result.pop("expires_at_epoch", None)
        result.pop("created_at_epoch", None)
        result.pop("claimed_at_epoch", None)
        result.pop("completed_at_epoch", None)
        result.pop("updated_at_epoch", None)
        return result

    def _expire_locked(self, jobs: list[dict[str, Any]], now: float) -> None:
        for job in jobs:
            if job.get("status") not in {"pending", "running"}:
                continue
            expires = job.get("expires_at_epoch")
            if (
                isinstance(expires, (int, float))
                and not isinstance(expires, bool)
                and now >= expires
            ):
                job.update(
                    status="expired",
                    error="The capture expired before completion.",
                    updated_at=_utc_timestamp(now),
                    updated_at_epoch=now,
                    expired_at=_utc_timestamp(now),
                    expired_at_epoch=now,
                )
                self._write_job_locked(job)

    def _find_locked(self, jobs: list[dict[str, Any]], identifier: str) -> dict[str, Any]:
        for job in jobs:
            if job.get("id") == identifier:
                return job
        raise HTTPException(404, "Captura no encontrada")

    def _ensure_trial_locked(self, trial_id: str) -> None:
        try:
            self._experiment_store().get_trial(trial_id)
        except (KeyError, ValueError):
            raise HTTPException(404, "Experimento no encontrado") from None

    def enqueue(self, trial_id: str) -> dict[str, Any]:
        with self._lock:
            self._ensure_trial_locked(trial_id)
            now = _now_epoch()
            jobs = self._read_jobs_locked()
            self._expire_locked(jobs, now)
            if any(job.get("status") in {"pending", "running"} for job in jobs):
                raise HTTPException(409, "A capture is already in progress")

            identifier = str(uuid.uuid4())
            expires = now + _TTL_SECONDS
            names = [f"{identifier}-{mode}.jpg" for mode in _LIGHT_MODES]
            job = {
                "schema_version": 1,
                "id": identifier,
                "job_id": identifier,
                "trial_id": trial_id,
                "status": "pending",
                "created_at": _utc_timestamp(now),
                "updated_at": _utc_timestamp(now),
                "expires_at": _utc_timestamp(expires),
                "created_at_epoch": now,
                "updated_at_epoch": now,
                "expires_at_epoch": expires,
                "ttl_seconds": _TTL_SECONDS,
                "light_modes": list(_LIGHT_MODES),
                "metadata": {
                    "light_modes": list(_LIGHT_MODES),
                    "photo_names": names,
                },
                "photo_names": names,
                "photos": [
                    {
                        "mode": mode,
                        "light_mode": mode,
                        "original_name": name,
                        "persisted": False,
                    }
                    for mode, name in zip(_LIGHT_MODES, names)
                ],
                "error": None,
                "claimed_at": None,
                "completed_at": None,
            }
            self._write_job_locked(job)
            return self._public_job(job)

    def claim_next(self) -> dict[str, Any] | None:
        with self._lock:
            now = _now_epoch()
            jobs = self._read_jobs_locked()
            self._expire_locked(jobs, now)
            pending = [job for job in jobs if job.get("status") == "pending"]
            if not pending:
                return None
            job = min(pending, key=lambda item: item.get("created_at_epoch", float("inf")))
            job.update(
                status="running",
                claimed_at=_utc_timestamp(now),
                claimed_at_epoch=now,
                updated_at=_utc_timestamp(now),
                updated_at_epoch=now,
            )
            self._write_job_locked(job)
            return self._public_job(job)

    def status(self, identifier: str) -> dict[str, Any]:
        with self._lock:
            now = _now_epoch()
            jobs = self._read_jobs_locked()
            self._expire_locked(jobs, now)
            return self._public_job(self._find_locked(jobs, identifier))

    def _persisted_photos_locked(self, job: dict[str, Any]) -> list[dict[str, Any]] | None:
        try:
            trial = self._experiment_store().get_trial(job["trial_id"])
        except (KeyError, ValueError):
            return None
        records = trial.get("photos") if isinstance(trial, dict) else None
        if not isinstance(records, list):
            return None
        by_name: dict[str, dict[str, Any]] = {}
        assets_path = self.root / "assets"
        if (
            assets_path.is_symlink()
            or getattr(assets_path, "is_junction", lambda: False)()
            or not assets_path.is_dir()
        ):
            return None
        assets_root = assets_path.resolve()
        for record in records:
            if not isinstance(record, dict):
                continue
            name = record.get("original_name")
            relative = record.get("relative_path")
            if not isinstance(name, str) or not isinstance(relative, str):
                continue
            if name not in {f"{job['id']}-{mode}.jpg" for mode in _LIGHT_MODES}:
                continue
            candidate = (self.root / relative).resolve()
            try:
                inside_assets = candidate.is_relative_to(assets_root)
            except AttributeError:  # pragma: no cover - Python 3.10 fallback
                inside_assets = assets_root == candidate or assets_root in candidate.parents
            if (
                not inside_assets
                or candidate.is_symlink()
                or getattr(candidate, "is_junction", lambda: False)()
                or not candidate.is_file()
            ):
                continue
            by_name[name] = record
        result: list[dict[str, Any]] = []
        for mode in _LIGHT_MODES:
            name = f"{job['id']}-{mode}.jpg"
            record = by_name.get(name)
            if record is None:
                return None
            result.append(
                {
                    "mode": mode,
                    "light_mode": mode,
                    "original_name": name,
                    "relative_path": record.get("relative_path"),
                    "sha256": record.get("sha256"),
                    "byte_count": record.get("byte_count"),
                    "persisted": True,
                }
            )
        return result

    def complete(self, identifier: str, error: str | None, token: str) -> dict[str, Any]:
        with self._lock:
            now = _now_epoch()
            jobs = self._read_jobs_locked()
            self._expire_locked(jobs, now)
            job = self._find_locked(jobs, identifier)
            if job.get("status") not in {"pending", "running"}:
                raise HTTPException(409, "The capture has already finished")
            if error is not None:
                job.update(
                    status="error",
                    error=_safe_error(error, token),
                    completed_at=_utc_timestamp(now),
                    completed_at_epoch=now,
                    updated_at=_utc_timestamp(now),
                    updated_at_epoch=now,
                )
                self._write_job_locked(job)
                return self._public_job(job)

            photos = self._persisted_photos_locked(job)
            if photos is None:
                raise HTTPException(409, "Both photographs have not been saved yet")
            job.update(
                status="complete",
                error=None,
                photos=photos,
                completed_at=_utc_timestamp(now),
                completed_at_epoch=now,
                updated_at=_utc_timestamp(now),
                updated_at_epoch=now,
            )
            self._write_job_locked(job)
            return self._public_job(job)


def install_photo_pair(app, token, root="data/experiments"):
    """Install the authenticated local photo-pair queue on a FastAPI app."""

    if not isinstance(token, str) or not token:
        raise ValueError("A local authentication token is required")
    expected = token.encode("utf-8")
    manager = _PhotoPairManager(root)

    def authorize(request: Request) -> None:
        candidates = request.headers.getlist("x-klipperlearn-token")
        if len(candidates) != 1:
            raise HTTPException(401, "Unauthorized")
        try:
            valid = hmac.compare_digest(candidates[0].encode("utf-8"), expected)
        except (UnicodeError, AttributeError):
            valid = False
        if not valid:
            raise HTTPException(401, "Unauthorized")

    async def invoke(method: str, *args: Any) -> Any:
        try:
            return await asyncio.to_thread(getattr(manager, method), *args)
        except HTTPException:
            raise
        except (OSError, ValueError, TypeError):
            raise HTTPException(503, "The capture could not be completed") from None
        except Exception:
            raise HTTPException(503, "The capture could not be completed") from None

    @app.post("/mobile/api/photo-pairs", status_code=202)
    async def queue_photo_pair(request: Request):
        authorize(request)
        payload = await _read_json(request)
        if set(payload) != {"trial_id"}:
            raise _invalid()
        result = await invoke("enqueue", _trial_id(payload["trial_id"]))
        return _response(result, status_code=202)

    @app.get("/mobile/api/photo-pairs/next")
    async def next_photo_pair(request: Request):
        authorize(request)
        result = await invoke("claim_next")
        return _response(result)

    @app.get("/mobile/api/photo-pairs/{job_id}")
    async def photo_pair_status(job_id: str, request: Request):
        authorize(request)
        return _response(await invoke("status", _job_id(job_id)))

    @app.post("/mobile/api/photo-pairs/{job_id}/complete")
    async def complete_photo_pair(job_id: str, request: Request):
        authorize(request)
        payload = await _read_json(request)
        if set(payload) - {"error"}:
            raise _invalid()
        error = None if "error" not in payload else payload["error"]
        if error is not None:
            error = _safe_error(error, token)
        result = await invoke("complete", _job_id(job_id), error, token)
        return _response(result)

    return app
