"""Offline four-zone first-layer experiment generator.

The generator deliberately emits files only.  Homing is an external runner
responsibility: every generated job starts from an already homed controller,
keeps external travel at Z=5 mm, keeps in-quadrant travel at the active layer,
and parks before restoring the extrusion factor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from numbers import Real
from pathlib import Path
from typing import Iterable, Sequence

from .calibration_chart import build_chart


_CHART_SIZE_MM = 80.0
_MIN_MARGIN_MM = 10.0
_MIN_CORRIDOR_MM = 20.0
_REFERENCE_X_CORRIDOR_MM = 80.0
_REFERENCE_Y_CORRIDOR_MM = 35.0
_PATCH_SIZE_MM = 16.0
_PATCH_X_MM = 48.0
_PATCH_Y_MM = 48.0
_PATCH_RADIUS_MM = 2.0
_PATCH_LAYER_HEIGHT_MM = 0.2
_PATCH_LAYERS = 3
_BED_TEMPERATURE_C = 60.0
_PRINT_SPEED_MM_S = 20.0
_TRAVEL_SPEED_MM_S = 60.0
_Z_SAFE_MM = 5.0
_Z_FEED_MM_MIN = 300.0
_MAX_Z_VELOCITY_MM_S = 7.0
_PARK_FEED_MM_MIN = 1800.0
_BED_WIDTH_MM = 270.0
_BED_DEPTH_MM = 215.0
_PARK_X_MM = 260.0
_PARK_Y_MM = 205.0
_NOZZLE_MM = 0.4
_MATERIAL = {
    "type": "PLA",
    "color": "white",
    "name": "White PLA",
}

_GCODE_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_GCODE_WORD = re.compile(rf"^(?P<letter>[A-Za-z])(?P<value>{_GCODE_NUMBER})$")


def _fmt(value: float) -> str:
    if abs(value) < 0.0000005:
        value = 0.0
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _round(value: float) -> float:
    return round(float(value), 6)


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number, not bool or text")
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _two_finite(values: Iterable[object], name: str) -> tuple[float, float]:
    if isinstance(values, (str, bytes, dict)):
        raise ValueError(f"{name} must contain exactly two finite numbers")
    try:
        items = list(values)
    except TypeError as exc:
        raise ValueError(f"{name} must contain exactly two finite numbers") from exc
    if len(items) != 2:
        raise ValueError(f"{name} must contain exactly two finite numbers")
    return (_finite(items[0], f"{name}[0]"), _finite(items[1], f"{name}[1]"))


def _validate_conditions(
    temperatures: Iterable[object], flows: Iterable[object]
) -> tuple[tuple[float, float], tuple[float, float]]:
    temps = _two_finite(temperatures, "temperatures")
    factors = _two_finite(flows, "flows")
    if any(not 150.0 <= value <= 500.0 for value in temps):
        raise ValueError("temperatures must be between 150 and 500 C")
    if any(not 0.1 <= value <= 2.0 for value in factors):
        raise ValueError("flows must be between 0.1 and 2.0")
    return temps, factors


def _axis_layout(length: float, reference_corridor: float, axis: str) -> tuple[float, float, float]:
    available_corridor = length - 2.0 * _MIN_MARGIN_MM - 2.0 * _CHART_SIZE_MM
    if available_corridor < _MIN_CORRIDOR_MM - 1e-9:
        raise ValueError(
            f"bed {axis} is too small for two 80 mm quadrants, 10 mm margins, and a 20 mm corridor"
        )
    corridor = min(reference_corridor, available_corridor)
    margin = (length - 2.0 * _CHART_SIZE_MM - corridor) / 2.0
    if margin < _MIN_MARGIN_MM - 1e-9 or corridor < _MIN_CORRIDOR_MM - 1e-9:
        raise ValueError(f"bed {axis} leaves insufficient margin or center corridor")
    return _round(margin), _round(margin + _CHART_SIZE_MM + corridor), _round(corridor)


def _rounded_rectangle_points(
    x0: float, y0: float, size: float, radius: float, samples_per_corner: int = 8
) -> list[list[float]]:
    """Return a non-repeating rounded rectangle centre-line polyline."""

    x1 = x0 + size
    y1 = y0 + size
    radius = min(radius, size / 2.0)
    points: list[tuple[float, float]] = [(x0 + radius, y0), (x1 - radius, y0)]

    corners = (
        (x1 - radius, y0 + radius, -90.0, 0.0),
        (x1 - radius, y1 - radius, 0.0, 90.0),
        (x0 + radius, y1 - radius, 90.0, 180.0),
        (x0 + radius, y0 + radius, 180.0, 270.0),
    )
    for corner_index, (cx, cy, start, end) in enumerate(corners):
        if corner_index == 1:
            points.append((x1, y1 - radius))
        elif corner_index == 2:
            points.append((x0 + radius, y1))
        elif corner_index == 3:
            points.append((x0, y0 + radius))
        for sample in range(1, samples_per_corner + 1):
            if corner_index == len(corners) - 1 and sample == samples_per_corner:
                # The closed-path flag supplies this final segment.
                continue
            angle = math.radians(start + (end - start) * sample / samples_per_corner)
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

    return [[_round(x), _round(y)] for x, y in points]


def _rounded_span(
    y: float, x0: float, y0: float, size: float, radius: float
) -> tuple[float, float]:
    """Horizontal centre-line span inside a rounded rectangle at ``y``."""

    x1 = x0 + size
    y1 = y0 + size
    if y < y0 + radius:
        dy = y - (y0 + radius)
        dx = math.sqrt(max(0.0, radius * radius - dy * dy))
        return x0 + radius - dx, x1 - radius + dx
    if y > y1 - radius:
        dy = y - (y1 - radius)
        dx = math.sqrt(max(0.0, radius * radius - dy * dy))
        return x0 + radius - dx, x1 - radius + dx
    return x0, x1


def _build_patch_paths(
    origin_x: float, origin_y: float, line_width: float
) -> tuple[list[dict], dict]:
    """Build the rounded perimeter and clipped, equally spaced solid infill."""

    local_x0 = _PATCH_X_MM
    local_y0 = _PATCH_Y_MM
    perimeter_points = _rounded_rectangle_points(
        origin_x + local_x0,
        origin_y + local_y0,
        _PATCH_SIZE_MM,
        _PATCH_RADIUS_MM,
    )
    paths: list[dict] = [
        {
            "id": "solid_patch_perimeter",
            "role": "solid_patch_perimeter",
            "layer_role": "solid_test_patch",
            "layers": list(range(1, _PATCH_LAYERS + 1)),
            "closed": True,
            "points_mm": perimeter_points,
        }
    ]

    spacing = _round(line_width)
    if spacing <= 0.0:
        raise ValueError("line_width_mm must be positive for patch bead spacing")
    y = local_y0 + spacing / 2.0
    infill_index = 1
    while y <= local_y0 + _PATCH_SIZE_MM - spacing / 2.0 + 1e-9:
        span_x0, span_x1 = _rounded_span(y, local_x0, local_y0, _PATCH_SIZE_MM, _PATCH_RADIUS_MM)
        points = [
            [_round(origin_x + span_x0), _round(origin_y + y)],
            [_round(origin_x + span_x1), _round(origin_y + y)],
        ]
        if infill_index % 2 == 0:
            points.reverse()
        paths.append(
            {
                "id": f"solid_patch_infill_{infill_index:02d}",
                "role": "solid_patch_infill",
                "layer_role": "solid_test_patch",
                "layers": list(range(1, _PATCH_LAYERS + 1)),
                "closed": False,
                "points_mm": points,
            }
        )
        infill_index += 1
        y += spacing

    patch = {
        "placement": "grid_sector_replacement",
        "footprint_bounds_local_mm": [
            _PATCH_X_MM,
            _PATCH_Y_MM,
            _PATCH_SIZE_MM,
            _PATCH_SIZE_MM,
        ],
        "size_mm": [_PATCH_SIZE_MM, _PATCH_SIZE_MM],
        "corner_radius_mm": _PATCH_RADIUS_MM,
        "layer_height_mm": _PATCH_LAYER_HEIGHT_MM,
        "layers": _PATCH_LAYERS,
        "bead_spacing_mm": spacing,
        "solid": True,
        "replaces_role": "grid",
        "path_ids": [path["id"] for path in paths],
    }
    return paths, patch


def _translate_chart_paths(chart_manifest: dict, origin_x: float, origin_y: float) -> list[dict]:
    paths: list[dict] = []
    for source in chart_manifest["paths"]:
        if source["role"] == "grid":
            continue
        path = {
            "id": source["id"],
            "role": source["role"],
            "layer_role": "chart",
            "layers": [1],
            "closed": False,
            "points_mm": [list(point) for point in source["points_mm"]],
        }
        # build_chart already returned absolute coordinates for this zone.
        if not path["points_mm"]:
            raise ValueError(f"chart path {path['id']} has no points")
        paths.append(path)
    return paths


def _with_patch(paths: list[dict], patch_paths: list[dict]) -> list[dict]:
    return paths + patch_paths


def _local_geometry(
    paths: list[dict],
    fiducials: list[list[float]],
    origin_x: float,
    origin_y: float,
    line_width: float,
    chart_layer_height: float,
    patch: dict,
) -> dict:
    local_paths = []
    for path in paths:
        local_paths.append(
            {
                "id": path["id"],
                "role": path["role"],
                "layer_role": path["layer_role"],
                "layers": list(path["layers"]),
                "closed": bool(path["closed"]),
                "points_mm": [
                    [_round(x - origin_x), _round(y - origin_y)] for x, y in path["points_mm"]
                ],
            }
        )
    return {
        "size_mm": _CHART_SIZE_MM,
        "line_width_mm": _round(line_width),
        "chart_layer_height_mm": _round(chart_layer_height),
        "paths": local_paths,
        "fiducials_local_mm": [[_round(x - origin_x), _round(y - origin_y)] for x, y in fiducials],
        "layer_roles": [
            {
                "id": "chart",
                "layers": [1],
                "layer_height_mm": _round(chart_layer_height),
                "path_ids": [path["id"] for path in paths if path["layer_role"] == "chart"],
            },
            {
                "id": "solid_test_patch",
                "layers": list(range(1, _PATCH_LAYERS + 1)),
                "layer_height_mm": _PATCH_LAYER_HEIGHT_MM,
                "path_ids": list(patch["path_ids"]),
                "bead_spacing_mm": patch["bead_spacing_mm"],
            },
        ],
        "patch": dict(patch),
    }


def _geometry_hash(geometry: dict) -> str:
    payload = json.dumps(geometry, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _segments(path: dict) -> Iterable[tuple[tuple[float, float], tuple[float, float]]]:
    points = [tuple(point) for point in path["points_mm"]]
    for start, end in zip(points, points[1:]):
        yield start, end
    if path.get("closed"):
        yield points[-1], points[0]


def _iter_gcode_commands(gcode: str) -> Iterable[tuple[str, dict[str, float]]]:
    """Yield executable G-code words, excluding full-line and inline comments."""

    for raw_line in gcode.splitlines():
        code = raw_line.split(";", 1)[0].strip()
        if not code:
            continue
        words = code.split()
        opcode = words[0].upper()
        params: dict[str, float] = {}
        for word in words[1:]:
            match = _GCODE_WORD.fullmatch(word)
            if match is None:
                raise ValueError(f"invalid G-code word: {word}")
            params[match.group("letter").upper()] = float(match.group("value"))
        yield opcode, params


def _validate_gcode_safety(
    gcode: str,
    bed_width: float,
    bed_depth: float,
    in_layer_bounds: tuple[float, float, float, float] | None = None,
) -> None:
    """Reject unsafe motion in the exact commands that will be written to disk."""

    z_position: float | None = None
    x_position: float | None = None
    y_position: float | None = None
    last_non_printing_xy: tuple[float | None, float | None] | None = None
    extrusion_commands = 0
    m221_values: list[float] = []

    for opcode, params in _iter_gcode_commands(gcode):
        if opcode in {"G28", "M84"}:
            raise ValueError(f"unsafe command emitted: {opcode}")
        if any(not math.isfinite(value) for value in params.values()):
            raise ValueError(f"non-finite G-code parameter in {opcode}")

        if opcode == "M221":
            if "S" not in params:
                raise ValueError("M221 must specify an extrusion factor")
            m221_values.append(params["S"])

        if opcode not in {"G0", "G1"}:
            continue

        next_z = params.get("Z", z_position)
        moved_xy = "X" in params or "Y" in params
        if moved_xy:
            next_x = params.get("X", x_position)
            next_y = params.get("Y", y_position)
            for axis, value, limit in (
                ("X", next_x, bed_width),
                ("Y", next_y, bed_depth),
            ):
                if value is not None and not 0.0 <= value <= limit:
                    raise ValueError(f"G-code {axis} coordinate is outside the bed")

            if "E" in params:
                extrusion = params["E"]
                if not extrusion > 0.0:
                    raise ValueError("printing G-code must extrude a positive amount")
                extrusion_commands += 1
            else:
                safe_external_travel = next_z is not None and next_z >= _Z_SAFE_MM - 1e-9
                in_quadrant_travel = (
                    in_layer_bounds is not None
                    and next_z is not None
                    and next_z < _Z_SAFE_MM - 1e-9
                    and next_x is not None
                    and next_y is not None
                    and in_layer_bounds[0] - 1e-9
                    <= next_x
                    <= in_layer_bounds[0] + in_layer_bounds[2] + 1e-9
                    and in_layer_bounds[1] - 1e-9
                    <= next_y
                    <= in_layer_bounds[1] + in_layer_bounds[3] + 1e-9
                )
                if not safe_external_travel and not in_quadrant_travel:
                    raise ValueError(
                        "non-printing XY travel must be at or above Z5 or inside the quadrant"
                    )
                last_non_printing_xy = (next_x, next_y)
            x_position, y_position = next_x, next_y
        elif "E" in params:
            if not params["E"] > 0.0:
                raise ValueError("printing G-code must extrude a positive amount")
            extrusion_commands += 1

        z_position = next_z

    if extrusion_commands == 0:
        raise ValueError("G-code contains no positive extrusion commands")
    if last_non_printing_xy != (_PARK_X_MM, _PARK_Y_MM):
        raise ValueError("G-code must finish its XY travel at X260 Y205")
    if z_position is None or z_position < _Z_SAFE_MM - 1e-9:
        raise ValueError("G-code must finish at or above Z5")
    if not m221_values or not math.isclose(m221_values[-1], 100.0, abs_tol=1e-9, rel_tol=0.0):
        raise ValueError("G-code must restore the extrusion factor to 100%")


def _emit_path(
    lines: list[str],
    path: dict,
    z: float,
    line_width: float,
    layer_height: float,
    filament_area: float,
    travel_feed: float,
    print_feed: float,
    layer_number: int,
    current_z: float,
    initial_entry: bool = False,
) -> float:
    points = path["points_mm"]
    if len(points) < 2:
        raise ValueError(f"path {path['id']} must contain at least two points")
    lines.append(f"; PATH {path['id']} role={path['role']} layer={layer_number}")
    start_x, start_y = points[0]
    if initial_entry:
        # The first move enters the quadrant at the safe height.  Once there,
        # all subsequent XY travels stay at the active printing layer.
        lines.append(f"G0 X{_fmt(start_x)} Y{_fmt(start_y)} F{_fmt(travel_feed)}")
        if not math.isclose(current_z, z, abs_tol=1e-9, rel_tol=0.0):
            lines.append(f"G1 Z{_fmt(z)} F{_fmt(_Z_FEED_MM_MIN)}")
    else:
        if not math.isclose(current_z, z, abs_tol=1e-9, rel_tol=0.0):
            lines.append(f"G1 Z{_fmt(z)} F{_fmt(_Z_FEED_MM_MIN)}")
        lines.append(f"G0 X{_fmt(start_x)} Y{_fmt(start_y)} F{_fmt(travel_feed)}")
    for (start_x, start_y), (end_x, end_y) in _segments(path):
        length = math.hypot(end_x - start_x, end_y - start_y)
        extrusion = length * line_width * layer_height / filament_area
        if not math.isfinite(extrusion) or not extrusion > 0.0:
            raise ValueError(f"path {path['id']} contains a non-positive extrusion segment")
        lines.append(f"G1 X{_fmt(end_x)} Y{_fmt(end_y)} E{_fmt(extrusion)} F{_fmt(print_feed)}")
    return z


def _build_gcode(
    geometry: dict,
    temperature: float,
    extrusion_factor: float,
    bed_width: float,
    bed_depth: float,
    filament_diameter: float,
) -> str:
    line_width = geometry["line_width_mm"]
    chart_layer_height = geometry["chart_layer_height_mm"]
    filament_area = math.pi * (filament_diameter / 2.0) ** 2
    print_feed = _PRINT_SPEED_MM_S * 60.0
    travel_feed = _TRAVEL_SPEED_MM_S * 60.0
    path_by_id = {path["id"]: path for path in geometry["paths"]}
    chart_paths = [path for path in geometry["paths"] if path["layer_role"] == "chart"]
    patch_paths = [path_by_id[path_id] for path_id in geometry["patch"]["path_ids"]]

    lines = [
        "; KlipperLearn offline 2x2 quadrant experiment",
        "; EXPERIMENTAL: this is not a universal calibration or an automatic verdict.",
        "; REQUIREMENT: XYZ must be homed externally once before this file; no homing command is emitted.",
        "; External XY travel is at Z5; in-quadrant travel stays at the active layer.",
        "G90",
        "M83",
        "M220 S100",
        f"M221 S{_fmt(extrusion_factor * 100.0)}",
        f"M140 S{_fmt(_BED_TEMPERATURE_C)}",
        f"M190 S{_fmt(_BED_TEMPERATURE_C)}",
        f"M104 S{_fmt(temperature)}",
        f"M109 S{_fmt(temperature)}",
        f"G1 Z{_fmt(_Z_SAFE_MM)} F{_fmt(_Z_FEED_MM_MIN)}",
    ]

    current_z = _Z_SAFE_MM
    initial_entry = True
    for path in chart_paths:
        current_z = _emit_path(
            lines,
            path,
            chart_layer_height,
            line_width,
            chart_layer_height,
            filament_area,
            travel_feed,
            print_feed,
            1,
            current_z,
            initial_entry,
        )
        initial_entry = False

    for layer_number in range(1, _PATCH_LAYERS + 1):
        z = layer_number * _PATCH_LAYER_HEIGHT_MM
        for path in patch_paths:
            current_z = _emit_path(
                lines,
                path,
                z,
                line_width,
                _PATCH_LAYER_HEIGHT_MM,
                filament_area,
                travel_feed,
                print_feed,
                layer_number,
                current_z,
                initial_entry,
            )
            initial_entry = False

    lines.extend(
        (
            "M400",
            f"G1 Z{_fmt(_Z_SAFE_MM)} F{_fmt(_Z_FEED_MM_MIN)}",
            f"G1 X{_fmt(_PARK_X_MM)} Y{_fmt(_PARK_Y_MM)} F{_fmt(_PARK_FEED_MM_MIN)}",
            "M400",
            "G4 P1500",
            "M221 S100",
            "M104 S0",
            "M140 S0",
            "",
        )
    )
    gcode = "\n".join(lines)
    _validate_gcode_safety(
        gcode,
        bed_width,
        bed_depth,
        in_layer_bounds=tuple(geometry["bounds_mm"]),
    )
    return gcode


def _zone_geometry(
    chart: dict,
    origin_x: float,
    origin_y: float,
    line_width: float,
    chart_layer_height: float,
) -> dict:
    chart_manifest = chart["manifest"]
    chart_paths = _translate_chart_paths(chart_manifest, origin_x, origin_y)
    patch_paths, patch = _build_patch_paths(origin_x, origin_y, line_width)
    paths = _with_patch(chart_paths, patch_paths)
    local = _local_geometry(
        paths,
        chart_manifest["fiducials_mm"],
        origin_x,
        origin_y,
        line_width,
        chart_layer_height,
        patch,
    )
    absolute = {
        "bounds_mm": [
            _round(origin_x),
            _round(origin_y),
            _CHART_SIZE_MM,
            _CHART_SIZE_MM,
        ],
        "paths": paths,
        "fiducials_mm": [list(point) for point in chart_manifest["fiducials_mm"]],
        "layer_roles": local["layer_roles"],
        "patch": {
            **patch,
            "footprint_bounds_mm": [
                _round(origin_x + _PATCH_X_MM),
                _round(origin_y + _PATCH_Y_MM),
                _PATCH_SIZE_MM,
                _PATCH_SIZE_MM,
            ],
        },
        "placement": "grid_sector_replacement",
    }
    return {"absolute": absolute, "local": local}


def build_batch(
    base_spec: dict,
    temperatures: Iterable[object] = (200, 205),
    flows: Iterable[object] = (0.97, 1.0),
) -> dict:
    """Return a manifest and four offline G-code files for one 2x2 experiment."""

    if not isinstance(base_spec, dict):
        raise ValueError("base_spec must be a dictionary")
    temps, factors = _validate_conditions(temperatures, flows)

    # Validate the supplied chart specification itself, including finite values
    # that this batch fixes (print speed, bed temperature, and origin) before
    # applying the batch's deliberately fixed runtime values.
    build_chart(base_spec)
    bed_width = _finite(base_spec["bed_width_mm"], "bed_width_mm")
    bed_depth = _finite(base_spec["bed_depth_mm"], "bed_depth_mm")
    if not math.isclose(bed_width, _BED_WIDTH_MM, abs_tol=1e-9, rel_tol=0.0) or not math.isclose(
        bed_depth, _BED_DEPTH_MM, abs_tol=1e-9, rel_tol=0.0
    ):
        raise ValueError("quadrant batch requires a 270 x 215 mm bed")
    nozzle = _finite(base_spec["nozzle_mm"], "nozzle_mm")
    if not math.isclose(nozzle, _NOZZLE_MM, abs_tol=1e-9, rel_tol=0.0):
        raise ValueError("quadrant batch requires a 0.4 mm nozzle")
    origin_x_left, origin_x_right, x_corridor = _axis_layout(
        bed_width, _REFERENCE_X_CORRIDOR_MM, "width"
    )
    origin_y_bottom, origin_y_top, y_corridor = _axis_layout(
        bed_depth, _REFERENCE_Y_CORRIDOR_MM, "depth"
    )

    # build_chart remains the source of the chart paths.  The original chart's
    # origin is intentionally ignored after validation: the batch owns layout.
    common_spec = dict(base_spec)
    common_spec.update(
        {
            "size_mm": _CHART_SIZE_MM,
            "print_speed_mm_s": _PRINT_SPEED_MM_S,
            "travel_speed_mm_s": _TRAVEL_SPEED_MM_S,
            "bed_temp_c": _BED_TEMPERATURE_C,
            "origin_x_mm": origin_x_left,
            "origin_y_mm": origin_y_bottom,
        }
    )
    first_chart = build_chart({**common_spec, "hotend_temp_c": temps[0]})
    line_width = _finite(first_chart["manifest"]["line_width_mm"], "line_width_mm")
    chart_layer_height = _finite(first_chart["manifest"]["layer_height_mm"], "layer_height_mm")
    filament_diameter = _finite(base_spec["filament_diameter_mm"], "filament_diameter_mm")
    if _PATCH_LAYER_HEIGHT_MM > nozzle + 1e-12:
        # The patch's fixed 0.2 mm layers must obey the same nozzle constraint
        # as the chart, even when the chart itself is thinner.
        raise ValueError("0.2 mm patch layers exceed nozzle_mm")
    volumetric_rate = (
        line_width * max(chart_layer_height, _PATCH_LAYER_HEIGHT_MM) * _PRINT_SPEED_MM_S
    )
    max_volumetric = _finite(base_spec["max_volumetric_mm3_s"], "max_volumetric_mm3_s")
    if volumetric_rate > max_volumetric + 1e-12:
        raise ValueError("batch print speed exceeds max_volumetric_mm3_s")

    zone_specs = (
        ("bl", origin_x_left, origin_y_bottom, temps[0], factors[0], "bottom", "left"),
        ("br", origin_x_right, origin_y_bottom, temps[0], factors[1], "bottom", "right"),
        ("tl", origin_x_left, origin_y_top, temps[1], factors[0], "top", "left"),
        ("tr", origin_x_right, origin_y_top, temps[1], factors[1], "top", "right"),
    )

    zone_payloads: list[tuple[dict, str]] = []
    common_geometry: dict | None = None
    geometry_hash: str | None = None
    for zone_id, origin_x, origin_y, temperature, factor, row, column in zone_specs:
        spec = dict(common_spec)
        spec.update(
            {
                "origin_x_mm": origin_x,
                "origin_y_mm": origin_y,
                "hotend_temp_c": temperature,
            }
        )
        chart = first_chart if zone_id == "bl" else build_chart(spec)
        geometry_pair = _zone_geometry(chart, origin_x, origin_y, line_width, chart_layer_height)
        absolute_geometry = geometry_pair["absolute"]
        local_geometry = geometry_pair["local"]
        current_hash = _geometry_hash(local_geometry)
        if geometry_hash is None:
            geometry_hash = current_hash
            common_geometry = local_geometry
        elif current_hash != geometry_hash:
            raise ValueError("quadrant geometry is not translation-invariant")

        gcode = _build_gcode(
            local_geometry
            | {
                "bounds_mm": absolute_geometry["bounds_mm"],
                "paths": absolute_geometry["paths"],
                "patch": absolute_geometry["patch"],
            },
            temperature,
            factor,
            bed_width,
            bed_depth,
            filament_diameter,
        )
        filename = f"quadrant_{zone_id}.gcode"
        zone_geometry = {
            **absolute_geometry,
            "origin_mm": [_round(origin_x), _round(origin_y)],
            "local": local_geometry,
        }
        zone = {
            "id": zone_id,
            "gcode_filename": filename,
            "temperature_c": _round(temperature),
            "extrusion_factor": _round(factor),
            "geometry_sha256": current_hash,
            "gcode_sha256": hashlib.sha256(gcode.encode("utf-8")).hexdigest(),
            "bed_position": {"row": row, "column": column},
            "geometry": zone_geometry,
            # These aliases keep the manifest convenient for existing runners
            # that read bounds/paths directly from each zone.
            "bounds_mm": zone_geometry["bounds_mm"],
            "paths": zone_geometry["paths"],
            "fiducials_mm": zone_geometry["fiducials_mm"],
            "layer_roles": zone_geometry["layer_roles"],
            "patch": zone_geometry["patch"],
        }
        zone_payloads.append((zone, gcode))

    if geometry_hash is None or common_geometry is None:
        raise ValueError("quadrant batch did not produce any geometry")
    files = {zone["gcode_filename"]: gcode for zone, gcode in zone_payloads}
    file_hashes = {
        filename: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for filename, text in files.items()
    }
    zones = [zone for zone, _ in zone_payloads]
    manifest = {
        "schema_version": 1,
        "kind": "quadrant_batch",
        "material": dict(_MATERIAL),
        "nozzle_mm": _NOZZLE_MM,
        "variant": "White PLA / 0.4 mm nozzle",
        "zones": zones,
        "geometry_sha256": geometry_hash,
        "gcode_sha256": file_hashes,
        "bed_mm": [_round(bed_width), _round(bed_depth)],
        "layout": {
            "chart_size_mm": _CHART_SIZE_MM,
            "x_corridor_mm": x_corridor,
            "y_corridor_mm": y_corridor,
            "minimum_margin_mm": _MIN_MARGIN_MM,
            "origins_by_zone": {zone["id"]: zone["geometry"]["origin_mm"] for zone in zones},
            "center_corridor_x_mm": [
                _round(origin_x_left + _CHART_SIZE_MM),
                _round(origin_x_right),
            ],
        },
        "experimental_design": {
            "shape": "2x2",
            "temperatures_c": [_round(temps[0]), _round(temps[1])],
            "extrusion_factors": [_round(factors[0]), _round(factors[1])],
            "bed_position_confound": True,
            "universal_calibration": False,
            "note": "One experimental 2x2 temp/flow batch; bed position is a confound and this is not universal calibration.",
        },
        "runtime": {
            "requires_external_xyz_homing_once": True,
            "home_command_emitted": False,
            "z_safe_mm": _Z_SAFE_MM,
            "max_z_velocity_mm_s": _MAX_Z_VELOCITY_MM_S,
            "print_speed_mm_s": _PRINT_SPEED_MM_S,
            "travel_speed_mm_s": _TRAVEL_SPEED_MM_S,
            "bed_temperature_c": _BED_TEMPERATURE_C,
            "nozzle_mm": _NOZZLE_MM,
            "material": dict(_MATERIAL),
            "park_mm": [_PARK_X_MM, _PARK_Y_MM],
            "patch_layer_height_mm": _PATCH_LAYER_HEIGHT_MM,
            "patch_layers": _PATCH_LAYERS,
            "post_print": "parked for two external exposure captures; no camera/network/print action here",
        },
        "geometry": common_geometry,
    }
    return {"manifest": manifest, "files": files}


def _write_new_output(batch: dict, output_directory: Path) -> dict[str, str]:
    if output_directory.exists():
        if output_directory.is_symlink() or not output_directory.is_dir():
            raise ValueError("--output must be a directory that is safe to populate")
        if any(output_directory.iterdir()):
            raise ValueError(
                "--output must be empty; refusing to overwrite an existing destination"
            )
    else:
        output_directory.mkdir(parents=True, exist_ok=False)

    payloads = {"manifest.json": json.dumps(batch["manifest"], indent=2, ensure_ascii=False) + "\n"}
    payloads.update(batch["files"])
    hashes: dict[str, str] = {}
    for filename, payload in payloads.items():
        target = output_directory / filename
        target.write_text(payload, encoding="utf-8", newline="\n")
        hashes[filename] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return hashes


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build an offline Klipper quadrant experiment")
    parser.add_argument("--input", required=True, help="JSON base chart specification")
    parser.add_argument("--output", required=True, help="new or empty output directory")
    arguments = parser.parse_args(argv)

    try:
        base_spec = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
        batch = build_batch(base_spec)
        hashes = _write_new_output(batch, Path(arguments.output))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps({"output": str(Path(arguments.output)), "sha256": hashes}, indent=2))


if __name__ == "__main__":
    main()
