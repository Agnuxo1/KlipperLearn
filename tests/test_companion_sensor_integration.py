import copy
import json
from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from klipperlearn.companion import install_companion
from klipperlearn.trial_telemetry import build_trial_telemetry


TOKEN = "companion-sensor-integration-token"


def _permissions():
    return {
        source: {"requested": True, "granted": True, "state": "granted"}
        for source in ("motion", "orientation", "audio")
    }


def _snapshot(trial_id="trial-001"):
    return build_trial_telemetry(
        trial_id=trial_id,
        started_at_utc="2026-09-09T10:00:00Z",
        ended_at_utc="2026-09-09T10:00:01Z",
        permissions=_permissions(),
        motion=[
            {
                "t_ms": 0,
                "timestamp_utc": "2026-09-09T10:00:00Z",
                "linear_acceleration_mps2": {"x": 1.0, "y": 2.0, "z": 3.0},
            }
        ],
        orientation=[
            {
                "t_ms": 0,
                "timestamp_utc": "2026-09-09T10:00:00Z",
                "alpha_deg": 10.0,
            }
        ],
        audio_features=[
            {
                "t_ms": 0,
                "timestamp_utc": "2026-09-09T10:00:00Z",
                "rms_dbfs": -32.0,
            }
        ],
    )


class CompanionSensorIntegrationTests(unittest.TestCase):
    def test_uploads_preserve_previous_evidence_and_retries_are_idempotent(self):
        first = _snapshot()
        second = copy.deepcopy(first)
        second["samples"]["motion"][0]["t_ms"] = 500
        for payload in (first, second, second):
            response = self.client.post(
                "/mobile/api/trial-telemetry", headers=self.auth, json=payload
            )
            self.assertEqual(response.status_code, 200, response.text)
        chunks = list((self.root / "assets/telemetry/trial-001.json.chunks").glob("*.json"))
        self.assertEqual(len(chunks), 2)
        self.assertEqual(
            sorted(json.loads(p.read_text())["samples"]["motion"][0]["t_ms"] for p in chunks),
            [0, 500],
        )
        result = self.client.get("/mobile/api/trial-telemetry/trial-001/summary", headers=self.auth)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(
            result.json()["result"]["counts"], {"motion": 2, "orientation": 1, "audio_features": 1}
        )

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "experiments"
        app = FastAPI()
        install_companion(app, TOKEN, experiments_root=self.root)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.auth = {"X-KlipperLearn-Token": TOKEN}

    def test_overflow_counters_are_preserved_and_validated(self):
        payload = _snapshot()
        payload["dropped_samples"] = {"motion": 14, "orientation": 2, "audio": 0}
        response = self.client.post("/mobile/api/trial-telemetry", headers=self.auth, json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        saved = json.loads((self.root / "assets/telemetry/trial-001.json").read_text())
        self.assertEqual(saved["dropped_samples"], payload["dropped_samples"])
        payload["dropped_samples"]["motion"] = -1
        response = self.client.post("/mobile/api/trial-telemetry", headers=self.auth, json=payload)
        self.assertEqual(response.status_code, 422)

    def test_sensor_routes_are_authenticated_before_body_or_storage(self):
        for method, url in (
            ("POST", "/mobile/api/trial-telemetry/active"),
            ("POST", "/mobile/api/trial-telemetry"),
            ("POST", "/mobile/api/trial-telemetry/trial-001/snapshot"),
            ("GET", "/mobile/api/trial-telemetry/active"),
            ("GET", "/mobile/api/trial-telemetry/trial-001/summary"),
        ):
            with self.subTest(method=method, url=url):
                response = self.client.request(method, url, content=b"not json")
                self.assertEqual(response.status_code, 401)
        self.assertFalse(self.root.exists())

    def test_active_snapshot_and_summary_persist_atomic_contract(self):
        active = self.client.post(
            "/mobile/api/trial-telemetry/active",
            headers=self.auth,
            json={"trial_id": "trial-001"},
        )
        self.assertEqual(active.status_code, 200, active.text)
        self.assertEqual(active.json()["result"], {"trial_id": "trial-001"})
        current = self.client.get(
            "/mobile/api/trial-telemetry/active",
            headers=self.auth,
        )
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json(), {"result": {"trial_id": "trial-001"}})
        self.assertEqual(
            json.loads((self.root / "trial-telemetry-active.json").read_text(encoding="utf-8")),
            {"trial_id": "trial-001"},
        )

        restarted_app = FastAPI()
        install_companion(restarted_app, TOKEN, experiments_root=self.root)
        restarted_client = TestClient(restarted_app)
        try:
            restarted = restarted_client.get(
                "/mobile/api/trial-telemetry/active",
                headers=self.auth,
            )
            self.assertEqual(restarted.status_code, 200, restarted.text)
            self.assertEqual(restarted.json(), {"result": {"trial_id": "trial-001"}})
        finally:
            restarted_client.close()

        response = self.client.post(
            "/mobile/api/trial-telemetry",
            headers=self.auth,
            json=_snapshot(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["result"]["counts"],
            {"motion": 1, "audio_features": 1, "orientation": 1},
        )

        stored = self.root / "assets" / "telemetry" / "trial-001.json"
        self.assertTrue(stored.is_file())
        self.assertEqual(json.loads(stored.read_text(encoding="utf-8"))["trial_id"], "trial-001")
        summary = self.client.get(
            "/mobile/api/trial-telemetry/trial-001/summary",
            headers=self.auth,
        )
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(
            summary.json()["result"]["counts"],
            {"motion": 1, "audio_features": 1, "orientation": 1},
        )

        cleared = self.client.post(
            "/mobile/api/trial-telemetry/active",
            headers=self.auth,
            json={"trial_id": None},
        )
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(
            json.loads((self.root / "trial-telemetry-active.json").read_text(encoding="utf-8")),
            {"trial_id": None},
        )
        self.assertEqual(
            self.client.get(
                "/mobile/api/trial-telemetry/active",
                headers=self.auth,
            ).json(),
            {"result": {"trial_id": None}},
        )
        self.assertEqual(list((self.root / "assets" / "telemetry").glob("*.tmp")), [])

    def test_frontend_snapshot_alias_requires_matching_trial_id(self):
        mismatch = self.client.post(
            "/mobile/api/trial-telemetry/trial-path/snapshot",
            headers=self.auth,
            json=_snapshot("trial-payload"),
        )
        self.assertEqual(mismatch.status_code, 422, mismatch.text)
        self.assertFalse((self.root / "assets" / "telemetry").exists())

        response = self.client.post(
            "/mobile/api/trial-telemetry/trial-path/snapshot",
            headers=self.auth,
            json=_snapshot("trial-path"),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json(),
            {
                "result": {
                    "trial_id": "trial-path",
                    "counts": {"motion": 1, "audio_features": 1, "orientation": 1},
                }
            },
        )
        summary = self.client.get(
            "/mobile/api/trial-telemetry/trial-path/summary",
            headers=self.auth,
        )
        self.assertEqual(summary.json()["result"], response.json()["result"])

    def test_snapshot_is_validated_and_photo_pair_is_installed_on_same_root(self):
        invalid = copy.deepcopy(_snapshot("trial-invalid"))
        invalid["samples"]["audio_features"][0]["waveform"] = [0.1, 0.2]
        response = self.client.post(
            "/mobile/api/trial-telemetry",
            headers=self.auth,
            json=invalid,
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse((self.root / "assets" / "telemetry" / "trial-invalid.json").exists())

        experiment = self.client.post(
            "/mobile/api/experiments",
            headers=self.auth,
            json={
                "context": {
                    "printer_id": "sensor-test-printer",
                    "model_sha256": "a" * 64,
                    "material": "PLA",
                    "nozzle_mm": 0.4,
                    "session_id": "sensor-test-session",
                },
                "parameters": {"layer_height_mm": 0.2},
            },
        )
        self.assertEqual(experiment.status_code, 201, experiment.text)
        trial_id = experiment.json()["result"]["id"]
        queued = self.client.post(
            "/mobile/api/photo-pairs",
            headers=self.auth,
            json={"trial_id": trial_id},
        )
        self.assertEqual(queued.status_code, 202, queued.text)
        self.assertEqual(queued.json()["result"]["trial_id"], trial_id)


if __name__ == "__main__":
    unittest.main()
