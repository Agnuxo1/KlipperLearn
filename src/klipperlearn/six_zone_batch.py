"""Six low, registered coupons in one job; no Z hops between individual paths.

This is a flow/speed screening experiment, not an Input Shaper calibration.
One physical batch remains one independent statistical session.
"""

from __future__ import annotations
import hashlib
import math
import re

from .calibration_chart import build_chart
from .mesh_inspection import six_zone_plan


def marker_bitmap(identifier):
    import cv2
    import numpy as np

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    return np.pad(cv2.aruco.generateImageMarker(dictionary, identifier, 6), 1, constant_values=255)


def marker_paths(identifier, x, y, width):
    bitmap = marker_bitmap(identifier)
    paths = []
    spacing = 3 / math.ceil(3 / width)
    for row in range(8):
        spans = []
        start = None
        for col in range(9):
            white = col < 8 and bitmap[row, col] > 0
            if white and start is None:
                start = col
            if not white and start is not None:
                spans.append((start, col))
                start = None
        for stripe in range(math.ceil(3 / width)):
            yy = y + 24 - row * 3 - (stripe + 0.5) * spacing
            for left, right in spans:
                paths.append([[x + left * 3 + width / 2, yy], [x + right * 3 - width / 2, yy]])
    return paths


def build_six_zone_batch(spec, rates, restore):
    if (
        not isinstance(rates, list)
        or len(rates) != 6
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in rates)
    ):
        raise ValueError("Six finite volumetric rates are required")
    if not 1 <= rates[0] <= 6 or any(not rates[0] <= v <= min(8, rates[0] * 1.5) for v in rates):
        raise ValueError("Screening is limited to a 50 percent bracket, at most 8 mm3/s")
    if any(right < left or right - left > 0.5 for left, right in zip(rates, rates[1:])):
        raise ValueError("Increase at most 0.5 mm3/s between coupons")
    layout = six_zone_plan(spec["bed_width_mm"], spec["bed_depth_mm"])
    if (
        min(cell["size_mm"][0] for cell in layout["cells"]) < 66
        or min(cell["size_mm"][1] for cell in layout["cells"]) < 92
    ):
        raise ValueError("Six registered coupons require cells at least 66 x 92 mm")
    if (
        spec["nozzle_mm"] != 0.4
        or spec["layer_height_mm"] != 0.2
        or not 0.4 <= spec["line_width_mm"] <= 0.48
    ):
        raise ValueError(
            "This registered coupon revision is validated only for 0.4 mm nozzle and 0.2 mm layers"
        )
    if max(rates) > spec["max_volumetric_mm3_s"]:
        raise ValueError("Requested screening exceeds its explicit volumetric ceiling")
    base = build_chart({**spec, "origin_x_mm": 5, "origin_y_mm": 5, "size_mm": 80})["manifest"]
    if not re.fullmatch(r"[A-Za-z0-9 _./+-]{1,64}", str(spec["material"])):
        raise ValueError("Invalid material label")
    width, height = spec["line_width_mm"], spec["layer_height_mm"]
    if max(rates) / (width * height) > spec["max_velocity_mm_s"]:
        raise ValueError("Screening exceeds machine velocity")
    flow_ratio = float(spec.get("flow_ratio", 1))
    acceleration = float(spec.get("acceleration_mm_s2", 500))
    if not 0.9 <= flow_ratio <= 1.1 or not 100 <= acceleration <= float(spec["max_accel_mm_s2"]):
        raise ValueError("Unverified flow or acceleration")
    if (
        not 0.8 <= restore["extrusion_factor"] <= 1.2
        or not 100 <= restore["accel_mm_s2"] <= spec["max_accel_mm_s2"]
    ):
        raise ValueError("Unverified restoration values")
    f = lambda value: format(value, ".7g")
    area = math.pi * (spec["filament_diameter_mm"] / 2) ** 2
    lines = [
        "; KlipperLearn six-zone screening v2",
        "; max_z_height: 0.60",
        "; filament_type = " + str(spec["material"]).replace("\n", " "),
        "; nozzle_diameter = 0.4",
        "; layer_height = 0.2",
        f"; first_layer_temperature = {f(spec['hotend_temp_c'])}",
        f"; first_layer_bed_temperature = {f(spec['bed_temp_c'])}",
        "G90",
        "M83",
        "M220 S100",
        "M221 S100",
        f"SET_VELOCITY_LIMIT ACCEL={f(acceleration)}",
        "G28",
        "G1 Z5 F300",
        f"M140 S{f(spec['bed_temp_c'])}",
        f"M104 S{f(spec['hotend_temp_c'])}",
        f"M190 S{f(spec['bed_temp_c'])}",
        f"M109 S{f(spec['hotend_temp_c'])}",
        "G92 E0",
    ]
    zones = []
    current = None
    between_zone_retracted = False
    extrusion_mm = 0.0

    def emit_path(points, speed):
        nonlocal current, extrusion_mm, between_zone_retracted
        x, y = points[0]
        if current is not None:
            lines.append("G1 E-0.8 F2100")
        lines.append(f"G1 X{f(x)} Y{f(y)} F{f(spec['travel_speed_mm_s'] * 60)}")
        if current is not None or between_zone_retracted:
            lines.append("G1 E0.8 F2100")
        between_zone_retracted = False
        current = (x, y)
        for x, y in points[1:]:
            length = math.dist(current, (x, y))
            if length <= 1e-8:
                continue
            extrusion = length * width * height * flow_ratio / area
            extrusion_mm += extrusion
            lines.append(f"G1 X{f(x)} Y{f(y)} E{f(extrusion)} F{f(speed * 60)}")
            current = (x, y)

    for index, cell in enumerate(layout["cells"]):
        x, y = cell["origin_mm"]
        x += (cell["size_mm"][0] - 64) / 2
        marker_x, marker_y = x + 20, y + 68
        paths = [
            {
                **path,
                "points_mm": [
                    [x + (px - 5) * 0.8, y + (py - 5) * 0.8] for px, py in path["points_mm"]
                ],
            }
            for path in base["paths"]
        ]
        zone = {
            "id": cell["id"],
            "marker_id": 30 + index,
            "bounds_mm": [x, y, 64, 64],
            "marker_corners_mm": [
                [marker_x + 3, marker_y + 21],
                [marker_x + 21, marker_y + 21],
                [marker_x + 21, marker_y + 3],
                [marker_x + 3, marker_y + 3],
            ],
            "paths": paths,
            "line_width_mm": width,
            "layer_height_mm": height,
            "volumetric_mm3_s": rates[index],
            "speed_mm_s": rates[index] / (width * height),
            "start_line": len(lines),
            "status": "planned",
        }
        zone["fiducials_mm"] = [
            [x + (px - 5) * 0.8, y + (py - 5) * 0.8] for px, py in base["fiducials_mm"]
        ]
        zone["measurement_lines"] = []
        lines += [
            f"; KL_ZONE_START {cell['id']}",
            "G1 Z5 F300",
            f"G1 X{f(x + 32)} Y{f(y + 32)} F{f(spec['travel_speed_mm_s'] * 60)}",
        ]
        current = None
        for layer in range(1, 4):
            lines += [f"G1 Z{f(layer * height)} F300", "M106 S0" if layer == 1 else "M106 S255"]
            speed = min(25, zone["speed_mm_s"]) if layer == 1 else zone["speed_mm_s"]
            measurement_start = len(lines)
            for path in paths:
                emit_path(path["points_mm"], speed)
            if layer > 1:
                zone["measurement_lines"].append([measurement_start, len(lines)])
            # Registration pattern has the same conservative speed in every zone.
            if layer <= 2:
                for points in marker_paths(30 + index, marker_x, marker_y, width):
                    emit_path(points, 25)
        lines += ["G1 E-0.8 F2100", "G1 Z5 F300", f"; KL_ZONE_END {cell['id']}"]
        # Remain retracted throughout the elevated inter-zone travel. Recover
        # only at the next path start, not while moving across finished coupons.
        between_zone_retracted = True
        zone["end_line"] = len(lines)
        zones.append(zone)
    lines += [
        "M400",
        "G1 Z5 F300",
        f"G1 X{f(spec['bed_width_mm'] - 10)} Y{f(spec['bed_depth_mm'] - 10)} F1800",
        "M400",
        "M106 S0",
        "M104 S0",
        "M140 S0",
        "; KL_RESTORE_START",
        f"M221 S{f(restore['extrusion_factor'] * 100)}",
        f"SET_VELOCITY_LIMIT ACCEL={f(restore['accel_mm_s2'])}",
        "M400",
    ]
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len((line + "\n").encode()))
    for zone in zones:
        zone["start_byte"], zone["end_byte"] = (
            offsets[zone.pop("start_line")],
            offsets[zone.pop("end_line")],
        )
        zone["measurement_bytes"] = [
            [offsets[a], offsets[b]] for a, b in zone.pop("measurement_lines")
        ]
    gcode = "\n".join(lines) + "\n"
    audit = audit_six_zone_gcode(gcode, spec["bed_width_mm"], spec["bed_depth_mm"])
    return {
        "gcode": gcode,
        "manifest": {
            "schema": "klipperlearn-six-zone-batch-v1",
            "zones": zones,
            "generator_revision": 2,
            "gcode_sha256": hashlib.sha256(gcode.encode()).hexdigest(),
            "source_spec": spec,
            "restore": restore,
            "extrusion_mm": extrusion_mm,
            "audit": audit,
            "same_statistical_session": True,
            "scope": "Low-height speed/flow screen; not maximum hotend capacity or Input Shaper validation",
        },
    }


def audit_six_zone_gcode(gcode, width, depth):
    z = 5.0
    downs = 0
    home = 0
    for raw in gcode.splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if line == "G28":
            home += 1
        if line.split()[0] in ("G0", "G1"):
            words = {
                key: float(value) for key, value in re.findall(r"\b([XYZ])([-+]?\d*\.?\d+)", line)
            }
            if "X" in words and not 0 <= words["X"] <= width:
                raise ValueError("X outside bed")
            if "Y" in words and not 0 <= words["Y"] <= depth:
                raise ValueError("Y outside bed")
            if "Z" in words:
                if not 0 <= words["Z"] <= 5:
                    raise ValueError("Z outside low coupon envelope")
                if words["Z"] < z - 1e-6:
                    downs += 1
                z = words["Z"]
    if home != 1 or downs != 6:
        raise ValueError("Expected one home and one descent per coupon, never per stroke")
    return {
        "homing_commands": home,
        "z_descents": downs,
        "z_hop_per_path": False,
        "bounds_checked": True,
    }
