"""LAN bootstrap is explicit, same-origin, subnet-scoped and never moves a printer."""

from tempfile import TemporaryDirectory

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from klipperlearn.companion import install_companion

ORIGIN = "https://192.168.50.12:8765"
TOKEN = "test_local_token_not_real_1234567890"
HEADERS = {"Origin": ORIGIN, "X-KlipperLearn-Connect": "1", "Sec-Fetch-Site": "same-origin"}


def make_client(root, enabled=True, peer="192.168.50.25"):
    app = FastAPI()
    install_companion(
        app,
        TOKEN,
        experiments_root=root,
        local_connect_origin=ORIGIN if enabled else None,
        local_connect_networks=("192.168.50.0/24",) if enabled else (),
    )
    return TestClient(app, base_url=ORIGIN, client=(peer, 50000))


def test_valid_same_origin_connect_does_not_need_an_old_token():
    with TemporaryDirectory() as root, make_client(root) as client:
        response = client.post("/mobile/api/connect", headers=HEADERS)
        assert response.status_code == 200
        assert response.json()["result"]["token"] == TOKEN
        assert response.headers["cache-control"] == "no-store"
        # Authentication remains compulsory on printer controls.
        assert client.post("/mobile/api/printer/home").status_code == 401


@pytest.mark.parametrize(
    "override",
    [
        {"Origin": "https://evil.example"},
        {"Origin": ""},
        {"Host": "evil.example"},
        {"X-KlipperLearn-Connect": ""},
        {"Sec-Fetch-Site": "cross-site"},
    ],
)
def test_cross_site_bootstrap_is_rejected(override):
    with TemporaryDirectory() as root, make_client(root) as client:
        response = client.post("/mobile/api/connect", headers={**HEADERS, **override})
        assert response.status_code == 403
        assert TOKEN not in response.text


@pytest.mark.parametrize("enabled,peer", [(False, "192.168.50.25"), (True, "203.0.113.7")])
def test_bootstrap_disabled_by_default_and_denied_outside_lan(enabled, peer):
    with TemporaryDirectory() as root, make_client(root, enabled, peer) as client:
        response = client.post("/mobile/api/connect", headers=HEADERS)
        assert response.status_code == 403
        assert TOKEN not in response.text
