"""Exercise optimizer API authentication and pure profile generation."""

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from klipperlearn.optimizer_api import install_optimizer_api
from test_slicer_optimizer import session_fixture

TOKEN = "test-optimizer-token-not-real"
AUTH = {"X-KlipperLearn-Token": TOKEN}


def client():
    app = FastAPI()
    install_optimizer_api(app, TOKEN)
    return TestClient(app)


def test_unauthenticated_requests_cannot_inspect_or_scan():
    with client() as c, patch("klipperlearn.optimizer_api.discover_printers") as scan:
        for path in ("review", "profiles", "advisor-request", "check-proposal", "discover"):
            assert c.post("/mobile/api/optimizer/" + path, json={}).status_code == 401
        scan.assert_not_called()


def test_profile_generation_and_advisor_request_are_data_only():
    with client() as c:
        session = session_fixture()
        r = c.post("/mobile/api/optimizer/profiles", headers=AUTH, json=session)
        assert r.status_code == 200 and len(r.json()["result"]["files"]) == 6
        assert r.json()["result"]["printer_commands"] is False
        assert r.headers["cache-control"] == "no-store"
        r = c.post("/mobile/api/optimizer/advisor-request", headers=AUTH, json=session)
        assert r.status_code == 200 and not r.json()["result"]["images_attached"]
        assert "machine_start_gcode" not in r.text


def test_invalid_duplicate_or_private_fields_are_rejected():
    with client() as c:
        r = c.post(
            "/mobile/api/optimizer/review",
            headers={**AUTH, "Content-Type": "application/json"},
            content='{"schema":"a","schema":"b"}',
        )
        assert r.status_code == 422
        session = session_fixture()
        session["base_process"]["api_key"] = "fixture-sensitive-value"
        r = c.post("/mobile/api/optimizer/profiles", headers=AUTH, json=session)
        assert r.status_code == 422 and "fixture-sensitive-value" not in r.text
        assert c.post("/mobile/api/optimizer/review", headers=AUTH, json={}).status_code == 422


def test_network_scanning_is_disabled_without_server_allowlist():
    with client() as c:
        r = c.post(
            "/mobile/api/optimizer/discover",
            headers=AUTH,
            json={"cidr": "192.168.1.0/24", "confirmed": True},
        )
        assert r.status_code == 422
        r = c.get("/mobile/api/optimizer/catalog", headers=AUTH)
        assert not r.json()["result"]["discovery_enabled"]
