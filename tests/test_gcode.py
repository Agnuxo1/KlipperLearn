from pathlib import Path
import tempfile
import unittest

from klipperlearn.gcode import extract_gcode_metadata


class GcodeMetadataTests(unittest.TestCase):
    def test_extracts_only_audit_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.gcode"
            path.write_text(
                "M104 S235\nM140 S60\nSET_PRESSURE_ADVANCE ADVANCE=0.025\n"
                "SET_VELOCITY_LIMIT VELOCITY=120 ACCEL=3000\nM106 S255\n",
                encoding="utf-8",
            )
            result = extract_gcode_metadata(path)
        self.assertEqual(result["metadata"]["hotend_temp_c"], 235.0)
        self.assertEqual(result["metadata"]["pressure_advance"], 0.025)
        self.assertEqual(result["metadata"]["outer_speed_mm_s"], 120.0)
        self.assertTrue(result["contains_m106"])
