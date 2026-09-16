"""Explainable offline profile proposals. It never sends parameters to Klipper."""

from __future__ import annotations

from typing import Any

from .domain import ParameterBounds, ProfileCandidate
from .quality import aggregate_findings, missing_metrics
from .domain import Finding


BASELINE = {
    "hotend_temp_c": 235.0,
    "volumetric_flow_mm3_s": 12.0,
    "outer_speed_mm_s": 105.0,
    "inner_speed_mm_s": 135.0,
    "accel_mm_s2": 2500.0,
    "pressure_advance": 0.025,
    "fan_percent": 100.0,
}


def _clip(settings: dict[str, float], bounds: ParameterBounds) -> dict[str, float]:
    bounds.validate(settings)
    return settings


def propose_profiles(
    findings: list[Finding], bounds: ParameterBounds | None = None
) -> dict[str, Any]:
    """Create conservative, explainable candidates from labels; not a trained model."""
    missing = missing_metrics(findings)
    if missing:
        raise ValueError(
            "Profile proposals require a complete review; missing: " + ", ".join(missing)
        )
    limits = bounds or ParameterBounds()
    score = aggregate_findings(findings)
    rationale: list[str] = []
    detail = dict(BASELINE)
    balanced = dict(BASELINE)
    fast = dict(BASELINE)

    if score["corner_blobs"] >= 0.35 or score["stringing"] >= 0.4:
        detail["pressure_advance"] = min(0.05, limits.pressure_advance[1])
        detail["outer_speed_mm_s"] -= 15
        detail["accel_mm_s2"] -= 500
        detail["hotend_temp_c"] -= 5
        rationale.append(
            "Pressure or oozing evidence suggests calibrating pressure advance and reducing perimeter energy."
        )
    if score["under_extrusion"] >= 0.35:
        detail["volumetric_flow_mm3_s"] -= 2
        balanced["volumetric_flow_mm3_s"] -= 1
        fast["volumetric_flow_mm3_s"] -= 1
        detail["hotend_temp_c"] += 5
        rationale.append(
            "Under-extrusion suggests reducing volumetric flow before increasing speed."
        )
    if score["thermal_damage"] >= 0.35 or score["stringing"] >= 0.55:
        detail["hotend_temp_c"] -= 5
        detail["fan_percent"] = 100
        rationale.append(
            "Thermal evidence suggests lowering temperature and checking part cooling."
        )
    if score["ringing"] >= 0.35:
        detail["accel_mm_s2"] -= 700
        fast["accel_mm_s2"] -= 500
        rationale.append(
            "Ringing calls for an acceleration limit; a suitable accelerometer can support input-shaper calibration later."
        )
    if score["warping"] >= 0.35:
        detail["fan_percent"] = 70
        balanced["fan_percent"] = 80
        rationale.append(
            "Warping requires checking the first layer and adhesion before increasing speed."
        )

    fast["outer_speed_mm_s"] += 15
    fast["inner_speed_mm_s"] += 25
    fast["accel_mm_s2"] += 500
    balanced["outer_speed_mm_s"] += 5
    balanced["inner_speed_mm_s"] += 10

    candidates = [
        ProfileCandidate(
            "detail", "Surface finish priority", _clip(detail, limits), rationale, 0.4
        ),
        ProfileCandidate(
            "balanced", "Compromiso tiempo/calidad", _clip(balanced, limits), rationale, 0.35
        ),
        ProfileCandidate("fast", "Speed validated in stages", _clip(fast, limits), rationale, 0.25),
    ]
    return {
        "kind": "offline_recommendation",
        "automatic_control": False,
        "quality_observations": score,
        "candidates": [candidate.to_dict() for candidate in candidates],
        "next_experiment": "Print one Atlas specimen and compare photographs and telemetry before adopting a profile.",
    }
