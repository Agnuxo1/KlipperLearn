"""Contract and persistence checks for the independent photo-pair API."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from klipperlearn.experiment_api import install_experiment_api
from klipperlearn.photo_pair import install_photo_pair


TOKEN = "photo-pair-test-key"
PHOTO_PAIRS = "/mobile/api/photo-pairs"
EXPERIMENTS = "/mobile/api/experiments"
JPEG = b"\xff\xd8photo-pair-test\xff\xd9"


class PhotoPairAPITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "experiments"
        self.auth = {"X-KlipperLearn-Token": TOKEN}
        self.client = self._make_client()

    def _make_client(self):
        app = FastAPI()
        install_experiment_api(app, TOKEN, self.root)
        install_photo_pair(app, TOKEN, self.root)
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def _create_trial(self):
        response = self.client.post(
            EXPERIMENTS,
            headers=self.auth,
            json={
                "context": {
                    "printer_id": "samsung-test-printer",
                    "model_sha256": "a" * 64,
                    "material": "PLA",
                    "nozzle_mm": 0.4,
                    "session_id": "photo-pair-session",
                },
                "parameters": {"print_speed_mm_s": 45, "layer_height_mm": 0.2},
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["result"]

    def _enqueue(self):
        trial = self._create_trial()
        response = self.client.post(PHOTO_PAIRS, headers=self.auth, json={"trial_id": trial["id"]})
        self.assertEqual(response.status_code, 202, response.text)
        return trial, response.json()["result"]

    def _claim(self):
        trial, queued = self._enqueue()
        response = self.client.get(PHOTO_PAIRS + "/next", headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        claimed = response.json()["result"]
        self.assertEqual(claimed["id"], queued["id"])
        self.assertEqual(claimed["status"], "running")
        return trial, claimed

    def test_authentication_happens_before_body_or_storage(self):
        for method, url in (
            ("POST", PHOTO_PAIRS),
            ("GET", PHOTO_PAIRS + "/next"),
            ("GET", PHOTO_PAIRS + "/" + "0" * 8 + "-0000-0000-0000-000000000000"),
            ("POST", PHOTO_PAIRS + "/" + "0" * 8 + "-0000-0000-0000-000000000000/complete"),
        ):
            with self.subTest(method=method, url=url):
                response = self.client.request(method, url, content=b"not json")
                self.assertEqual(response.status_code, 401, response.text)
                self.assertEqual(response.json(), {"detail": "Unauthorized"})
        self.assertFalse(self.root.exists())

    def test_duplicate_token_header_is_rejected(self):
        response = self.client.get(
            PHOTO_PAIRS + "/next",
            headers=[("X-KlipperLearn-Token", TOKEN), ("X-KlipperLearn-Token", TOKEN)],
        )
        self.assertEqual(response.status_code, 401, response.text)
        self.assertFalse(self.root.exists())

    def test_queue_and_claim_have_stable_light_contract(self):
        _, queued = self._enqueue()
        self.assertEqual(queued["status"], "pending")
        self.assertEqual(queued["light_modes"], ["torch-off", "torch-on"])
        self.assertEqual(
            queued["photo_names"], [queued["id"] + "-torch-off.jpg", queued["id"] + "-torch-on.jpg"]
        )
        self.assertEqual([item["mode"] for item in queued["photos"]], ["torch-off", "torch-on"])
        self.assertEqual(
            self.client.post(
                PHOTO_PAIRS, headers=self.auth, json={"trial_id": queued["trial_id"]}
            ).status_code,
            409,
        )

        response = self.client.get(PHOTO_PAIRS + "/next", headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        claimed = response.json()["result"]
        self.assertEqual(claimed["status"], "running")
        self.assertIsNone(
            self.client.get(PHOTO_PAIRS + "/next", headers=self.auth).json()["result"]
        )
        self.assertEqual(
            self.client.get(PHOTO_PAIRS + "/" + claimed["id"], headers=self.auth).json()["result"][
                "status"
            ],
            "running",
        )

    def test_completion_requires_both_jpegs_and_survives_restart(self):
        trial, job = self._claim()
        complete_url = PHOTO_PAIRS + "/" + job["id"] + "/complete"
        self.assertEqual(
            self.client.post(complete_url, headers=self.auth, json={}).status_code, 409
        )

        for mode in ("torch-off", "torch-on"):
            filename = job["id"] + "-" + mode + ".jpg"
            response = self.client.put(
                EXPERIMENTS + "/" + trial["id"] + "/photos",
                headers={
                    **self.auth,
                    "Content-Type": "image/jpeg",
                    "X-KlipperLearn-Filename": filename,
                },
                content=JPEG,
            )
            self.assertEqual(response.status_code, 200, response.text)

        response = self.client.post(complete_url, headers=self.auth, json={})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        self.assertEqual(result["status"], "complete")
        self.assertEqual([photo["mode"] for photo in result["photos"]], ["torch-off", "torch-on"])
        self.assertTrue(all(photo["persisted"] for photo in result["photos"]))

        restarted = self._make_client()
        persisted = restarted.get(complete_url.removesuffix("/complete"), headers=self.auth)
        self.assertEqual(persisted.status_code, 200, persisted.text)
        self.assertEqual(persisted.json()["result"]["status"], "complete")

    def test_error_completion_sanitizes_token_and_is_terminal(self):
        _, job = self._claim()
        url = PHOTO_PAIRS + "/" + job["id"] + "/complete"
        response = self.client.post(url, headers=self.auth, json={"error": "fallo " + TOKEN})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["result"]
        self.assertEqual(result["status"], "error")
        self.assertNotIn(TOKEN, result["error"])
        self.assertEqual(self.client.post(url, headers=self.auth, json={}).status_code, 409)

    def test_expired_job_is_not_claimable_or_completable(self):
        trial = self._create_trial()
        clock = [1000.0]
        with patch("klipperlearn.photo_pair._now_epoch", side_effect=lambda: clock[0]):
            response = self.client.post(
                PHOTO_PAIRS, headers=self.auth, json={"trial_id": trial["id"]}
            )
            self.assertEqual(response.status_code, 202, response.text)
            job = response.json()["result"]
            clock[0] += 121
            expired = self.client.get(PHOTO_PAIRS + "/" + job["id"], headers=self.auth)
        self.assertEqual(expired.status_code, 200, expired.text)
        self.assertEqual(expired.json()["result"]["status"], "expired")
        self.assertIsNone(
            self.client.get(PHOTO_PAIRS + "/next", headers=self.auth).json()["result"]
        )

    def test_payload_and_identifiers_are_strict(self):
        self.assertEqual(self.client.post(PHOTO_PAIRS, headers=self.auth, json={}).status_code, 422)
        self.assertEqual(
            self.client.post(
                PHOTO_PAIRS,
                headers=self.auth,
                json={"trial_id": "a" * 32, "extra": True},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                PHOTO_PAIRS, headers=self.auth, json={"trial_id": "not-an-id"}
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(PHOTO_PAIRS + "/%2e%2e%5cprivate", headers=self.auth).status_code, 404
        )


if __name__ == "__main__":
    unittest.main()
