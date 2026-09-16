from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
from pathlib import Path
import tomllib
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    moonraker_url: str
    snapshot_url: str | None
    mode: str
    sample_interval_seconds: float
    save_frames_while_printing: bool
    bed_width_mm: float
    bed_depth_mm: float
    margin_mm: float
    cell_width_mm: float
    cell_depth_mm: float
    machine: dict[str, Any] = field(default_factory=dict)
    material: dict[str, Any] = field(default_factory=dict)
    camera: dict[str, Any] = field(default_factory=dict)
    config_sha256: str = ""


def _validate_http_url(name: str, value: str) -> str:
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (ValueError, TypeError):
        raise ValueError(f"{name} has an invalid host or port") from None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{name} must not embed credentials")
    if parsed.fragment or (port is not None and not 1 <= port <= 65535):
        raise ValueError(f"{name} has an invalid fragment or port")
    if name == "moonraker.url" and (parsed.query or parsed.path not in {"", "/"}):
        raise ValueError("moonraker.url must identify the server, without a path or query")
    return value.rstrip("/")


def _finite_setting(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        raise ValueError(f"{name} must be a finite number") from None
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def load_settings(path: str | Path) -> Settings:
    config_bytes = Path(path).read_bytes()
    raw = tomllib.loads(config_bytes.decode("utf-8"))
    if "moonraker" not in raw:
        raise ValueError("A moonraker configuration section is required")
    for section in ("moonraker", "camera", "observer", "atlas", "machine", "material"):
        if not isinstance(raw.get(section, {}), dict):
            raise ValueError(f"{section} must be a configuration table")
    moonraker = raw["moonraker"]
    camera = raw.get("camera", {})
    observer = raw.get("observer", {})
    atlas = raw.get("atlas", {})
    mode = observer.get("mode", "observe")
    if mode != "observe":
        raise ValueError("This MVP only supports the safe 'observe' mode.")
    snapshot_url = camera.get("snapshot_url")
    save_frames = observer.get("save_frames_while_printing", True)
    if type(save_frames) is not bool:
        raise ValueError("save_frames_while_printing must be a boolean")
    settings = Settings(
        moonraker_url=_validate_http_url("moonraker.url", moonraker["url"]),
        snapshot_url=_validate_http_url("camera.snapshot_url", snapshot_url)
        if snapshot_url
        else None,
        mode=mode,
        sample_interval_seconds=_finite_setting(
            "sample_interval_seconds", observer.get("sample_interval_seconds", 5)
        ),
        save_frames_while_printing=save_frames,
        bed_width_mm=_finite_setting("bed_width_mm", atlas.get("bed_width_mm", 220)),
        bed_depth_mm=_finite_setting("bed_depth_mm", atlas.get("bed_depth_mm", 140)),
        margin_mm=_finite_setting("margin_mm", atlas.get("margin_mm", 12)),
        cell_width_mm=_finite_setting("cell_width_mm", atlas.get("cell_width_mm", 45)),
        cell_depth_mm=_finite_setting("cell_depth_mm", atlas.get("cell_depth_mm", 45)),
        machine=dict(raw.get("machine", {})),
        material=dict(raw.get("material", {})),
        camera={key: value for key, value in camera.items() if key != "snapshot_url"},
        config_sha256=hashlib.sha256(config_bytes).hexdigest(),
    )
    positive = {
        "sample_interval_seconds": settings.sample_interval_seconds,
        "bed_width_mm": settings.bed_width_mm,
        "bed_depth_mm": settings.bed_depth_mm,
        "cell_width_mm": settings.cell_width_mm,
        "cell_depth_mm": settings.cell_depth_mm,
    }
    for name, value in positive.items():
        if value <= 0:
            raise ValueError(f"{name} must be greater than zero")
    if settings.margin_mm < 0:
        raise ValueError("margin_mm must not be negative")
    if 2 * settings.margin_mm >= min(settings.bed_width_mm, settings.bed_depth_mm):
        raise ValueError("margin_mm leaves no usable bed area")
    return settings
