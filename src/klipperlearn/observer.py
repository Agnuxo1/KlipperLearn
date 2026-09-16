from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import math
from .http_readonly import read_http_bytes

from . import __version__
from .config import Settings
from .moonraker import MoonrakerClient
from .storage import SessionStore

MAX_SNAPSHOT_BYTES = 25 * 1024 * 1024


class Observer:
    """Collect synchronized, read-only Moonraker and camera observations."""

    def __init__(self, settings: Settings, session_root: Path) -> None:
        self.settings = settings
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.session_dir = session_root / timestamp
        self.frames_dir = self.session_dir / "frames"
        self.client = MoonrakerClient(settings.moonraker_url)
        self._last_filename = ""
        self._frame_number = 0

    def run(self, duration_seconds: float) -> Path:
        if isinstance(duration_seconds, bool) or not isinstance(duration_seconds, (int, float)):
            raise ValueError("duration_seconds must be a finite positive number")
        if not math.isfinite(duration_seconds) or duration_seconds <= 0:
            raise ValueError("duration_seconds must be greater than zero")
        self.session_dir.mkdir(parents=True, exist_ok=False)
        self.frames_dir.mkdir()
        manifest = {
            "schema_version": 2,
            "klipperlearn_version": __version__,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": self.settings.mode,
            "moonraker_url": self.settings.moonraker_url,
            "camera_configured": bool(self.settings.snapshot_url),
            "machine": self.settings.machine,
            "material": self.settings.material,
            "camera": self.settings.camera,
            "config_sha256": self.settings.config_sha256,
            "safety": {
                "printer_control": False,
                "moonraker_methods": ["GET"],
                "gcode_commands": False,
            },
        }
        (self.session_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        deadline = time.monotonic() + duration_seconds
        store = SessionStore(self.session_dir / "telemetry.sqlite3")
        with store.open() as database:
            store.event(
                database,
                datetime.now(timezone.utc).isoformat(),
                "observer_started",
                {"read_only": True},
            )
            database.commit()
            while time.monotonic() < deadline:
                self._sample(store, database)
                # Observation sessions may be interrupted with the printer still running.
                # Persist every sample so registered frame hashes are not held until shutdown.
                database.commit()
                time.sleep(self.settings.sample_interval_seconds)
            store.event(
                database,
                datetime.now(timezone.utc).isoformat(),
                "observer_stopped",
                {"read_only": True},
            )
            database.commit()
        return self.session_dir

    def _sample(self, store: SessionStore, database) -> None:
        captured_at = datetime.now(timezone.utc).isoformat()
        try:
            status = self.client.printer_status()
        except Exception as exc:  # telemetry should keep running after a transient network failure
            store.event(database, captured_at, "moonraker_error", {"error": str(exc)})
            return

        print_stats = status.get("print_stats", {})
        state = print_stats.get("state", "unknown")
        filename = print_stats.get("filename", "")
        store.sample(database, captured_at, state, filename, status)
        if filename and filename != self._last_filename:
            self._record_file_metadata(store, database, captured_at, filename)
            self._last_filename = filename
        if state == "printing" and self.settings.save_frames_while_printing:
            self._capture_frame(store, database, captured_at)

    def _record_file_metadata(
        self, store: SessionStore, database, timestamp: str, filename: str
    ) -> None:
        try:
            metadata = self.client.file_metadata(filename)
            store.event(database, timestamp, "gcode_metadata", metadata)
        except Exception as exc:
            store.event(
                database, timestamp, "metadata_error", {"error": str(exc), "filename": filename}
            )

    def _capture_frame(self, store: SessionStore, database, timestamp: str) -> None:
        if not self.settings.snapshot_url:
            return
        try:
            image = read_http_bytes(
                self.settings.snapshot_url, limit=MAX_SNAPSHOT_BYTES, timeout=10
            )
            if len(image) > MAX_SNAPSHOT_BYTES:
                raise ValueError("Camera snapshot exceeds the 25 MiB safety limit")
            if not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9"):
                raise ValueError("Camera snapshot is not a JPEG image")
            self._frame_number += 1
            safe_timestamp = timestamp.replace("+00:00", "Z").replace(":", "")
            name = f"{self._frame_number:06d}_{safe_timestamp}.jpg"
            (self.frames_dir / name).write_bytes(image)
            relative_path = f"frames/{name}"
            store.frame(
                database, timestamp, relative_path, hashlib.sha256(image).hexdigest(), len(image)
            )
            store.event(database, timestamp, "frame", {"path": relative_path})
        except Exception as exc:
            store.event(database, timestamp, "camera_error", {"error": str(exc)})
