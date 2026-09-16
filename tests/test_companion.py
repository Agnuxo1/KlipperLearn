import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from klipperlearn.companion import install_companion
from klipperlearn.webapp import create_app


class CompanionTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.requests = []
        self.file_entries = []
        self.state = "printing"
        self.ready = "ready"
        self.webhooks_ready = None
        self.objects = ["input_shaper", "resonance_tester", "adxl345"]
        self.config = {
            "extruder": {"max_temp": 280},
            "heater_bed": {"max_temp": 120},
            "printer": {"max_velocity": 200, "max_accel": 3000},
            "input_shaper": {
                "shaper_type_x": "mzv",
                "shaper_freq_x": 45.0,
                "shaper_type_y": "mzv",
                "shaper_freq_y": 42.0,
            },
        }
        self.extruder_status = {"pressure_advance": 0.025}
        app = FastAPI()
        self.viewer = install_companion(
            app,
            "test-token-not-real",
            transport=httpx.MockTransport(self._respond),
        )
        self.client = TestClient(app)
        self.auth = {"X-KlipperLearn-Token": "test-token-not-real"}

    def test_auth_and_command_allowlist(self):
        self.assertEqual(self.client.get("/mobile/api/printer/status").status_code, 401)
        self.assertEqual(
            self.client.post("/mobile/api/printer/G28", headers=self.auth).status_code, 404
        )
        self.assertEqual(self.calls, [])

    def test_new_printer_routes_require_auth(self):
        self.assertEqual(self.client.get("/mobile/api/printer/files").status_code, 401)
        self.assertEqual(self.client.post("/mobile/api/printer/home").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/mobile/api/printer/temperature",
                json={"extruder": 200, "bed": 60},
            ).status_code,
            401,
        )
        self.assertEqual(self.client.post("/mobile/api/printer/cool").status_code, 401)
        self.assertEqual(
            self.client.post(
                "/mobile/api/printer/start",
                json={"filename": "model.gcode"},
            ).status_code,
            401,
        )
        self.assertEqual(self.client.get("/mobile/api/printer/capabilities").status_code, 401)
        self.assertEqual(self.calls, [])

    def test_files_filters_safe_model_entries_and_sorts_by_path(self):
        self.file_entries = [
            {"path": "z.gcode", "size": 3},
            {"path": "subdir/a.gco", "size": 2},
            {"path": "model.g", "size": 1},
            {"path": "model.g3d", "size": 4},
            {"path": "notes.txt", "size": 5},
            {"path": "../secret.gcode", "size": 6},
            {"path": "/absolute.gcode", "size": 7},
            {"path": "subdir\\escape.gcode", "size": 8},
            {"path": "C:/drive.gcode", "size": 9},
            {"name": "missing-path"},
            "not-an-object",
        ]

        response = self.client.get("/mobile/api/printer/files", headers=self.auth)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "result": [
                    {"path": "model.g", "size": 1},
                    {"path": "model.g3d", "size": 4},
                    {"path": "subdir/a.gco", "size": 2},
                    {"path": "z.gcode", "size": 3},
                ]
            },
        )
        self.assertEqual(self.calls, [("GET", "/server/files/list")])
        self.assertEqual(self.requests[0][2], "root=gcodes")

    def test_capabilities_returns_safe_validated_klipper_contract(self):
        self.state = "standby"

        response = self.client.get("/mobile/api/printer/capabilities", headers=self.auth)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "result": {
                    "connected": True,
                    "printer_state": "standby",
                    "machine": {"name": "Klipper"},
                    "limits": {
                        "extruder_max": 275.0,
                        "bed_max": 110.0,
                        "max_velocity": 200.0,
                        "max_accel": 3000.0,
                    },
                    "features": {
                        "input_shaper": True,
                        "resonance_tester": True,
                        "accelerometer": True,
                        "pressure_advance": True,
                    },
                    "input_shaper": self.config["input_shaper"],
                    "calibration": {
                        "automatic_available": False,
                        "model_trained": False,
                    },
                }
            },
        )
        self.assertEqual(
            self.calls,
            [("GET", "/printer/objects/list"), ("GET", "/printer/objects/query")],
        )
        self.assertEqual(self.requests[0][2], "")
        self.assertEqual(self.requests[1][2], "configfile&webhooks&print_stats&extruder")
        self.assertNotIn("configfile", json.dumps(response.json()))

    def test_capabilities_fails_closed_for_missing_or_nonfinite_config(self):
        for config in (
            {
                "extruder": {"max_temp": 280},
                "heater_bed": {"max_temp": 120},
                "printer": {"max_velocity": 200},
            },
            {
                "extruder": {"max_temp": float("nan")},
                "heater_bed": {"max_temp": 120},
                "printer": {"max_velocity": 200, "max_accel": 3000},
            },
            {
                "extruder": {"max_temp": 280},
                "heater_bed": {"max_temp": 120},
                "printer": {"max_velocity": float("inf"), "max_accel": 3000},
            },
        ):
            self.calls.clear()
            self.requests.clear()
            self.config = config
            response = self.client.get("/mobile/api/printer/capabilities", headers=self.auth)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                self.calls,
                [
                    ("GET", "/printer/objects/list"),
                    ("GET", "/printer/objects/query"),
                ],
            )

        self.config = {
            "extruder": {"max_temp": 280},
            "heater_bed": {"max_temp": 120},
            "printer": {"max_velocity": 200, "max_accel": 3000},
        }
        self.objects = ["gcode_move", "gcode_macro ADXL345_QUERY"]
        self.extruder_status = {}
        response = self.client.get("/mobile/api/printer/capabilities", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["result"]["features"],
            {
                "input_shaper": False,
                "resonance_tester": False,
                "accelerometer": False,
                "pressure_advance": False,
            },
        )
        self.assertIsNone(response.json()["result"]["input_shaper"])

    def test_capabilities_uses_canonical_webhooks_state_and_fails_closed_when_missing(self):
        self.webhooks_ready = True
        self.ready = "shutdown"
        response = self.client.get("/mobile/api/printer/capabilities", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["result"]["connected"])

        self.ready = None
        response = self.client.get("/mobile/api/printer/capabilities", headers=self.auth)
        self.assertEqual(response.status_code, 503)

        self.webhooks_ready = None
        response = self.client.get("/mobile/api/printer/capabilities", headers=self.auth)
        self.assertEqual(response.status_code, 503)

    def test_home_requires_ready_and_allowed_print_state(self):
        for state in ("standby", "complete", "cancelled", "error"):
            self.calls.clear()
            self.requests.clear()
            self.state = state
            response = self.client.post("/mobile/api/printer/home", headers=self.auth)
            self.assertEqual(response.status_code, 200, state)
            self.assertEqual(self._post_calls(), [("POST", "/printer/gcode/script")])
            self.assertEqual(self.requests[-1][3], {"script": "G28"})

        for state in ("printing", "paused", "unknown"):
            self.calls.clear()
            self.requests.clear()
            self.state = state
            response = self.client.post("/mobile/api/printer/home", headers=self.auth)
            self.assertEqual(response.status_code, 409, state)
            self.assertEqual(self._post_calls(), [])

        self.calls.clear()
        self.requests.clear()
        self.ready = "shutdown"
        self.state = "standby"
        response = self.client.post("/mobile/api/printer/home", headers=self.auth)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._post_calls(), [])
        self.ready = "ready"

    def test_temperature_accepts_bounds_and_emits_only_whitelisted_commands(self):
        self.state = "standby"
        for payload, script in (
            ({"extruder": 0, "bed": 0}, "M104 S0\nM140 S0"),
            ({"extruder": 275, "bed": 110}, "M104 S275\nM140 S110"),
            ({"extruder": 215.5, "bed": 60.25}, "M104 S215.5\nM140 S60.25"),
        ):
            self.calls.clear()
            self.requests.clear()
            response = self.client.post(
                "/mobile/api/printer/temperature",
                headers=self.auth,
                json=payload,
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self._post_calls(), [("POST", "/printer/gcode/script")])
            self.assertEqual(self.requests[-1][3], {"script": script})

    def test_temperature_uses_live_conservative_config_limits(self):
        self.state = "standby"
        for target in (280, 285):
            self.calls.clear()
            self.requests.clear()
            response = self.client.post(
                "/mobile/api/printer/temperature",
                headers=self.auth,
                json={"extruder": target, "bed": 60},
            )
            self.assertEqual(response.status_code, 422, target)
            self.assertEqual(self._post_calls(), [])
            self.assertIn(("GET", "/printer/objects/query"), self.calls)

        self.config["extruder"].pop("max_temp")
        self.calls.clear()
        self.requests.clear()
        response = self.client.post(
            "/mobile/api/printer/temperature",
            headers=self.auth,
            json={"extruder": 200, "bed": 60},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self._post_calls(), [])

    def test_temperature_rejects_invalid_payloads_without_post(self):
        invalid_payloads = (
            {},
            {"extruder": 0},
            {"extruder": 0, "bed": 0, "extra": "M997"},
            {"extruder": -0.1, "bed": 0},
            {"extruder": 285.1, "bed": 0},
            {"extruder": 0, "bed": -0.1},
            {"extruder": 0, "bed": 110.1},
            {"extruder": "200", "bed": 60},
            {"extruder": True, "bed": 60},
        )
        for payload in invalid_payloads:
            self.calls.clear()
            self.requests.clear()
            response = self.client.post(
                "/mobile/api/printer/temperature",
                headers=self.auth,
                json=payload,
            )
            self.assertEqual(response.status_code, 422, payload)
            self.assertEqual(self._post_calls(), [])

        for body in (b'{"extruder":NaN,"bed":60}', b'{"extruder":Infinity,"bed":60}'):
            self.calls.clear()
            self.requests.clear()
            response = self.client.post(
                "/mobile/api/printer/temperature",
                headers={**self.auth, "Content-Type": "application/json"},
                content=body,
            )
            self.assertEqual(response.status_code, 422)
            self.assertEqual(self._post_calls(), [])

    def test_temperature_rejects_non_home_states_or_not_ready_without_post(self):
        for state in ("printing", "paused", "unknown", "idle"):
            self.calls.clear()
            self.requests.clear()
            self.state = state
            response = self.client.post(
                "/mobile/api/printer/temperature",
                headers=self.auth,
                json={"extruder": 200, "bed": 60},
            )
            self.assertEqual(response.status_code, 409, state)
            self.assertEqual(self._post_calls(), [])

        self.calls.clear()
        self.requests.clear()
        self.state = "standby"
        self.ready = "shutdown"
        response = self.client.post(
            "/mobile/api/printer/temperature",
            headers=self.auth,
            json={"extruder": 200, "bed": 60},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._post_calls(), [])
        self.ready = "ready"

    def test_cool_requires_safe_state_and_emits_only_cooldown_commands(self):
        self.state = "standby"
        response = self.client.post("/mobile/api/printer/cool", headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._post_calls(), [("POST", "/printer/gcode/script")])
        self.assertEqual(self.requests[-1][3], {"script": "M104 S0\nM140 S0"})

        for state in ("complete", "cancelled", "error"):
            self.calls.clear()
            self.requests.clear()
            self.state = state
            response = self.client.post("/mobile/api/printer/cool", headers=self.auth)
            self.assertEqual(response.status_code, 200, state)
            self.assertEqual(self._post_calls(), [("POST", "/printer/gcode/script")])

        for state in ("printing", "paused", "unknown", "idle"):
            self.calls.clear()
            self.requests.clear()
            self.state = state
            response = self.client.post("/mobile/api/printer/cool", headers=self.auth)
            self.assertEqual(response.status_code, 409, state)
            self.assertEqual(self._post_calls(), [])

        self.calls.clear()
        self.requests.clear()
        self.state = "standby"
        self.ready = "shutdown"
        response = self.client.post("/mobile/api/printer/cool", headers=self.auth)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._post_calls(), [])
        self.ready = "ready"

    def test_start_requires_exact_safe_existing_file_and_standby(self):
        self.file_entries = [
            {"path": "models/part.gcode", "size": 1},
            {"path": "other.gco", "size": 2},
            {"path": "../part.gcode", "size": 3},
            {"path": "models/part.stl", "size": 4},
        ]
        self.state = "standby"
        response = self.client.post(
            "/mobile/api/printer/start",
            headers=self.auth,
            json={"filename": "models/part.gcode"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self._post_calls(),
            [("POST", "/printer/print/start")],
        )
        self.assertEqual(self.requests[-1][3], {"filename": "models/part.gcode"})

    def test_start_rejects_traversal_and_bad_extension_without_moonraker_post(self):
        self.file_entries = [{"path": "models/part.gcode", "size": 1}]
        for filename in (
            "../models/part.gcode",
            "models/../part.gcode",
            "/models/part.gcode",
            "models\\part.gcode",
            "C:/models/part.gcode",
            "models/part.stl",
        ):
            self.calls.clear()
            self.requests.clear()
            response = self.client.post(
                "/mobile/api/printer/start",
                headers=self.auth,
                json={"filename": filename},
            )
            self.assertEqual(response.status_code, 422, filename)
            self.assertEqual(self._post_calls(), [])
            self.assertEqual(self.calls, [])

    def test_start_rejects_missing_file_without_post(self):
        self.file_entries = [{"path": "models/part.gcode", "size": 1}]
        self.state = "standby"
        response = self.client.post(
            "/mobile/api/printer/start",
            headers=self.auth,
            json={"filename": "models/missing.gcode"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._post_calls(), [])

    def test_start_rejects_non_standby_or_not_ready_without_post(self):
        self.file_entries = [{"path": "models/part.gcode", "size": 1}]
        for state in ("printing", "paused", "error"):
            self.calls.clear()
            self.requests.clear()
            self.state = state
            response = self.client.post(
                "/mobile/api/printer/start",
                headers=self.auth,
                json={"filename": "models/part.gcode"},
            )
            self.assertEqual(response.status_code, 409, state)
            self.assertEqual(self._post_calls(), [])

        self.calls.clear()
        self.requests.clear()
        self.state = "standby"
        self.ready = "shutdown"
        response = self.client.post(
            "/mobile/api/printer/start",
            headers=self.auth,
            json={"filename": "models/part.gcode"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self._post_calls(), [])
        self.ready = "ready"

    def test_shutdown_blocks_commands(self):
        self.ready = "shutdown"
        self.assertEqual(
            self.client.post("/mobile/api/printer/pause", headers=self.auth).status_code, 409
        )
        self.assertFalse(any(method == "POST" for method, path in self.calls))

    def test_pause_only_when_printing(self):
        self.assertEqual(
            self.client.post("/mobile/api/printer/pause", headers=self.auth).status_code, 200
        )
        self.assertIn(("POST", "/printer/print/pause"), self.calls)
        self.state = "standby"
        self.assertEqual(
            self.client.post("/mobile/api/printer/resume", headers=self.auth).status_code, 409
        )

    def test_camera_auth_size_stop_and_expiration(self):
        upload = dict(self.auth, **{"Content-Type": "image/jpeg"})
        view = {"X-KlipperLearn-Viewer": self.viewer}
        route = "/mobile/api/live/"
        self.assertEqual(
            self.client.put(route + "frame", content=b"x", headers=upload).status_code, 422
        )
        self.assertEqual(
            self.client.put(
                route + "frame", content=b"x" * (1024 * 1024 + 1), headers=upload
            ).status_code,
            413,
        )
        jpeg = b"\xff\xd8test\xff\xd9"
        self.assertEqual(
            self.client.put(route + "frame", content=jpeg, headers=upload).status_code, 200
        )
        self.assertEqual(self.client.get(route + "snapshot").status_code, 401)
        self.assertEqual(self.client.get(route + "snapshot", headers=view).content, jpeg)
        with patch("klipperlearn.companion.time.monotonic", return_value=1e20):
            stale = self.client.get(route + "snapshot", headers=view)
            self.assertEqual(stale.status_code, 503)
        self.client.delete(route + "frame", headers=self.auth)
        self.assertEqual(self.client.get(route + "snapshot", headers=view).status_code, 503)

    def test_create_app_companion_and_static_routes(self):
        token = "test-token-not-real"
        with tempfile.TemporaryDirectory() as directory:
            app = create_app(Path(directory) / "sessions", Path(directory) / "inbox", token)
            client = TestClient(app)

            before = client.get("/health").json()
            self.assertEqual(before["mode"], "local_evidence_only")
            self.assertFalse(before["printer_control"])
            self.assertFalse(before["camera_live_enabled"])
            self.assertTrue(before["mobile_upload_enabled"])
            self.assertNotIn(token, json.dumps(before))

            viewer = install_companion(
                app,
                token,
                transport=httpx.MockTransport(self._respond),
            )

            status = client.get("/mobile/api/printer/status", headers=self.auth)
            self.assertEqual(status.status_code, 200)
            self.assertIn(("GET", "/printer/objects/query"), self.calls)
            self.assertEqual(
                client.get(
                    "/mobile/api/live/snapshot",
                    headers={"X-KlipperLearn-Viewer": viewer},
                ).status_code,
                503,
            )
            self.assertEqual(client.get("/mobile/").status_code, 200)
            self.assertEqual(app.routes[-1].name, "mobile")

            after = client.get("/health").json()
            self.assertEqual(after["mode"], "local_companion")
            self.assertTrue(after["printer_control"])
            self.assertTrue(after["camera_live_enabled"])
            self.assertTrue(after["mobile_upload_enabled"])
            self.assertNotIn(token, json.dumps(after))
            self.assertNotIn(viewer, json.dumps(after))

    def _post_calls(self):
        return [(method, path) for method, path in self.calls if method == "POST"]

    def _respond(self, request):
        self.calls.append((request.method, request.url.path))
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, request.url.query.decode(), body))
        if request.url.path == "/server/files/list":
            return httpx.Response(200, json={"result": self.file_entries})
        if request.url.path == "/printer/objects/list":
            return httpx.Response(200, json={"result": {"objects": self.objects}})
        webhooks = {"state": self.ready}
        if self.webhooks_ready is not None:
            webhooks["ready"] = self.webhooks_ready
        return httpx.Response(
            200,
            json={
                "result": {
                    "status": {
                        "configfile": {"settings": self.config},
                        "webhooks": webhooks,
                        "print_stats": {"state": self.state},
                        "extruder": self.extruder_status,
                    }
                }
            },
        )
