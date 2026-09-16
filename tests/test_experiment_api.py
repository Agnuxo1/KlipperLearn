"""HTTP boundary and real-store integration checks for local experiments."""

import asyncio
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from klipperlearn.experiment_api import install_experiment_api


BASE = "/mobile/api/experiments"
TOKEN = "local-experiment-test-key"


class ExperimentAPITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "experiments"
        self.auth = {"X-KlipperLearn-Token": TOKEN}
        self.client = self.make_client()
        self.payload = {
            "context": {
                "printer_id": "printer-one",
                "model_sha256": "a" * 64,
                "material": "PLA",
                "nozzle_mm": 0.4,
                "session_id": "session-one",
            },
            "parameters": {"print_speed_mm_s": 45, "layer_height_mm": 0.2},
        }

    def make_client(self):
        app = FastAPI()
        install_experiment_api(app, TOKEN, self.root)
        client = TestClient(app)
        self.addCleanup(client.close)
        return client

    def create(self, **extra):
        payload = copy.deepcopy(self.payload)
        payload.update(extra)
        response = self.client.post(BASE, headers=self.auth, json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        return response.json()["result"]

    def test_authentication_all_routes_before_body_or_store(self):
        for method, url in (
            ("GET", BASE),
            ("POST", BASE),
            ("GET", BASE + "/export/jsonl"),
            ("GET", BASE + "/valid-id"),
            ("POST", BASE + "/valid-id/ratings"),
            ("PUT", BASE + "/valid-id/photos"),
        ):
            for headers in ({}, {"X-KlipperLearn-Token": "wrong"}):
                with self.subTest(method=method, url=url, headers=headers):
                    response = self.client.request(
                        method, url, headers=headers, content=b"not json"
                    )
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.json(), {"detail": "Unauthorized"})
        self.assertFalse(self.root.exists(), "unauthenticated calls must not initialize storage")

    def test_duplicate_auth_header_rejected(self):
        response = self.client.get(
            BASE, headers=[("X-KlipperLearn-Token", TOKEN), ("X-KlipperLearn-Token", TOKEN)]
        )
        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.root.exists())

    def test_strict_json_and_sanitized_validation(self):
        malformed = [
            b"",
            b"{",
            b"null",
            b"[]",
            b"true",
            b"{} trailing",
            b'{"context":NaN}',
            b'{"context":Infinity}',
            b'{"context":-Infinity}',
            b'{"context":1e999}',
            b'{"context":1,"context":2}',
            b'{"context":{"key":1,"key":2}}',
            b'{"context":"\\ud800"}',
            b'{"context":"\xff"}',
            b'{"context":' + b"[" * 70 + b"0" + b"]" * 70 + b"}",
        ]
        for raw in malformed:
            with self.subTest(raw=raw[:40]):
                response = self.client.post(
                    BASE, headers={**self.auth, "Content-Type": "application/json"}, content=raw
                )
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json(), {"detail": "The experiment data are invalid"})
        self.assertFalse(self.root.exists())

    def test_body_size_content_type_and_stream_limit(self):
        headers = {**self.auth, "Content-Type": "application/json"}
        self.assertEqual(
            self.client.post(BASE, headers=headers, content=b" " * (256 * 1024 + 1)).status_code,
            413,
        )
        # Do not trust a lying Content-Length or require one for streamed bodies.
        self.assertEqual(
            self.client.post(
                BASE, headers={**headers, "Content-Length": "1"}, content=b" " * (256 * 1024 + 1)
            ).status_code,
            413,
        )
        self.assertEqual(
            self.client.post(
                BASE, headers=headers, content=iter([b" " * (128 * 1024), b" " * (128 * 1024 + 1)])
            ).status_code,
            413,
        )
        self.assertEqual(self.client.post(BASE, headers=self.auth, content=b"{}").status_code, 415)
        self.assertEqual(
            self.client.post(
                BASE, headers={**headers, "Content-Length": "-1"}, content=b"{}"
            ).status_code,
            422,
        )
        self.assertFalse(self.root.exists())

    def test_context_and_create_validation(self):
        invalid = []
        for key in self.payload["context"]:
            candidate = copy.deepcopy(self.payload)
            del candidate["context"][key]
            invalid.append(candidate)
        for key, value in (
            ("printer_id", ""),
            ("session_id", "../\nprivate"),
            ("material", 42),
            ("model_sha256", "../outside"),
            ("model_sha256", "z" * 64),
            ("nozzle_mm", True),
            ("nozzle_mm", "0.4"),
            ("nozzle_mm", 0),
        ):
            candidate = copy.deepcopy(self.payload)
            candidate["context"][key] = value
            invalid.append(candidate)
        for extra in (
            {"objective_score": True},
            {"objective_score": "50"},
            {"objective_score": -1},
            {"objective_score": 101},
            {"evidence": []},
            {"parameters": []},
            {"validated": True},
            {"training_eligible": True},
            {"provenance": "validated"},
        ):
            invalid.append({**self.payload, **extra})
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertEqual(
                    self.client.post(BASE, headers=self.auth, json=payload).status_code, 422
                )
        self.assertFalse(self.root.exists())

    def test_ratings_require_exact_three_numeric_dimensions(self):
        invalid = [
            {},
            {"speed": 1, "surface": 2},
            {"speed": 1, "surface": 2, "geometry": 3, "extra": 1},
            {"speed": True, "surface": 2, "geometry": 3},
            {"speed": "1", "surface": 2, "geometry": 3},
            {"speed": 1.5, "surface": 2, "geometry": 3},
            {"speed": 1.0, "surface": 2, "geometry": 3},
            {"speed": -1, "surface": 2, "geometry": 3},
            {"speed": 6, "surface": 2, "geometry": 3},
        ]
        for ratings in invalid:
            with self.subTest(ratings=ratings):
                response = self.client.post(
                    BASE + "/" + "a" * 32 + "/ratings", headers=self.auth, json={"ratings": ratings}
                )
                self.assertEqual(response.status_code, 422)
        self.assertEqual(
            self.client.post(
                BASE + "/" + "a" * 32 + "/ratings",
                headers=self.auth,
                json={"ratings": {"speed": 1, "surface": 2, "geometry": 3}, "comment": []},
            ).status_code,
            422,
        )
        self.assertFalse(self.root.exists())

    def test_identifier_traversal_and_pagination_rejected(self):
        for identifier in (
            "%2e%2e%5cprivate",
            "C%3Aprivate",
            "%2Foutside",
            "bad%00id",
            "%252e%252e",
            "bad.id",
            "a" * 129,
            "valid-id",
            "A" * 32,
        ):
            for suffix, method in (("", "GET"), ("/ratings", "POST")):
                response = self.client.request(
                    method, BASE + "/" + identifier + suffix, headers=self.auth
                )
                self.assertEqual(response.status_code, 404, response.text)
                self.assertNotIn(str(self.root), response.text)
        for query in (
            "limit=0",
            "limit=201",
            "offset=-1",
            "offset=1000001",
            "limit=NaN",
            "limit=1&limit=2",
            "token=private",
        ):
            response = self.client.get(BASE + "?" + query, headers=self.auth)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn("private", response.text)
        self.assertFalse(self.root.exists())

    def test_restart_persists_records_and_manual_provenance(self):
        created = self.create(
            objective_score=25,
            evidence={"note": "observación manual", "validated": True, "training_eligible": True},
        )
        self.assertEqual(created["context"], self.payload["context"])
        self.assertEqual(created["parameters"], self.payload["parameters"])
        self.assertEqual(created["evidence"]["provenance"], "user_supplied")
        self.assertIs(created["evidence"]["validated"], False)
        self.assertIs(created["evidence"]["training_eligible"], False)
        restarted = self.make_client()
        response = restarted.get(BASE + "/" + created["id"], headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["result"], created)
        exported = restarted.get(BASE + "/export/jsonl", headers=self.auth)
        self.assertEqual(exported.status_code, 200)
        self.assertIn("application/x-ndjson", exported.headers["content-type"])
        self.assertEqual(exported.headers["cache-control"], "no-store")
        self.assertEqual([json.loads(line) for line in exported.text.splitlines()], [created])
        self.assertNotIn(TOKEN, exported.text)
        listed = restarted.get(BASE + "?limit=1&offset=0", headers=self.auth)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["result"], [created])

    def test_missing_record(self):
        response = self.client.get(BASE + "/" + "a" * 32, headers=self.auth)
        self.assertEqual(response.status_code, 404, response.text)

    def test_manual_photo_upload_is_authenticated_bounded_and_persistent(self):
        created = self.create()
        jpeg = b"\xff\xd8best-manual-view\xff\xd9"
        response = self.client.put(
            BASE + "/" + created["id"] + "/photos",
            headers={
                **self.auth,
                "Content-Type": "image/jpeg",
                "X-KlipperLearn-Filename": "pieza.jpg",
            },
            content=jpeg,
        )
        self.assertEqual(response.status_code, 200, response.text)
        photo = response.json()["result"]["photos"][0]
        self.assertEqual(photo["original_name"], "pieza.jpg")
        self.assertEqual((self.root / photo["relative_path"]).read_bytes(), jpeg)
        loaded = self.make_client().get(BASE + "/" + created["id"], headers=self.auth)
        self.assertEqual(loaded.json()["result"]["photos"], [photo])

        self.assertEqual(
            self.client.put(
                BASE + "/" + created["id"] + "/photos",
                headers={**self.auth, "Content-Type": "text/plain"},
                content=jpeg,
            ).status_code,
            415,
        )
        self.assertEqual(
            self.client.put(
                BASE + "/" + created["id"] + "/photos",
                headers={**self.auth, "Content-Type": "image/jpeg"},
                content=b"bad",
            ).status_code,
            422,
        )
        response = self.client.post(
            BASE + "/" + "a" * 32 + "/ratings",
            headers=self.auth,
            json={"ratings": {"speed": 1, "surface": 2, "geometry": 3}},
        )
        self.assertEqual(response.status_code, 404, response.text)

    def test_scoring_and_pending(self):
        created = self.create(objective_score=90)
        self.assertEqual(created["status"], "pending")
        self.assertIsNone(created["human_score"])
        self.assertIsNone(created["score"])
        rated = self.client.post(
            BASE + "/" + created["id"] + "/ratings",
            headers=self.auth,
            json={
                "ratings": {"speed": 1, "surface": 2, "geometry": 3},
                "comment": "revisión manual",
            },
        )
        self.assertEqual(rated.status_code, 200, rated.text)
        result = rated.json()["result"]
        self.assertEqual(result["objective_score"], 90)
        self.assertEqual(result["human_score"], 40)
        self.assertAlmostEqual(result["score"], 60)  # 0.4 * 90 + 0.6 * 40
        self.assertEqual(result["raw_scores"], {"objective": 90, "human": 40, "score": 60})
        self.assertEqual(result["weights"], {"objective": 0.4, "human": 0.6, "version": "40-60-v1"})
        self.assertEqual(result["status"], "scored")
        self.assertEqual(result["revisions"][0]["comment"], "revisión manual")
        self.assertEqual(
            self.make_client().get(BASE + "/" + created["id"], headers=self.auth).json()["result"],
            result,
        )
        second_rating = self.client.post(
            BASE + "/" + created["id"] + "/ratings",
            headers=self.auth,
            json={
                "ratings": {"speed": 5, "surface": 5, "geometry": 5},
                "comment": "segunda revisión",
            },
        )
        self.assertEqual(second_rating.status_code, 200, second_rating.text)
        revised = second_rating.json()["result"]
        self.assertEqual(revised["rating_revision"], 2)
        self.assertEqual(len(revised["revisions"]), 2)
        self.assertEqual(revised["revisions"][0], result["revisions"][0])
        self.assertEqual(revised["revisions"][1]["comment"], "segunda revisión")
        self.assertAlmostEqual(revised["score"], 96)
        self.assertEqual(
            self.make_client().get(BASE + "/" + created["id"], headers=self.auth).json()["result"],
            revised,
        )
        pending = self.create()
        self.assertIsNone(pending["objective_score"])
        self.assertIsNone(pending["human_score"])
        self.assertIsNone(pending["score"])
        self.assertEqual(pending["status"], "pending")
        human_only = self.client.post(
            BASE + "/" + pending["id"] + "/ratings",
            headers=self.auth,
            json={"ratings": {"speed": 5, "surface": 5, "geometry": 5}},
        )
        self.assertEqual(human_only.status_code, 200, human_only.text)
        self.assertEqual(human_only.json()["result"]["human_score"], 100)
        self.assertIsNone(human_only.json()["result"]["score"])
        self.assertEqual(human_only.json()["result"]["status"], "pending")
        zero = self.create(objective_score=0)
        rated_zero = self.client.post(
            BASE + "/" + zero["id"] + "/ratings",
            headers=self.auth,
            json={"ratings": {"speed": 0, "surface": 0, "geometry": 0}},
        )
        self.assertEqual(rated_zero.status_code, 200, rated_zero.text)
        self.assertEqual(rated_zero.json()["result"]["human_score"], 0)
        self.assertEqual(rated_zero.json()["result"]["score"], 0)
        self.assertEqual(rated_zero.json()["result"]["status"], "scored")

    def test_default_list_and_pagination(self):
        response = self.client.get(BASE, headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"result": []})
        first = self.create(objective_score=0)
        second = self.create(objective_score=100)
        self.assertEqual(self.client.get(BASE, headers=self.auth).json()["result"], [first, second])
        self.assertEqual(
            self.client.get(BASE + "?limit=1&offset=1", headers=self.auth).json()["result"],
            [second],
        )

    def test_store_errors_are_sanitized_and_work_is_off_loop(self):
        from klipperlearn.experiment_store import ExperimentStore

        original = ExperimentStore.list_trials
        checked = []

        def checked_list(instance, *args, **kwargs):
            checked.append(threading.get_ident())
            with self.assertRaises(RuntimeError):
                asyncio.get_running_loop()
            return original(instance, *args, **kwargs)

        with patch.object(ExperimentStore, "list_trials", checked_list):
            response = self.client.get(BASE, headers=self.auth)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(checked)
        with patch.object(
            ExperimentStore, "list_trials", side_effect=RuntimeError("private /path " + TOKEN)
        ):
            response = self.client.get(BASE, headers=self.auth)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(TOKEN, response.text)
        self.assertNotIn("/path", response.text)


if __name__ == "__main__":
    unittest.main()
