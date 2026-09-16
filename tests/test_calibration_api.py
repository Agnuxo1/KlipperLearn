import json
from pathlib import Path
import tempfile
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
from klipperlearn.calibration_api import install_calibration_api, _machine_snapshot
from test_calibration_control import FakeMoonraker
from test_calibration_chart import SPEC


class CalibrationIntegrationTests(unittest.TestCase):
    def test_negative_homing_travel_does_not_expand_chart_bed(self):
        info = _machine_snapshot(
            {
                "result": {
                    "status": {
                        "webhooks": {"state": "ready"},
                        "print_stats": {"state": "standby"},
                        "toolhead": {"axis_minimum": [-8, -1, 0], "axis_maximum": [270, 215, 195]},
                        "configfile": {
                            "settings": {
                                "extruder": {
                                    "max_temp": 280,
                                    "nozzle_diameter": 0.4,
                                    "filament_diameter": 1.75,
                                },
                                "heater_bed": {"max_temp": 125},
                                "printer": {"max_velocity": 150},
                            }
                        },
                    }
                }
            }
        )
        self.assertTrue(info["ready"])
        self.assertEqual(info["machine"]["bed_width_mm"], 270)
        self.assertEqual(info["machine"]["bed_depth_mm"], 215)
        self.assertEqual(info["machine"]["origin_x_mm"], 0)

    def test_real_controller_and_chart_contracts(self):
        fake = FakeMoonraker()

        def respond(request):
            response = fake.respond(request)
            if request.method == "GET":
                body = response.json()
                status = body["result"]["status"]
                status["toolhead"].update(axis_minimum=[0, 0, 0], axis_maximum=[220, 220, 250])
                status["configfile"]["settings"].update(
                    extruder={"max_temp": 280, "nozzle_diameter": 0.4, "filament_diameter": 1.75},
                    heater_bed={"max_temp": 125},
                )
                status["configfile"]["settings"]["printer"]["max_velocity"] = 150
                return httpx.Response(200, json=body)
            return response

        with tempfile.TemporaryDirectory() as directory:
            app = FastAPI()
            install_calibration_api(
                app,
                "test-key",
                "http://printer.invalid",
                transport=httpx.MockTransport(respond),
                root=directory,
            )
            with TestClient(app) as client:
                base = "/mobile/api/calibration"
                auth = {"X-KlipperLearn-Token": "test-key"}
                self.assertEqual(client.get(base + "/info").status_code, 401)
                info = client.get(base + "/info", headers=auth).json()["result"]
                self.assertEqual(info["machine"]["max_hotend_temp_c"], 275)
                created = client.post(base + "/charts", headers=auth, json=SPEC)
                self.assertEqual(created.status_code, 201, created.text)
                chart = created.json()["chart_id"]
                saved = json.loads((Path(directory) / chart / "chart.json").read_text())
                self.assertEqual(saved["kind"], "first_layer_geometry")
                for parameter, value, bounds, step in [
                    ("pressure_advance", 0.03, [0, 0.2], 0.005),
                    ("extrusion_factor", 1.01, [0.8, 1.2], 0.02),
                    ("accel_mm_s2", 2550, [100, 5000], 100),
                ]:
                    response = client.post(
                        base + "/adjustments/preview",
                        headers=auth,
                        json={
                            "parameter": parameter,
                            "value": value,
                            "bounds": bounds,
                            "maximum_step": step,
                        },
                    )
                    self.assertEqual(response.status_code, 200, response.text)
                    proposal = response.json()["id"]
                    applied = client.post(
                        base + "/adjustments/apply",
                        headers=auth,
                        json={"proposal_id": proposal, "confirmed": True},
                    )
                    self.assertEqual(applied.status_code, 200, applied.text)
                    self.assertEqual(applied.json()["status"], "applied")
                    restored = client.post(
                        base + "/adjustments/restore",
                        headers=auth,
                        json={"proposal_id": proposal, "confirmed": True},
                    )
                    self.assertEqual(restored.json()["status"], "restored")
                fake.state = "printing"
                blocked = client.post(
                    base + "/adjustments/preview",
                    headers=auth,
                    json={
                        "parameter": "pressure_advance",
                        "value": 0.03,
                        "bounds": [0, 0.2],
                        "maximum_step": 0.005,
                    },
                )
                self.assertEqual(blocked.status_code, 409)
