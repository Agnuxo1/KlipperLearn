import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from klipperlearn.orca_export import OrcaExportError, build_orca_overrides, main


PRINTER = "MyKlipper 0.4 nozzle"


def filament_profile() -> dict:
    return {
        "type": "filament",
        "from": "System",
        "inherits": "Generic PLA @System",
        "name": "Base PLA",
        "version": "2.4.2.0",
        "filament_settings_id": ["Base PLA"],
        "compatible_printers": [PRINTER],
        "nozzle_temperature": ["230"],
        "nested": {"preserve": ["yes"]},
    }


def process_profile() -> dict:
    return {
        "type": "process",
        "from": "System",
        "inherits": "0.20mm Standard @MyKlipper",
        "name": "Base process",
        "version": "2.4.2.0",
        "print_settings_id": "Base process",
        "compatible_printers": [PRINTER],
        "default_acceleration": "0",
        "initial_layer_acceleration": "200",
        "outer_wall_acceleration": "400",
        "inner_wall_acceleration": "500",
        "travel_acceleration": "750",
        "top_surface_acceleration": "3000",
        "outer_wall_speed": "25",
        "nozzle_temperature": "230",
    }


class OrcaExportTests(unittest.TestCase):
    def test_pressure_advance_preserves_inputs_and_candidate_schema(self) -> None:
        filament = filament_profile()
        process = process_profile()
        filament_before = copy.deepcopy(filament)
        process_before = copy.deepcopy(process)

        result = build_orca_overrides(
            filament,
            process,
            "pressure_advance",
            0.035,
            "PLA PA 0.035",
            PRINTER,
        )

        self.assertEqual(filament, filament_before)
        self.assertEqual(process, process_before)
        self.assertIsNot(result["filament"], filament)
        self.assertIsNot(result["process"], process)
        self.assertEqual(result["filament"]["from"], "User")
        self.assertEqual(result["filament"]["name"], "PLA PA 0.035")
        self.assertEqual(result["filament"]["filament_settings_id"], ["PLA PA 0.035"])
        self.assertEqual(result["filament"]["inherits"], filament["inherits"])
        self.assertEqual(result["process"]["from"], "User")
        self.assertEqual(result["process"]["print_settings_id"], "PLA PA 0.035")
        self.assertEqual(result["filament"]["enable_pressure_advance"], ["1"])
        self.assertEqual(result["filament"]["pressure_advance"], ["0.035"])
        self.assertEqual(result["warnings"], [])
        self.assertFalse(result["automatic_install"])
        self.assertFalse(result["validated_on_printer"])
        json.loads(json.dumps(result["filament"], allow_nan=False))
        json.loads(json.dumps(result["process"], allow_nan=False))

    def test_requires_explicit_compatibility_on_both_profiles(self) -> None:
        missing_filament = filament_profile()
        missing_filament.pop("compatible_printers")
        with self.assertRaises(OrcaExportError):
            build_orca_overrides(
                missing_filament,
                process_profile(),
                "pressure_advance",
                0.03,
                "candidate",
                PRINTER,
            )

        missing_process = process_profile()
        missing_process.pop("compatible_printers")
        with self.assertRaises(OrcaExportError):
            build_orca_overrides(
                filament_profile(),
                missing_process,
                "pressure_advance",
                0.03,
                "candidate",
                PRINTER,
            )

        wrong_printer = process_profile()
        wrong_printer["compatible_printers"] = ["another printer"]
        with self.assertRaises(OrcaExportError):
            build_orca_overrides(
                filament_profile(),
                wrong_printer,
                "pressure_advance",
                0.03,
                "candidate",
                PRINTER,
            )

    def test_rejects_unhashable_parameter_nan_and_unsafe_values(self) -> None:
        cases = (
            ([], 0.03, None),
            ("shaper_freq_x", 40.0, None),
            ("pressure_advance", math.nan, None),
            ("pressure_advance", 0.21, None),
            ("accel_mm_s2", 99.0, None),
            ("extrusion_factor", 1.01, math.nan),
        )
        for parameter, value, flow_ratio in cases:
            with self.subTest(parameter=parameter, value=value):
                with self.assertRaises(OrcaExportError):
                    build_orca_overrides(
                        filament_profile(),
                        process_profile(),
                        parameter,
                        value,
                        "candidate",
                        PRINTER,
                        flow_ratio,
                    )

    def test_flow_exports_effective_ratio_and_double_count_warning(self) -> None:
        result = build_orca_overrides(
            filament_profile(),
            process_profile(),
            "extrusion_factor",
            1.02,
            "PLA flow 1.02",
            PRINTER,
            base_flow_ratio=0.98,
        )

        self.assertEqual(result["filament"]["filament_flow_ratio"], ["0.9996"])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("M221", result["warnings"][0])
        self.assertIn("100", result["warnings"][0])
        self.assertNotIn("M221", json.dumps(result["filament"]))

        with self.assertRaises(OrcaExportError):
            build_orca_overrides(
                filament_profile(),
                process_profile(),
                "extrusion_factor",
                1.02,
                "missing flow",
                PRINTER,
            )

    def test_acceleration_caps_known_overrides_and_leaves_other_settings(self) -> None:
        process = process_profile()
        before_speed = process["outer_wall_speed"]
        before_temp = process["nozzle_temperature"]
        result = build_orca_overrides(
            filament_profile(),
            process,
            "accel_mm_s2",
            300.0,
            "accel 300",
            PRINTER,
        )
        output = result["process"]

        self.assertEqual(output["default_acceleration"], "300")
        self.assertEqual(output["initial_layer_acceleration"], "200")
        self.assertEqual(output["outer_wall_acceleration"], "300")
        self.assertEqual(output["inner_wall_acceleration"], "300")
        self.assertEqual(output["travel_acceleration"], "300")
        self.assertEqual(output["top_surface_acceleration"], "300")
        self.assertEqual(output["outer_wall_speed"], before_speed)
        self.assertEqual(output["nozzle_temperature"], before_temp)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("present in this JSON", result["warnings"][0])
        self.assertIn("unresolved inherited", result["warnings"][0])
        self.assertIn("slice", result["warnings"][0])

        bad = process_profile()
        bad["bridge_acceleration"] = "50%"
        with self.assertRaises(OrcaExportError):
            build_orca_overrides(filament_profile(), bad, "accel_mm_s2", 300.0, "bad", PRINTER)

    def test_rejects_profile_name_collisions_with_either_base_profile(self) -> None:
        filament = filament_profile()
        process = process_profile()
        collisions = (
            filament["name"],
            filament["filament_settings_id"][0],
            filament["inherits"],
            process["name"],
            process["print_settings_id"],
            process["inherits"],
        )
        for name in collisions:
            with self.subTest(name=name):
                with self.assertRaises(OrcaExportError):
                    build_orca_overrides(
                        filament,
                        process,
                        "pressure_advance",
                        0.03,
                        name,
                        PRINTER,
                    )

    def test_cli_writes_separate_safe_artifacts_and_rejects_nonempty_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            filament_path = root / "base-filament.json"
            process_path = root / "base-process.json"
            output = root / "export"
            filament_path.write_text(json.dumps(filament_profile()), encoding="utf-8")
            process_path.write_text(json.dumps(process_profile()), encoding="utf-8")

            exit_code = main(
                [
                    "--filament",
                    str(filament_path),
                    "--process",
                    str(process_path),
                    "--parameter",
                    "pressure_advance",
                    "--value",
                    "0.03",
                    "--name",
                    "PLA ../PA 0.03",
                    "--printer",
                    PRINTER,
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(exit_code, 0)
            names = {path.name for path in output.iterdir()}
            self.assertEqual(
                names,
                {"pla-pa-0-03_filament.json", "pla-pa-0-03_process.json", "report.json"},
            )
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertFalse(report["automatic_install"])
            self.assertFalse(report["validated_on_printer"])

            marker = output / "do-not-overwrite.txt"
            marker.write_text("keep", encoding="utf-8")
            self.assertEqual(
                main(
                    [
                        "--filament",
                        str(filament_path),
                        "--process",
                        str(process_path),
                        "--parameter",
                        "pressure_advance",
                        "--value",
                        "0.03",
                        "--name",
                        "candidate",
                        "--printer",
                        PRINTER,
                        "--output",
                        str(output),
                    ]
                ),
                2,
            )
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
