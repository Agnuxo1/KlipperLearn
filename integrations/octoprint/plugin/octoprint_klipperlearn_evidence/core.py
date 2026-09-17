"""Bounded, privacy-filtered local evidence primitives for the OctoPrint plugin.

SPDX-License-Identifier: GPL-3.0-or-later
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any

SCHEMA = "klipperlearn.octoprint-evidence/v1"
_CHUNK_SIZE = 1024 * 1024
MAX_FILE_BYTES = 512 * 1024 * 1024
_SAFE_PREFIX = re.compile(r"[^a-z0-9_-]+")
_EVENTS = {"PrintStarted", "PrintDone", "PrintFailed", "PrintCancelled"}
_REASONS = {"error", "cancelled", "canceled", "cancel", "timeout", "communication_error"}


class CaptureCancelled(RuntimeError):
    """Raised when OctoPrint is shutting down during a background file hash."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def hash_regular_file(path: str | os.PathLike[str], cancel: Event | None = None) -> tuple[str, int]:
    """Hash one bounded regular file and reject file replacement/mutation races."""
    candidate = Path(path)
    before = candidate.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or getattr(before, "st_file_attributes", 0) & 0x400
        or not 0 < before.st_size <= MAX_FILE_BYTES
    ):
        raise ValueError("Evidence source must be a nonempty regular file of at most 512 MiB")
    digest, size = hashlib.sha256(), 0
    with candidate.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("Evidence source changed before reading")
        while True:
            if cancel is not None and cancel.is_set():
                raise CaptureCancelled("Capture cancelled during shutdown")
            block = handle.read(_CHUNK_SIZE)
            if not block:
                break
            size += len(block)
            if size > MAX_FILE_BYTES:
                raise ValueError("Evidence source grew beyond 512 MiB")
            digest.update(block)
        after = os.fstat(handle.fileno())
    current = candidate.lstat()
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_mode)
    if size != before.st_size or stamp(before) != stamp(after) or stamp(after) != stamp(current):
        raise ValueError("Evidence source changed while reading")
    return digest.hexdigest(), size


def _number(value: Any, maximum: float = 1e12) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value) if math.isfinite(value) and 0 <= value <= maximum else None
    except (OverflowError, ValueError):
        return None


def _file_identity(storage: str, path: str, *, size: int | None = None) -> dict[str, Any]:
    """Retain a relative storage name; never stringify arbitrary metadata objects."""
    normalized = path.replace("\\", "/") if isinstance(path, str) else ""
    safe = (
        0 < len(normalized) <= 512
        and not normalized.startswith("/")
        and ":" not in normalized
        and all(p not in ("", ".", "..") for p in normalized.split("/"))
    )
    safe = safe and all(ord(c) >= 32 and ord(c) != 127 for c in normalized)
    location = storage if isinstance(storage, str) and storage in {"local", "sdcard"} else "unknown"
    result: dict[str, Any] = {
        "storage": location,
        "path": normalized if safe else None,
        "name": normalized.rsplit("/", 1)[-1] if safe else None,
    }
    if not safe:
        result["invalid_path_omitted"] = True
    if type(size) is int and 0 <= size <= MAX_FILE_BYTES:
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
    """Build a content-addressed record without disclosing the absolute host path."""
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
            "relative_storage_name_included": True,
        },
    }


def build_print_manifest(
    event: str, payload: dict[str, Any] | None, *, captured_at: str | None = None
) -> dict[str, Any]:
    """Normalize numeric lifecycle fields; arbitrary free-text reasons are omitted."""
    if event not in _EVENTS:
        raise ValueError("Unsupported print lifecycle event")
    source = payload if isinstance(payload, dict) else {}
    print_data: dict[str, Any] = {"state": event}
    elapsed = _number(source.get("time"))
    progress = _number(source.get("progress"), 100)
    if elapsed is not None:
        print_data["elapsed_seconds"] = elapsed
    reason = source.get("reason")
    if isinstance(reason, str) and reason:
        print_data["reason"] = reason if reason in _REASONS else "unclassified"
    if progress is not None:
        print_data["progress_percent"] = progress
    return {
        "schema": SCHEMA,
        "captured_at": captured_at or utc_now(),
        "source": {"kind": "octoprint_event", "event": event},
        "file": _file_identity(
            source.get("origin", "unknown"),
            source.get("path") or source.get("name") or "unknown",
            size=source.get("size"),
        ),
        "print": print_data,
        "privacy": {
            "gcode_included": False,
            "absolute_host_path_included": False,
            "user_identity_included": False,
            "raw_error_text_included": False,
            "relative_storage_name_included": True,
        },
    }


def store_manifest(directory: str | os.PathLike[str], prefix: str, payload: dict[str, Any]) -> Path:
    """Exclusively write a strict JSON record, rejecting NaN and existing targets."""
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    if len(encoded) > 64 * 1024:
        raise ValueError("Evidence record is unexpectedly large")
    target_dir = Path(directory)
    if target_dir.is_symlink():
        raise ValueError("Evidence directory must not be a symlink")
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_prefix = _SAFE_PREFIX.sub("-", prefix.lower()).strip("-")[:80] or "evidence"
    identity = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    target = target_dir / f"{safe_prefix}-{identity}.json"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return target
