"""Pure evidence-capture primitives for the OctoPrint integration."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any

SCHEMA = "klipperlearn.octoprint-evidence/v1"
_CHUNK_SIZE = 1024 * 1024
_SAFE_PREFIX = re.compile(r"[^a-z0-9_-]+")


class CaptureCancelled(RuntimeError):
    """Raised when OctoPrint is shutting down during a background file hash."""


def utc_now() -> str:
    """Return a timezone-aware UTC timestamp in a stable ISO-8601 representation."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hash_regular_file(path: str | os.PathLike[str], cancel: Event | None = None) -> tuple[str, int]:
    """Stream a regular non-symlink file and return its SHA-256 and byte count."""
    candidate = Path(path)
    if candidate.is_symlink():
        raise ValueError("Refusing to hash a symbolic link")
    if not candidate.is_file():
        raise ValueError("Evidence source is not a regular file")

    digest = hashlib.sha256()
    size = 0
    with candidate.open("rb") as handle:
        while True:
            if cancel is not None and cancel.is_set():
                raise CaptureCancelled("Capture cancelled during shutdown")
            block = handle.read(_CHUNK_SIZE)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _file_identity(storage: str, path: str, *, size: int | None = None) -> dict[str, Any]:
    normalized = str(path).replace("\\", "/")
    result: dict[str, Any] = {
        "storage": str(storage),
        "path": normalized,
        "name": normalized.rsplit("/", 1)[-1],
    }
    if isinstance(size, int) and size >= 0:
        result["size_bytes"] = size
    return result


def build_file_manifest(
    storage: str,
    storage_path: str,
    disk_path: str | os.PathLike[str],
    *,
    captured_at: str | None = None,
    cancel: Event | None = None,
) -> dict[str, Any]:
    """Build a content-addressed manifest without exposing the absolute host path."""
    sha256, size = hash_regular_file(disk_path, cancel=cancel)
    return {
        "schema": SCHEMA,
        "captured_at": captured_at or utc_now(),
        "source": {"kind": "octoprint_file", "event": "FileAdded"},
        "file": {**_file_identity(storage, storage_path, size=size), "sha256": sha256},
        "privacy": {
            "gcode_included": False,
            "absolute_host_path_included": False,
            "user_identity_included": False,
        },
    }


def build_print_manifest(
    event: str,
    payload: dict[str, Any] | None,
    *,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Normalize a print lifecycle event to a minimal, non-user-identifying record."""
    source = dict(payload or {})
    storage = source.get("origin", "unknown")
    storage_path = source.get("path") or source.get("name") or "unknown"
    print_data: dict[str, Any] = {"state": str(event)}
    if isinstance(source.get("time"), (int, float)) and source["time"] >= 0:
        print_data["elapsed_seconds"] = float(source["time"])
    if isinstance(source.get("reason"), str) and source["reason"]:
        print_data["reason"] = source["reason"]
    if isinstance(source.get("progress"), (int, float)):
        print_data["progress_percent"] = float(source["progress"])

    size = source.get("size") if isinstance(source.get("size"), int) else None
    return {
        "schema": SCHEMA,
        "captured_at": captured_at or utc_now(),
        "source": {"kind": "octoprint_event", "event": str(event)},
        "file": _file_identity(str(storage), str(storage_path), size=size),
        "print": print_data,
        "privacy": {
            "gcode_included": False,
            "absolute_host_path_included": False,
            "user_identity_included": False,
            "printer_network_identity_included": False,
        },
    }


def store_manifest(directory: str | os.PathLike[str], prefix: str, payload: dict[str, Any]) -> Path:
    """Write one immutable JSON manifest with restrictive permissions where supported."""
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_prefix = _SAFE_PREFIX.sub("-", prefix.lower()).strip("-") or "evidence"
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    identity = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    target = target_dir / f"{safe_prefix}-{identity}.json"
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            target.unlink(missing_ok=True)
        finally:
            raise
    return target
