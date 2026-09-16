import asyncio
import json
import math
import unittest

import httpx

from klipperlearn.print_context import fetch_print_context


def _status(filename="prints/benchy.gcode"):
    return {
        "print_stats": {"filename": filename, "state": "printing"},
        "configfile": {"settings": {"extruder": {"nozzle_diameter": 0.4}}},
        "toolhead": {"max_accel": 1800.0},
        "extruder": {"pressure_advance": 0.032},
        "gcode_move": {"extrude_factor": 1.01},
    }


class FakeMoonraker:
    def __init__(self):
        self.calls = []
        self.status = _status()
        self.metadata = {
            "filament_name": "Generic PLA",
            "filament_type": "PLA",
            "filament_colors": ["#112233"],
            "nozzle_diameter": 0.4,
            "estimated_time": 123.5,
            "print_start_time": 1700000000.0,
            "secret": "must not be copied",
        }
        self.metadata_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if request.method != "GET":
            return httpx.Response(405, request=request)
        if request.url.path == "/printer/objects/query":
            # Moonraker may emit non-standard NaN/Infinity values; encode them
            # explicitly because httpx's json= helper intentionally rejects them.
            content = json.dumps({"result": {"status": self.status}}, allow_nan=True).encode(
                "utf-8"
            )
            return httpx.Response(200, content=content, request=request)
        if request.url.path == "/server/files/metadata":
            if self.metadata_status == 404:
                return httpx.Response(404, json={"error": "missing"}, request=request)
            return httpx.Response(
                self.metadata_status, json={"result": self.metadata}, request=request
            )
        return httpx.Response(404, request=request)


class PrintContextTests(unittest.TestCase):
    def run_fetch(self, fake, **kwargs):
        return asyncio.run(
            fetch_print_context(
                "http://printer.invalid:7125",
                transport=httpx.MockTransport(fake),
                **kwargs,
            )
        )

    def test_reads_live_status_and_whitelisted_metadata_without_post(self):
        fake = FakeMoonraker()

        result = self.run_fetch(fake)

        self.assertEqual(
            set(result),
            {
                "material",
                "nozzle_mm",
                "configured_nozzle_mm",
                "parameters",
                "filename",
                "printer_state",
                "provenance",
                "conflicts",
                "effective_verified",
            },
        )
        self.assertEqual(result["material"]["type"], "PLA")
        self.assertEqual(result["material"]["name"], "Generic PLA")
        self.assertEqual(result["nozzle_mm"], 0.4)
        self.assertEqual(result["configured_nozzle_mm"], 0.4)
        self.assertEqual(result["filename"], "prints/benchy.gcode")
        self.assertEqual(result["printer_state"], "printing")
        self.assertEqual(
            result["parameters"],
            {"pressure_advance": 0.032, "accel_mm_s2": 1800.0, "extrude_factor": 1.01},
        )
        self.assertEqual(result["conflicts"], [])
        self.assertFalse(result["effective_verified"])
        self.assertNotIn("secret", result["provenance"]["metadata"]["fields"])
        self.assertEqual([request.method for request in fake.calls], ["GET", "GET"])
        self.assertEqual(fake.calls[0].url.path, "/printer/objects/query")
        self.assertEqual(
            fake.calls[0].url.query.decode(),
            "print_stats&configfile&toolhead&extruder&gcode_move",
        )
        self.assertEqual(fake.calls[1].url.params["filename"], "prints/benchy.gcode")

    def test_explicit_filename_is_used_even_when_not_printing(self):
        fake = FakeMoonraker()
        fake.status = _status(filename="")

        result = self.run_fetch(fake, filename="archive/old.gco")

        self.assertEqual(result["filename"], "archive/old.gco")
        self.assertEqual(fake.calls[1].url.params["filename"], "archive/old.gco")

    def test_changed_material_and_nozzle_are_reported_as_metadata_and_conflict(self):
        fake = FakeMoonraker()
        fake.metadata.update(filament_type="PETG", filament_name="PETG red", nozzle_diameter=0.6)

        result = self.run_fetch(fake)

        self.assertEqual(
            result["material"],
            {"name": "PETG red", "type": "PETG", "colors": ["#112233"]},
        )
        self.assertEqual(result["nozzle_mm"], 0.6)
        self.assertEqual(result["configured_nozzle_mm"], 0.4)
        self.assertEqual(result["conflicts"], ["nozzle_mm"])

    def test_missing_metadata_404_is_unknown_not_an_error(self):
        fake = FakeMoonraker()
        fake.metadata_status = 404

        result = self.run_fetch(fake)

        self.assertIsNone(result["material"])
        self.assertIsNone(result["nozzle_mm"])
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["provenance"]["metadata"]["status"], "unknown")
        self.assertEqual(result["provenance"]["metadata"]["reason"], "not_found")

    def test_missing_filename_does_not_request_metadata(self):
        fake = FakeMoonraker()
        fake.status = _status(filename="")

        result = self.run_fetch(fake)

        self.assertIsNone(result["filename"])
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(result["provenance"]["metadata"]["reason"], "no_filename")

    def test_nonfinite_live_values_become_none(self):
        fake = FakeMoonraker()
        fake.status["extruder"]["pressure_advance"] = math.nan
        fake.status["toolhead"]["max_accel"] = math.inf
        fake.status["gcode_move"]["extrude_factor"] = "nan"
        fake.status["configfile"]["settings"]["extruder"]["nozzle_diameter"] = math.inf

        result = self.run_fetch(fake)

        self.assertEqual(
            result["parameters"],
            {"pressure_advance": None, "accel_mm_s2": None, "extrude_factor": None},
        )
        self.assertIsNone(result["configured_nozzle_mm"])

    def test_rejects_path_injection_before_any_http_request(self):
        for bad in (
            "../secret.gcode",
            "prints/../secret.gcode",
            "/absolute.gcode",
            "prints\\escape.gcode",
            "C:/secret.gcode",
            "https://evil.invalid/file.gcode",
            "prints/%2e%2e/secret.gcode",
            "prints/model.stl",
        ):
            with self.subTest(filename=bad):
                fake = FakeMoonraker()
                with self.assertRaises(ValueError):
                    self.run_fetch(fake, filename=bad)
                self.assertEqual(fake.calls, [])

    def test_malformed_query_and_non_404_metadata_errors_are_sanitized(self):
        fake = FakeMoonraker()
        fake.status = {"print_stats": "not-an-object"}
        with self.assertRaisesRegex(ValueError, "Invalid Moonraker response"):
            self.run_fetch(fake)

        fake = FakeMoonraker()
        fake.metadata_status = 500
        with self.assertRaisesRegex(ValueError, "Moonraker metadata could not be queried"):
            self.run_fetch(fake)


if __name__ == "__main__":
    unittest.main()
