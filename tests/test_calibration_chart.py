import json
import math
import re
import tempfile
import unittest
from pathlib import Path

from klipperlearn.calibration_chart import build_chart, main


SPEC = {
    "bed_width_mm": 220,
    "bed_depth_mm": 220,
    "origin_x_mm": 20,
    "origin_y_mm": 20,
    "size_mm": 80,
    "nozzle_mm": 0.4,
    "layer_height_mm": 0.2,
    "line_width_mm": 0.4,
    "filament_diameter_mm": 1.75,
    "print_speed_mm_s": 20,
    "travel_speed_mm_s": 80,
    "hotend_temp_c": 205,
    "bed_temp_c": 60,
    "max_hotend_temp_c": 260,
    "max_bed_temp_c": 110,
    "max_velocity_mm_s": 150,
    "max_volumetric_mm3_s": 10,
}


class CalibrationChartTests(unittest.TestCase):
    def test_manifest_contains_required_geometry_and_roles(self):
        chart = build_chart(SPEC)
        manifest = chart["manifest"]

        self.assertEqual(set(chart), {"manifest", "svg", "gcode"})
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["kind"], "first_layer_geometry")
        self.assertTrue(manifest["not_validated_on_printer"])
        self.assertEqual(
            manifest["fiducials_mm"], [[25.0, 95.0], [95.0, 95.0], [95.0, 25.0], [25.0, 25.0]]
        )
        self.assertEqual(manifest["paths"][0]["id"], "prime")
        self.assertEqual(manifest["paths"][0]["role"], "prime")
        fiducial_paths = [path for path in manifest["paths"] if path["role"] == "fiducial"]
        self.assertEqual(len(fiducial_paths), 8)
        for centre, suffix in zip(manifest["fiducials_mm"], ("tl", "tr", "br", "bl")):
            corner_paths = [
                path
                for path in fiducial_paths
                if path["id"] in {f"fiducial_{suffix}_h", f"fiducial_{suffix}_v"}
            ]
            self.assertEqual(
                {path["id"] for path in corner_paths},
                {f"fiducial_{suffix}_h", f"fiducial_{suffix}_v"},
            )
            for path in corner_paths:
                self.assertIn(centre, path["points_mm"])
        roles = {path["role"] for path in manifest["paths"]}
        self.assertTrue({"prime", "fiducial", "parallel_line", "grid", "curve", "corner"} <= roles)
        self.assertIn("scale(1,-1)", chart["svg"])
        self.assertIn("M83", chart["gcode"])
        self.assertIn("G90", chart["gcode"])
        self.assertIn("M220 S100", chart["gcode"])
        self.assertNotIn("M221", chart["gcode"])
        self.assertTrue(manifest["runtime_controls"]["extrusion_factor"]["record_before_trial"])

    def test_required_numbers_reject_bool_and_nan(self):
        for field in SPEC:
            for bad_value in (True, float("nan")):
                bad = dict(SPEC)
                bad[field] = bad_value
                with self.subTest(field=field, bad_value=bad_value):
                    with self.assertRaises(ValueError):
                        build_chart(bad)

        huge = dict(SPEC)
        huge["bed_width_mm"] = 10**10000
        with self.assertRaises(ValueError):
            build_chart(huge)

    def test_physical_and_safety_constraints(self):
        invalid = {
            "size_mm": 79.9,
            "origin_x_mm": 4.9,
            "layer_height_mm": 0.5,
            "line_width_mm": 0.9,
            "print_speed_mm_s": 151,
            "travel_speed_mm_s": 151,
            "max_volumetric_mm3_s": 1,
            "hotend_temp_c": 149.9,
            "bed_temp_c": 111,
        }
        for field, value in invalid.items():
            bad = dict(SPEC)
            bad[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    build_chart(bad)
        too_hot = dict(SPEC)
        too_hot["hotend_temp_c"] = 261
        with self.assertRaises(ValueError):
            build_chart(too_hot)

    def test_points_are_inside_bounds_and_extrusion_is_positive(self):
        chart = build_chart(SPEC)
        x0, y0, width, height = chart["manifest"]["bounds_mm"]
        e_values = []
        for path in chart["manifest"]["paths"]:
            self.assertGreaterEqual(len(path["points_mm"]), 2)
            for x, y in path["points_mm"]:
                self.assertGreaterEqual(x, x0)
                self.assertLessEqual(x, x0 + width)
                self.assertGreaterEqual(y, y0)
                self.assertLessEqual(y, y0 + height)
        for line in chart["gcode"].splitlines():
            if line.startswith("G1 X") and " E" in line:
                match = re.search(r"\bE([-+0-9.eE]+)", line)
                self.assertIsNotNone(match)
                e_values.append(float(match.group(1)))
        self.assertTrue(e_values)
        self.assertTrue(all(value > 0 for value in e_values))
        self.assertFalse(
            any(
                line.split(maxsplit=1)[0] in {"G2", "G3"}
                for line in chart["gcode"].splitlines()
                if line
            )
        )
        self.assertNotIn("M84", chart["gcode"])

    def test_gcode_motion_matches_manifest_paths_and_formula(self):
        chart = build_chart(SPEC)
        manifest = chart["manifest"]
        observed: dict[str, list[tuple[float, float]]] = {}
        observed_e = []
        current_id = None
        xy_pattern = re.compile(r"^[G][01] X([-+0-9.eE]+) Y([-+0-9.eE]+)")
        e_pattern = re.compile(r"\bE([-+0-9.eE]+)")
        for line in chart["gcode"].splitlines():
            if line.startswith("; PATH "):
                current_id = line.split()[2]
                observed[current_id] = []
                continue
            if current_id is None:
                continue
            match = xy_pattern.match(line)
            if match:
                observed[current_id].append((float(match.group(1)), float(match.group(2))))
                if line.startswith("G1 "):
                    e_match = e_pattern.search(line)
                    self.assertIsNotNone(e_match)
                    observed_e.append(float(e_match.group(1)))

        expected_e = []
        area = SPEC["line_width_mm"] * SPEC["layer_height_mm"]
        filament_area = math.pi * (SPEC["filament_diameter_mm"] / 2) ** 2
        for path in manifest["paths"]:
            expected = [tuple(point) for point in path["points_mm"]]
            self.assertIn(path["id"], observed)
            self.assertEqual(len(expected), len(observed[path["id"]]))
            for wanted, got in zip(expected, observed[path["id"]]):
                self.assertAlmostEqual(wanted[0], got[0], places=5)
                self.assertAlmostEqual(wanted[1], got[1], places=5)
            for (x1, y1), (x2, y2) in zip(expected, expected[1:]):
                expected_e.append(math.hypot(x2 - x1, y2 - y1) * area / filament_area)
        self.assertEqual(len(expected_e), len(observed_e))
        for wanted, got in zip(expected_e, observed_e):
            self.assertAlmostEqual(wanted, got, places=5)

    def test_cli_writes_three_files_and_rejects_nonempty_destination(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "spec.json"
            output_path = root / "chart"
            input_path.write_text(json.dumps(SPEC), encoding="utf-8")
            main(["--input", str(input_path), "--output", str(output_path)])
            self.assertEqual(
                {path.name for path in output_path.iterdir()},
                {"chart.json", "chart.svg", "chart.gcode"},
            )

            occupied = root / "occupied"
            occupied.mkdir()
            (occupied / "keep.txt").write_text("do not overwrite", encoding="utf-8")
            with self.assertRaises(SystemExit):
                main(["--input", str(input_path), "--output", str(occupied)])


if __name__ == "__main__":
    unittest.main()
