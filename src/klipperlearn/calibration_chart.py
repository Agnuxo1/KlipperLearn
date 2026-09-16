"""Build a deterministic, offline, one-layer first-layer geometry chart.

The chart is deliberately a geometry probe rather than a printer-calibration
routine: it contains fiducials, separated line/curve/corner sectors, and an
explicit grid sector.  It does not validate input shaping or pressure advance,
and it is never sent to a printer.  ``build_chart`` validates every required
value, returns a manifest plus SVG and G-code strings, and the module CLI writes
only those three artifacts to an explicitly supplied empty output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
from typing import Iterable, Sequence
from xml.sax.saxutils import escape


_REQUIRED_FIELDS = (
    "bed_width_mm",
    "bed_depth_mm",
    "origin_x_mm",
    "origin_y_mm",
    "size_mm",
    "nozzle_mm",
    "layer_height_mm",
    "line_width_mm",
    "filament_diameter_mm",
    "print_speed_mm_s",
    "travel_speed_mm_s",
    "hotend_temp_c",
    "bed_temp_c",
    "max_hotend_temp_c",
    "max_bed_temp_c",
    "max_velocity_mm_s",
    "max_volumetric_mm3_s",
)

_BED_MARGIN_MM = 5.0
_FIDUCIAL_OFFSET_MM = 5.0
_FIDUCIAL_HALF_SIZE_MM = 1.5
_PRIME_HALF_LENGTH_MM = 2.0
_SECTOR_EDGE_MM = 11.0
_SECTOR_GAP_MM = 6.0


def _fmt(value: float) -> str:
    """Format a numeric motion value without needless trailing zeroes."""

    if abs(value) < 0.0000005:
        value = 0.0
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _finite_number(spec: dict, name: str) -> float:
    if name not in spec:
        raise ValueError(f"Missing required field: {name}")
    value = spec[name]
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{name} must be a finite number, not bool or text")
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def _in_range(values: dict[str, float], name: str, minimum: float, maximum: float) -> None:
    value = values[name]
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g} mm/C/s")


def _validate_spec(spec: dict) -> dict[str, float]:
    if not isinstance(spec, dict):
        raise ValueError("spec must be a dictionary")

    values = {name: _finite_number(spec, name) for name in _REQUIRED_FIELDS}

    # These broad bounds reject unit mistakes and impossible machine settings
    # while leaving ordinary desktop, Cartesian, and larger-format printers
    # usable.  Coupled constraints below carry the more meaningful checks.
    _in_range(values, "bed_width_mm", 20.0, 2000.0)
    _in_range(values, "bed_depth_mm", 20.0, 2000.0)
    _in_range(values, "origin_x_mm", 0.0, 2000.0)
    _in_range(values, "origin_y_mm", 0.0, 2000.0)
    _in_range(values, "size_mm", 80.0, 160.0)
    _in_range(values, "nozzle_mm", 0.1, 2.0)
    _in_range(values, "layer_height_mm", 0.01, 2.0)
    _in_range(values, "line_width_mm", 0.1, 4.0)
    _in_range(values, "filament_diameter_mm", 1.0, 3.0)
    _in_range(values, "print_speed_mm_s", 0.1, 1000.0)
    _in_range(values, "travel_speed_mm_s", 0.1, 1000.0)
    _in_range(values, "hotend_temp_c", 150.0, 500.0)
    _in_range(values, "bed_temp_c", 0.0, 200.0)
    _in_range(values, "max_hotend_temp_c", 150.0, 500.0)
    _in_range(values, "max_bed_temp_c", 0.0, 200.0)
    _in_range(values, "max_velocity_mm_s", 0.1, 1000.0)
    _in_range(values, "max_volumetric_mm3_s", 0.001, 1000.0)

    size = values["size_mm"]
    if values["origin_x_mm"] < _BED_MARGIN_MM:
        raise ValueError("origin_x_mm leaves less than 5 mm of bed margin")
    if values["origin_y_mm"] < _BED_MARGIN_MM:
        raise ValueError("origin_y_mm leaves less than 5 mm of bed margin")
    if values["origin_x_mm"] + size > values["bed_width_mm"] - _BED_MARGIN_MM:
        raise ValueError("chart exceeds bed width or its 5 mm margin")
    if values["origin_y_mm"] + size > values["bed_depth_mm"] - _BED_MARGIN_MM:
        raise ValueError("chart exceeds bed depth or its 5 mm margin")

    nozzle = values["nozzle_mm"]
    layer_height = values["layer_height_mm"]
    line_width = values["line_width_mm"]
    if layer_height > nozzle:
        raise ValueError("layer_height_mm must not exceed nozzle_mm")
    if line_width < nozzle or line_width > 2.0 * nozzle:
        raise ValueError("line_width_mm must be between one and two nozzle diameters")

    max_velocity = values["max_velocity_mm_s"]
    if values["print_speed_mm_s"] > max_velocity:
        raise ValueError("print_speed_mm_s exceeds max_velocity_mm_s")
    if values["travel_speed_mm_s"] > max_velocity:
        raise ValueError("travel_speed_mm_s exceeds max_velocity_mm_s")

    volumetric_rate = line_width * layer_height * values["print_speed_mm_s"]
    if volumetric_rate > values["max_volumetric_mm3_s"] + 1e-12:
        raise ValueError(
            "line_width_mm * layer_height_mm * print_speed_mm_s exceeds max volumetric flow"
        )

    if values["hotend_temp_c"] > values["max_hotend_temp_c"]:
        raise ValueError("hotend_temp_c exceeds max_hotend_temp_c")
    if values["bed_temp_c"] > values["max_bed_temp_c"]:
        raise ValueError("bed_temp_c exceeds max_bed_temp_c")

    return values


def _rounded(value: float) -> float:
    return round(float(value), 6)


def _absolute_path(
    origin_x: float,
    origin_y: float,
    path_id: str,
    role: str,
    local_points: Iterable[tuple[float, float]],
) -> dict:
    return {
        "id": path_id,
        "role": role,
        "points_mm": [
            [_rounded(origin_x + point_x), _rounded(origin_y + point_y)]
            for point_x, point_y in local_points
        ],
    }


def _build_paths(values: dict[str, float]) -> tuple[list[dict], list[list[float]]]:
    origin_x = values["origin_x_mm"]
    origin_y = values["origin_y_mm"]
    size = values["size_mm"]
    paths: list[dict] = []
    midpoint = size / 2.0

    # A short purge/prime line stays inside the central layout gap and is not
    # part of the measurement sectors.  Consumers may exclude role=prime.
    paths.append(
        _absolute_path(
            origin_x,
            origin_y,
            "prime",
            "prime",
            (
                (midpoint - _PRIME_HALF_LENGTH_MM, midpoint),
                (midpoint + _PRIME_HALF_LENGTH_MM, midpoint),
            ),
        )
    )

    fiducial_centres = [
        (_FIDUCIAL_OFFSET_MM, size - _FIDUCIAL_OFFSET_MM),  # top-left
        (size - _FIDUCIAL_OFFSET_MM, size - _FIDUCIAL_OFFSET_MM),  # top-right
        (size - _FIDUCIAL_OFFSET_MM, _FIDUCIAL_OFFSET_MM),  # bottom-right
        (_FIDUCIAL_OFFSET_MM, _FIDUCIAL_OFFSET_MM),  # bottom-left
    ]
    fiducials = [
        [_rounded(origin_x + point_x), _rounded(origin_y + point_y)]
        for point_x, point_y in fiducial_centres
    ]
    fiducial_names = ("tl", "tr", "br", "bl")
    half = _FIDUCIAL_HALF_SIZE_MM
    for name, (centre_x, centre_y) in zip(fiducial_names, fiducial_centres):
        paths.append(
            _absolute_path(
                origin_x,
                origin_y,
                f"fiducial_{name}_h",
                "fiducial",
                (
                    (centre_x - half, centre_y),
                    (centre_x, centre_y),
                    (centre_x + half, centre_y),
                ),
            )
        )
        paths.append(
            _absolute_path(
                origin_x,
                origin_y,
                f"fiducial_{name}_v",
                "fiducial",
                (
                    (centre_x, centre_y - half),
                    (centre_x, centre_y),
                    (centre_x, centre_y + half),
                ),
            )
        )

    left_x = (_SECTOR_EDGE_MM, midpoint - _SECTOR_GAP_MM / 2.0)
    right_x = (midpoint + _SECTOR_GAP_MM / 2.0, size - _SECTOR_EDGE_MM)
    bottom_y = (_SECTOR_EDGE_MM, midpoint - _SECTOR_GAP_MM / 2.0)
    top_y = (midpoint + _SECTOR_GAP_MM / 2.0, size - _SECTOR_EDGE_MM)

    # Top-left: separated parallel lines.
    x0, x1 = left_x
    y0, y1 = top_y
    for index in range(4):
        line_y = y0 + (index + 1) * (y1 - y0) / 5.0
        points = ((x0, line_y), (x1, line_y))
        if index % 2:
            points = tuple(reversed(points))
        paths.append(
            _absolute_path(origin_x, origin_y, f"parallel_{index + 1:02d}", "parallel_line", points)
        )

    # Top-right: the only intentionally intersecting paths are the grid lines.
    x0, x1 = right_x
    y0, y1 = top_y
    grid_line_count = 5
    for index in range(grid_line_count):
        line_x = x0 + index * (x1 - x0) / (grid_line_count - 1)
        points = ((line_x, y0), (line_x, y1))
        if index % 2:
            points = tuple(reversed(points))
        paths.append(_absolute_path(origin_x, origin_y, f"grid_v_{index + 1:02d}", "grid", points))
    for index in range(grid_line_count):
        line_y = y0 + index * (y1 - y0) / (grid_line_count - 1)
        points = ((x0, line_y), (x1, line_y))
        if index % 2:
            points = tuple(reversed(points))
        paths.append(_absolute_path(origin_x, origin_y, f"grid_h_{index + 1:02d}", "grid", points))

    # Bottom-left: two independent sinusoidal curves, represented only by
    # straight segments so both SVG and G-code contain the same polyline.
    x0, x1 = left_x
    y0, y1 = bottom_y
    width = x1 - x0
    height = y1 - y0
    for index, baseline in enumerate((0.30, 0.70), start=1):
        curve_points = []
        for sample in range(13):
            t = sample / 12.0
            curve_points.append(
                (
                    x0 + t * width,
                    y0 + baseline * height + 0.12 * height * math.sin(2.0 * math.pi * t),
                )
            )
        paths.append(
            _absolute_path(origin_x, origin_y, f"curve_{index:02d}", "curve", curve_points)
        )

    # Bottom-right: four isolated L-shaped corner probes.
    x0, x1 = right_x
    y0, y1 = bottom_y
    width = x1 - x0
    height = y1 - y0
    corner_pad = min(2.0, width * 0.08, height * 0.08)
    corner_arm = min(5.0, width * 0.18, height * 0.18)
    corner_specs = (
        ("bl", x0 + corner_pad, y0 + corner_pad, "bottom_left"),
        ("br", x1 - corner_pad, y0 + corner_pad, "bottom_right"),
        ("tr", x1 - corner_pad, y1 - corner_pad, "top_right"),
        ("tl", x0 + corner_pad, y1 - corner_pad, "top_left"),
    )
    for name, centre_x, centre_y, orientation in corner_specs:
        if orientation == "bottom_left":
            points = (
                (centre_x + corner_arm, centre_y),
                (centre_x, centre_y),
                (centre_x, centre_y + corner_arm),
            )
        elif orientation == "bottom_right":
            points = (
                (centre_x - corner_arm, centre_y),
                (centre_x, centre_y),
                (centre_x, centre_y + corner_arm),
            )
        elif orientation == "top_right":
            points = (
                (centre_x - corner_arm, centre_y),
                (centre_x, centre_y),
                (centre_x, centre_y - corner_arm),
            )
        else:
            points = (
                (centre_x + corner_arm, centre_y),
                (centre_x, centre_y),
                (centre_x, centre_y - corner_arm),
            )
        paths.append(_absolute_path(origin_x, origin_y, f"corner_{name}", "corner", points))

    return paths, fiducials


def _build_svg(manifest: dict) -> str:
    origin_x, origin_y, size, _ = manifest["bounds_mm"]
    line_width = manifest["line_width_mm"]
    path_markup = []
    for path in manifest["paths"]:
        local_points = [
            (point_x - origin_x, point_y - origin_y) for point_x, point_y in path["points_mm"]
        ]
        first_x, first_y = local_points[0]
        commands = [f"M {_fmt(first_x)} {_fmt(first_y)}"]
        commands.extend(
            f"L {_fmt(point_x)} {_fmt(point_y)}" for point_x, point_y in local_points[1:]
        )
        path_markup.append(f'    <path id="{escape(path["id"])}" d="{" ".join(commands)}" />')

    return "\n".join(
        (
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_fmt(size)} {_fmt(size)}" '
            f'width="{_fmt(size)}mm" height="{_fmt(size)}mm" '
            'data-coordinate-system="printer-cartesian-y-up">',
            "  <!-- SVG uses local chart coordinates; Y is mirrored for a usual camera view. -->",
            f'  <g transform="translate(0,{_fmt(size)}) scale(1,-1)" fill="none" '
            f'stroke="black" stroke-width="{_fmt(line_width)}" stroke-linecap="round" '
            'stroke-linejoin="round">',
            *path_markup,
            "  </g>",
            "</svg>",
            "",
        )
    )


def _build_gcode(manifest: dict, values: dict[str, float]) -> str:
    line_width = values["line_width_mm"]
    layer_height = values["layer_height_mm"]
    filament_diameter = values["filament_diameter_mm"]
    print_feed = values["print_speed_mm_s"] * 60.0
    travel_feed = values["travel_speed_mm_s"] * 60.0
    filament_area = math.pi * (filament_diameter / 2.0) ** 2
    rectangular_area = line_width * layer_height
    z_layer = layer_height
    z_safe = z_layer + 1.0

    lines = [
        "; KlipperLearn first-layer geometry chart",
        "; EXPERIMENTAL: ensure the bed is clear and inspect the machine before running.",
        "; ONE LAYER ONLY: first-layer geometry; input shaping and pressure advance are not validated.",
        "; This file is generated offline and has not been sent to a printer.",
        "G90",
        "M83",
        "M220 S100",
        f"M140 S{_fmt(values['bed_temp_c'])}",
        f"M104 S{_fmt(values['hotend_temp_c'])}",
        f"M190 S{_fmt(values['bed_temp_c'])}",
        f"M109 S{_fmt(values['hotend_temp_c'])}",
        "G28",
        f"G1 Z{_fmt(z_safe)} F{_fmt(travel_feed)}",
    ]

    for path_index, path in enumerate(manifest["paths"]):
        lines.append(f"; PATH {path['id']} role={path['role']}")
        if path_index:
            lines.append(f"G1 Z{_fmt(z_safe)} F{_fmt(travel_feed)}")
        start_x, start_y = path["points_mm"][0]
        lines.append(f"G0 X{_fmt(start_x)} Y{_fmt(start_y)} F{_fmt(travel_feed)}")
        lines.append(f"G1 Z{_fmt(z_layer)} F{_fmt(travel_feed)}")
        previous_x, previous_y = start_x, start_y
        for end_x, end_y in path["points_mm"][1:]:
            length = math.hypot(end_x - previous_x, end_y - previous_y)
            extrusion = length * rectangular_area / filament_area
            if not extrusion > 0.0:
                raise ValueError(f"path {path['id']} contains a zero-length segment")
            lines.append(f"G1 X{_fmt(end_x)} Y{_fmt(end_y)} E{_fmt(extrusion)} F{_fmt(print_feed)}")
            previous_x, previous_y = end_x, end_y

    lines.extend(
        (
            "M400",
            f"G1 Z{_fmt(z_safe)} F{_fmt(travel_feed)}",
            "M104 S0",
            "M140 S0",
            "",
        )
    )
    return "\n".join(lines)


def build_chart(spec: dict) -> dict:
    """Return ``manifest``, mirrored ``svg``, and offline ``gcode`` for one chart."""

    values = _validate_spec(spec)
    paths, fiducials = _build_paths(values)
    bounds = [
        _rounded(values["origin_x_mm"]),
        _rounded(values["origin_y_mm"]),
        _rounded(values["size_mm"]),
        _rounded(values["size_mm"]),
    ]
    z_safe = _rounded(values["layer_height_mm"] + 1.0)
    manifest = {
        "schema_version": 1,
        "kind": "first_layer_geometry",
        "bounds_mm": bounds,
        "line_width_mm": _rounded(values["line_width_mm"]),
        "layer_height_mm": _rounded(values["layer_height_mm"]),
        "paths": paths,
        "fiducials_mm": fiducials,
        "not_validated_on_printer": True,
        "scope": "One layer of first-layer geometry only; no input-shaper or pressure-advance validation.",
        "coordinate_notes": {
            "printer_xy": "All manifest points are absolute printer X/Y coordinates in millimetres.",
            "svg": "SVG points are local to bounds_mm and its group mirrors Y for a usual camera Cartesian view.",
            "fiducials_order": ["TL", "TR", "BR", "BL"],
            "fiducials": "fiducials_mm are marker centres in TL, TR, BR, BL order; each centre is an explicit point in its fiducial path.",
            "prime": "The first path has role=prime and lies in the central gap outside measurement sectors; vision may exclude it.",
            "path_order": "G-code follows paths in this manifest order; only grid paths intentionally cross.",
        },
        "runtime_controls": {
            "speed_factor_percent": 100,
            "extrusion_factor": {
                "command": "M221",
                "record_before_trial": True,
                "reset_by_chart": False,
            },
        },
        "print_speed_mm_s": _rounded(values["print_speed_mm_s"]),
        "travel_speed_mm_s": _rounded(values["travel_speed_mm_s"]),
        "filament_diameter_mm": _rounded(values["filament_diameter_mm"]),
        "hotend_temp_c": _rounded(values["hotend_temp_c"]),
        "bed_temp_c": _rounded(values["bed_temp_c"]),
        "z_safe_mm": z_safe,
        "extrusion": {
            "mode": "relative E (M83)",
            "formula": "segment_length_mm * line_width_mm * layer_height_mm / (pi * (filament_diameter_mm / 2)^2)",
        },
    }
    return {
        "manifest": manifest,
        "svg": _build_svg(manifest),
        "gcode": _build_gcode(manifest, values),
    }


def _write_new_output(chart: dict, output_directory: Path) -> dict[str, str]:
    if output_directory.exists():
        if output_directory.is_symlink() or not output_directory.is_dir():
            raise ValueError("--output must be a directory that is safe to populate")
        if any(output_directory.iterdir()):
            raise ValueError(
                "--output must be empty; refusing to overwrite an existing destination"
            )
    else:
        output_directory.mkdir(parents=True, exist_ok=False)

    payloads = {
        "chart.json": json.dumps(chart["manifest"], indent=2, ensure_ascii=False) + "\n",
        "chart.svg": chart["svg"],
        "chart.gcode": chart["gcode"],
    }
    hashes: dict[str, str] = {}
    for filename, payload in payloads.items():
        target = output_directory / filename
        target.write_text(payload, encoding="utf-8", newline="\n")
        hashes[filename] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return hashes


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Build an offline Klipper first-layer geometry chart"
    )
    parser.add_argument("--input", required=True, help="JSON chart specification")
    parser.add_argument("--output", required=True, help="new or empty output directory")
    arguments = parser.parse_args(argv)

    try:
        input_path = Path(arguments.input)
        spec = json.loads(input_path.read_text(encoding="utf-8"))
        chart = build_chart(spec)
        hashes = _write_new_output(chart, Path(arguments.output))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps({"output": str(Path(arguments.output)), "sha256": hashes}, indent=2))


if __name__ == "__main__":
    main()
