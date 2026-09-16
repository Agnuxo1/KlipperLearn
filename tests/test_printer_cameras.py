import json
from tempfile import TemporaryDirectory

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from klipperlearn.companion import install_companion
from klipperlearn.experiment_store import ExperimentStore

TOKEN = "test-token"
AUTH = {"X-KlipperLearn-Token": TOKEN}
JPEG = b"\xff\xd8fixture\xff\xd9"


def test_multiview_auth_ssrf_staleness_and_durable_partial_results():
    calls = []

    def respond(request):
        calls.append(str(request.url))
        if request.url.path == "/server/webcams/list":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "webcams": [
                            {
                                "uid": "usb-camera",
                                "name": "USB",
                                "snapshot_url": "/webcam/snapshot",
                            },
                            {"uid": "phone", "name": "Phone", "snapshot_url": "/samsung/snapshot"},
                            {"uid": "evil", "snapshot_url": "http://evil.example/snapshot"},
                            {"uid": "redirect", "snapshot_url": "/redirect"},
                        ]
                    }
                },
            )
        if request.url.path == "/redirect":
            return httpx.Response(302, headers={"Location": "http://evil.example"})
        return httpx.Response(
            200,
            content=JPEG,
            headers={
                "Content-Type": "image/jpeg",
                "X-KlipperLearn-Camera": "last-frame"
                if "/samsung/" in request.url.path
                else "live",
            },
        )

    with TemporaryDirectory() as root:
        app = FastAPI()
        install_companion(app, TOKEN, transport=httpx.MockTransport(respond), experiments_root=root)
        client = TestClient(app)
        assert client.get("/mobile/api/printer/cameras").status_code == 401
        assert calls == []
        listed = client.get("/mobile/api/printer/cameras", headers=AUTH).json()["result"]
        assert [v["id"] for v in listed] == ["usb-camera", "phone", "redirect"]
        assert all("url" not in v for v in listed)
        assert (
            client.get("/mobile/api/printer/cameras/usb-camera/snapshot", headers=AUTH).content
            == JPEG
        )
        assert (
            client.get("/mobile/api/printer/cameras/phone/snapshot", headers=AUTH).status_code
            == 503
        )
        assert (
            client.get("/mobile/api/printer/cameras/redirect/snapshot", headers=AUTH).status_code
            == 503
        )
        assert all("evil.example" not in call for call in calls)
        store = ExperimentStore(root)
        trial = store.create_trial(
            {
                "printer_id": "test",
                "session_id": "test",
                "model_sha256": "a" * 64,
                "material": "PLA",
                "nozzle_mm": 0.4,
            },
            {},
            None,
        )
        result = client.post(f"/mobile/api/experiments/{trial['id']}/capture-views", headers=AUTH)
        assert result.status_code == 200, result.text
        views = result.json()["result"]["views"]
        assert [v["status"] for v in views] == ["saved", "unavailable", "unavailable"]
        assert len(ExperimentStore(root).get_trial(trial["id"])["photos"]) == 1
        manifests = list((store.root / "assets" / "multiview" / trial["id"]).glob("*.json"))
        assert len(manifests) == 1
        assert json.loads(manifests[0].read_text(encoding="utf-8"))["views"] == views


def test_camera_sessions_cannot_overwrite_or_stop_other_emitters():
    with TemporaryDirectory() as root:
        app = FastAPI()
        viewer = install_companion(app, TOKEN, experiments_root=root)
        client = TestClient(app)
        first = {
            **AUTH,
            "Content-Type": "image/jpeg",
            "X-KlipperLearn-Camera-Session": "camera_session_first",
        }
        second = {**first, "X-KlipperLearn-Camera-Session": "camera_session_second"}
        assert client.put("/mobile/api/live/frame", headers=first, content=JPEG).status_code == 200
        assert client.put("/mobile/api/live/frame", headers=second, content=JPEG).status_code == 409
        assert client.delete("/mobile/api/live/frame", headers=second).status_code == 409
        assert client.delete("/mobile/api/live/frame", headers=AUTH).status_code == 409
        assert (
            client.get(
                "/mobile/api/live/snapshot", headers={"X-KlipperLearn-Viewer": viewer}
            ).headers["x-klipperlearn-camera"]
            == "live"
        )
        assert client.delete("/mobile/api/live/frame", headers=first).status_code == 200
        assert client.put("/mobile/api/live/frame", headers=second, content=JPEG).status_code == 200


def test_recent_history_is_descending_and_paginates_without_losing_old_trials():
    with TemporaryDirectory() as root:
        app = FastAPI()
        install_companion(app, TOKEN, experiments_root=root)
        store = ExperimentStore(root)
        context = {
            "printer_id": "test",
            "session_id": "test",
            "model_sha256": "a" * 64,
            "material": "PLA",
            "nozzle_mm": 0.4,
        }
        first, second = (store.create_trial(context, {}, None) for _ in range(2))
        client = TestClient(app)
        assert client.get("/mobile/api/experiments/recent").status_code == 401
        page = client.get("/mobile/api/experiments/recent?limit=1", headers=AUTH).json()["result"]
        assert page[0]["id"] == second["id"]
        page = client.get("/mobile/api/experiments/recent?limit=1&offset=1", headers=AUTH).json()[
            "result"
        ]
        assert page[0]["id"] == first["id"]
        assert store.list_trials(1)[0]["id"] == first["id"]
