import numpy as np
import cv2
import pytest

from klipperlearn.six_zone_batch import build_six_zone_batch, marker_bitmap
from klipperlearn.registered_vision import analyze_registered_photo

SPEC = {
    "bed_width_mm": 270,
    "bed_depth_mm": 215,
    "origin_x_mm": 10,
    "origin_y_mm": 10,
    "size_mm": 80,
    "nozzle_mm": 0.4,
    "layer_height_mm": 0.2,
    "line_width_mm": 0.42,
    "filament_diameter_mm": 1.75,
    "print_speed_mm_s": 25,
    "travel_speed_mm_s": 100,
    "hotend_temp_c": 220,
    "bed_temp_c": 60,
    "max_hotend_temp_c": 260,
    "max_bed_temp_c": 110,
    "max_velocity_mm_s": 150,
    "max_volumetric_mm3_s": 6,
    "material": "PLA",
    "max_accel_mm_s2": 3000,
    "acceleration_mm_s2": 750,
    "flow_ratio": 0.98,
}
RESTORE = {"extrusion_factor": 1, "accel_mm_s2": 1500}


def test_six_low_zones_preserve_width_separate_phases_and_restore():
    batch = build_six_zone_batch(SPEC, [4, 4.4, 4.8, 5.2, 5.6, 6], RESTORE)
    manifest = batch["manifest"]
    gcode = batch["gcode"]
    raw = gcode.encode()
    assert manifest["audit"]["homing_commands"] == 1
    assert manifest["audit"]["z_descents"] == 6
    assert manifest["same_statistical_session"]
    assert gcode.count("G1 Z0.2 F300") == 6
    assert gcode.count("G1 Z0.4 F300") == 6
    assert len({zone["marker_id"] for zone in manifest["zones"]}) == 6
    for zone in manifest["zones"]:
        assert zone["line_width_mm"] == 0.42
        assert raw[zone["start_byte"] : zone["end_byte"]].startswith(b"; KL_ZONE_START")
        for start, end in zone["measurement_bytes"]:
            assert zone["start_byte"] <= start < end <= zone["end_byte"]
        x, y, w, h = zone["bounds_mm"]
        assert all(
            x - 1e-6 <= px <= x + w + 1e-6 and y - 1e-6 <= py <= y + h + 1e-6
            for path in zone["paths"]
            for px, py in path["points_mm"]
        )
    assert "M221 S100\nSET_VELOCITY_LIMIT ACCEL=1500\nM400" in gcode
    # No positive extrusion above the deposition plane, including transitions.
    z = 5
    for line in gcode.splitlines():
        if line.startswith("G1 Z"):
            z = float(line.split()[1][1:])
        if line.startswith("G1 E0.8"):
            assert z <= 0.6


def test_limits_and_injection_are_rejected():
    for rates in ([4] * 5, [4, 4.4, 4.8, 5.2, 5.6, 9], [4, 5, 5, 5, 5, 5]):
        with pytest.raises(ValueError):
            build_six_zone_batch(SPEC, rates, RESTORE)
    with pytest.raises(ValueError):
        build_six_zone_batch({**SPEC, "material": "PLA\rG28"}, [4] * 6, RESTORE)


def test_registered_vision_finds_marker_and_does_not_invent_missing_views(tmp_path):
    batch = build_six_zone_batch(SPEC, [4] * 6, RESTORE)
    scale = 5
    frame = np.zeros((215 * scale, 270 * scale, 3), np.uint8)
    for zone in batch["manifest"]["zones"]:
        x, y, _, _ = zone["bounds_mm"]
        mx, my = x + 20, y + 68
        marker = cv2.resize(
            marker_bitmap(zone["marker_id"]), (120, 120), interpolation=cv2.INTER_NEAREST
        )
        left, top = round(mx * scale), round((215 - my - 24) * scale)
        frame[top : top + 120, left : left + 120] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        for path in zone["paths"]:
            points = np.int32(
                [[round(px * scale), round((215 - py) * scale)] for px, py in path["points_mm"]]
            )
            cv2.polylines(frame, [points], False, (255, 255, 255), 2, cv2.LINE_AA)
    path = tmp_path / "synthetic-registration-fixture.jpg"
    cv2.imwrite(str(path), frame)
    result = analyze_registered_photo(path, batch["manifest"])
    assert len(result["zones"]) == 6
    assert all(zone["reason"] != "marker_missing_or_ambiguous" for zone in result["zones"])
    assert all(zone["usable"] for zone in result["zones"])
    scores = [zone["analysis"]["iou"] for zone in result["zones"]]
    assert min(scores) > 0.55 and max(scores) - min(scores) < 0.06
    blank = tmp_path / "blank.jpg"
    cv2.imwrite(str(blank), np.zeros((200, 200, 3), np.uint8))
    assert not any(
        zone["usable"] for zone in analyze_registered_photo(blank, batch["manifest"])["zones"]
    )
