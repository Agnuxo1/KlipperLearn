import hashlib
import io
import json
import math
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from klipperlearn.quadrant_batch import build_batch, main


SPEC = {
    "bed_width_mm": 270,
    "bed_depth_mm": 215,
    "origin_x_mm": 20,
    "origin_y_mm": 20,
    "size_mm": 80,
    "nozzle_mm": 0.4,
    "layer_height_mm": 0.2,
    "line_width_mm": 0.4,
    "filament_diameter_mm": 1.75,
    "print_speed_mm_s": 20,
    "travel_speed_mm_s": 60,
    "hotend_temp_c": 205,
    "bed_temp_c": 60,
    "max_hotend_temp_c": 260,
    "max_bed_temp_c": 110,
    "max_velocity_mm_s": 150,
    "max_volumetric_mm3_s": 10,
}

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_WORD = re.compile(rf"^(?P<letter>[A-Za-z])(?P<value>{_NUMBER})$")


def _commands(gcode):
    """Parse executable words only; semicolon comments are not commands."""

    commands = []
    for raw_line in gcode.splitlines():
        code = raw_line.split(";", 1)[0].strip()
        if not code:
            continue
        words = code.split()
        params = {}
        for word in words[1:]:
            match = _WORD.fullmatch(word)
            if match is None:
                raise AssertionError(f"unexpected G-code word: {word}")
            params[match.group("letter").upper()] = float(match.group("value"))
        commands.append((words[0].upper(), params))
    return commands


class QuadrantBatchTests(unittest.TestCase):
    def test_fixed_schema_layout_geometry_hash_and_variant(self):
        batch = build_batch(SPEC)
        manifest = batch["manifest"]
        self.assertEqual(set(batch), {"manifest", "files"})
        self.assertEqual([zone["id"] for zone in manifest["zones"]], ["bl", "br", "tl", "tr"])
        self.assertEqual(manifest["bed_mm"], [270.0, 215.0])
        self.assertEqual(
            manifest["material"],
            {"type": "PLA", "color": "white", "name": "White PLA"},
        )
        self.assertEqual(manifest["nozzle_mm"], 0.4)
        self.assertEqual(manifest["variant"], "White PLA / 0.4 mm nozzle")
        self.assertEqual(
            [zone["bounds_mm"][:2] for zone in manifest["zones"]],
            [[15.0, 10.0], [175.0, 10.0], [15.0, 125.0], [175.0, 125.0]],
        )
        self.assertEqual(len(batch["files"]), 4)
        self.assertEqual(
            {zone["gcode_filename"] for zone in manifest["zones"]}, set(batch["files"])
        )
        hashes = {zone["geometry_sha256"] for zone in manifest["zones"]}
        self.assertEqual(hashes, {manifest["geometry_sha256"]})
        self.assertTrue(all(len(value) == 64 for value in hashes))
        for zone in manifest["zones"]:
            self.assertEqual(zone["geometry_sha256"], manifest["geometry_sha256"])
            self.assertEqual(
                zone["gcode_sha256"],
                hashlib.sha256(batch["files"][zone["gcode_filename"]].encode()).hexdigest(),
            )
            self.assertEqual(zone["geometry"]["patch"]["size_mm"], [16.0, 16.0])
            self.assertEqual(zone["geometry"]["patch"]["layers"], 3)
            self.assertEqual(zone["geometry"]["patch"]["placement"], "grid_sector_replacement")

    def test_comment_text_is_not_treated_as_a_command(self):
        self.assertEqual(
            _commands("; G28 and M84 are forbidden commands\nG90 ; fake G28\n"),
            [("G90", {})],
        )

    def test_no_home_external_safe_travel_internal_layer_travel_and_shutdown(self):
        batch = build_batch(SPEC)
        for filename, gcode in batch["files"].items():
            with self.subTest(filename=filename):
                zone = next(
                    zone
                    for zone in batch["manifest"]["zones"]
                    if zone["gcode_filename"] == filename
                )
                commands = _commands(gcode)
                opcodes = [opcode for opcode, _ in commands]
                self.assertNotIn("G28", opcodes)
                self.assertNotIn("M84", opcodes)
                self.assertEqual(opcodes[:3], ["G90", "M83", "M220"])

                z = None
                z_moves = []
                e_values = []
                non_printing_xy = []
                for opcode, params in commands:
                    if opcode not in {"G0", "G1"}:
                        continue
                    if "Z" in params:
                        z_moves.append(params["Z"])
                    next_z = params.get("Z", z)
                    if "X" in params or "Y" in params:
                        if "E" in params:
                            e_values.append(params["E"])
                        else:
                            self.assertIsNotNone(next_z)
                            non_printing_xy.append((params.get("X"), params.get("Y"), next_z))
                    elif "E" in params:
                        e_values.append(params["E"])
                    z = next_z

                self.assertTrue(e_values)
                self.assertTrue(all(value > 0 and math.isfinite(value) for value in e_values))
                patch_path_count = len(zone["geometry"]["patch"]["path_ids"])
                expected_travel_count = (
                    len(zone["paths"])
                    + patch_path_count * (zone["geometry"]["patch"]["layers"] - 1)
                    + 1
                )
                self.assertEqual(len(non_printing_xy), expected_travel_count)
                external_travels = [travel for travel in non_printing_xy if travel[2] >= 5.0]
                internal_travels = [travel for travel in non_printing_xy if travel[2] < 5.0]
                self.assertEqual(
                    external_travels,
                    [(*zone["paths"][0]["points_mm"][0], 5.0), (260.0, 205.0, 5.0)],
                )
                self.assertTrue(internal_travels)
                x0, y0, width, depth = zone["bounds_mm"]
                for x, y, layer_z in internal_travels:
                    self.assertGreater(layer_z, 0.0)
                    self.assertTrue(x0 <= x <= x0 + width)
                    self.assertTrue(y0 <= y <= y0 + depth)

                self.assertEqual(z_moves, [5.0, 0.2, 0.4, 0.6, 5.0])
                self.assertEqual(
                    commands[-3:],
                    [
                        ("M221", {"S": 100.0}),
                        ("M104", {"S": 0.0}),
                        ("M140", {"S": 0.0}),
                    ],
                )

    def test_factors_are_mapped_and_restored(self):
        batch = build_batch(SPEC, temperatures=(201, 207), flows=(0.93, 1.04))
        expected = [(201.0, 0.93), (201.0, 1.04), (207.0, 0.93), (207.0, 1.04)]
        for zone, (temperature, factor) in zip(batch["manifest"]["zones"], expected):
            with self.subTest(zone=zone["id"]):
                self.assertEqual(
                    (zone["temperature_c"], zone["extrusion_factor"]),
                    (temperature, factor),
                )
                commands = _commands(batch["files"][zone["gcode_filename"]])
                m221 = [params["S"] for opcode, params in commands if opcode == "M221"]
                m109 = [params["S"] for opcode, params in commands if opcode == "M109"]
                self.assertIn(factor * 100.0, m221)
                self.assertEqual(m221[-1], 100.0)
                self.assertEqual(m109, [temperature])

    def test_per_zone_geometry_is_translation_invariant(self):
        batch = build_batch(SPEC)
        zones = batch["manifest"]["zones"]
        reference = zones[0]
        rx, ry = reference["bounds_mm"][:2]
        for zone in zones[1:]:
            dx = zone["bounds_mm"][0] - rx
            dy = zone["bounds_mm"][1] - ry
            self.assertEqual(len(zone["paths"]), len(reference["paths"]))
            for wanted, got in zip(reference["paths"], zone["paths"]):
                self.assertEqual(
                    (wanted["id"], wanted["role"], wanted["layers"]),
                    (got["id"], got["role"], got["layers"]),
                )
                translated = [[round(x + dx, 6), round(y + dy, 6)] for x, y in wanted["points_mm"]]
                self.assertEqual(translated, got["points_mm"])
        roles = {path["role"] for path in zones[0]["paths"]}
        self.assertNotIn("grid", roles)
        self.assertIn("solid_patch_perimeter", roles)
        self.assertIn("solid_patch_infill", roles)

    def test_finite_arguments_machine_variant_and_small_bed_are_rejected(self):
        for field in SPEC:
            bad = dict(SPEC)
            bad[field] = float("nan")
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    build_batch(bad)

        for temperatures in ((float("nan"), 205), (200, float("inf"))):
            with self.subTest(temperatures=temperatures):
                with self.assertRaises(ValueError):
                    build_batch(SPEC, temperatures=temperatures)
        for flows in ((0.97, float("nan")), (float("inf"), 1.0)):
            with self.subTest(flows=flows):
                with self.assertRaises(ValueError):
                    build_batch(SPEC, flows=flows)

        for field, value in (("bed_width_mm", 269), ("bed_depth_mm", 214), ("nozzle_mm", 0.6)):
            bad = dict(SPEC, **{field: value})
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    build_batch(bad)

        small = dict(SPEC, bed_width_mm=199, bed_depth_mm=199)
        with self.assertRaises(ValueError):
            build_batch(small)

    def test_cli_writes_manifest_and_four_gcode_files_to_empty_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_path = root / "base.json"
            output_path = root / "batch"
            input_path.write_text(json.dumps(SPEC), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                main(["--input", str(input_path), "--output", str(output_path)])
            self.assertEqual(
                {path.name for path in output_path.iterdir()},
                {
                    "manifest.json",
                    "quadrant_bl.gcode",
                    "quadrant_br.gcode",
                    "quadrant_tl.gcode",
                    "quadrant_tr.gcode",
                },
            )
            manifest = json.loads((output_path / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["zones"]), 4)
            occupied = root / "occupied"
            occupied.mkdir()
            (occupied / "keep.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(SystemExit):
                main(["--input", str(input_path), "--output", str(occupied)])


if __name__ == "__main__":
    unittest.main()
