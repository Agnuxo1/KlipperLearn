"""Extract audit metadata from a G-code file without modifying it."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

_NUMBER = r"[-+]?\d*\.?\d+"


def _latest_value(text: str, command: str, parameter: str) -> float | None:
    pattern = re.compile(
        rf"^(?:{command})\b.*?\b{parameter}\s*=?\s*({_NUMBER})\b",
        re.MULTILINE | re.IGNORECASE,
    )
    values = pattern.findall(text)
    return float(values[-1]) if values else None


def extract_gcode_metadata(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    text = target.read_text(encoding="utf-8", errors="replace")
    matches = {
        "hotend_temp_c": _latest_value(text, "M104|M109", "S"),
        "bed_temp_c": _latest_value(text, "M140|M190", "S"),
        "max_volumetric_speed_mm3_s": _latest_value(
            text, "SET_VOLUMETRIC_FLOW_LIMIT", "MAX_VOL_FLOW"
        ),
        "outer_speed_mm_s": _latest_value(text, "SET_VELOCITY_LIMIT", "VELOCITY"),
        "accel_mm_s2": _latest_value(text, "SET_VELOCITY_LIMIT", "ACCEL"),
        "pressure_advance": _latest_value(text, "SET_PRESSURE_ADVANCE", "ADVANCE"),
    }
    return {
        "path": str(target),
        "line_count": text.count("\n") + 1,
        "metadata": {key: value for key, value in matches.items() if value is not None},
        "contains_m106": bool(re.search(r"^M106\b", text, re.MULTILINE | re.IGNORECASE)),
        "contains_m107": bool(re.search(r"^M107\b", text, re.MULTILINE | re.IGNORECASE)),
    }
