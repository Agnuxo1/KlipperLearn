"""Stable, serialisable domain objects used by collection, review and optimisation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


DEFECT_KEYS = (
    "visible_lamination",
    "corner_blobs",
    "under_extrusion",
    "over_extrusion",
    "stringing",
    "warping",
    "bridging",
    "ringing",
    "thermal_damage",
)


@dataclass(frozen=True)
class Finding:
    """A normalised quality observation. Severity is 0.0 (absent) to 1.0 (severe)."""

    metric: str
    severity: float
    confidence: float
    source: str
    notes: str = ""

    def __post_init__(self) -> None:
        if self.metric not in DEFECT_KEYS:
            raise ValueError(f"Unknown quality metric: {self.metric}")
        if not 0.0 <= self.severity <= 1.0:
            raise ValueError("severity must be between 0 and 1")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParameterBounds:
    """Hard safety bounds used for offline proposals, never as printer commands."""

    hotend_temp_c: tuple[float, float] = (190.0, 250.0)
    volumetric_flow_mm3_s: tuple[float, float] = (2.0, 14.0)
    outer_speed_mm_s: tuple[float, float] = (20.0, 180.0)
    inner_speed_mm_s: tuple[float, float] = (20.0, 220.0)
    accel_mm_s2: tuple[float, float] = (300.0, 6000.0)
    pressure_advance: tuple[float, float] = (0.0, 0.20)
    fan_percent: tuple[float, float] = (0.0, 100.0)

    def validate(self, settings: dict[str, float]) -> None:
        ranges = {
            "hotend_temp_c": self.hotend_temp_c,
            "volumetric_flow_mm3_s": self.volumetric_flow_mm3_s,
            "outer_speed_mm_s": self.outer_speed_mm_s,
            "inner_speed_mm_s": self.inner_speed_mm_s,
            "accel_mm_s2": self.accel_mm_s2,
            "pressure_advance": self.pressure_advance,
            "fan_percent": self.fan_percent,
        }
        for name, value in settings.items():
            if name not in ranges:
                raise ValueError(f"Parameter is not allowed: {name}")
            low, high = ranges[name]
            if not low <= value <= high:
                raise ValueError(f"{name}={value} is outside safe proposal bounds [{low}, {high}]")


@dataclass(frozen=True)
class ProfileCandidate:
    name: str
    objective: str
    settings: dict[str, float]
    rationale: list[str] = field(default_factory=list)
    confidence: float = 0.0
    requires_human_review: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
