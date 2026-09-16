"""Host isolation and identity tests. No printer or network access."""

import asyncio
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from klipperlearn.companion import install_companion, _TrialTelemetryStore
from klipperlearn.learning_service import LearningService

TOKEN = "test-host-backend-token-not-a-credential"


@pytest.mark.parametrize("enabled", [False, True])
def test_restoration_requires_explicit_controller_enablement(tmp_path, enabled):
    service = LearningService(
        FastAPI(), TOKEN, "http://printer.test", tmp_path, _TrialTelemetryStore(tmp_path)
    )
    service.automatic_configured = enabled
    service.automatic.restore = AsyncMock()
    service.last_learning = time.monotonic()
    state = {"webhooks": {"state": "ready"}, "print_stats": {"state": "standby"}}

    async def exercise():
        transport = httpx.MockTransport(
            lambda r: httpx.Response(200, json={"result": {"status": state}})
        )
        async with httpx.AsyncClient(base_url="http://printer.test", transport=transport) as client:
            await service.tick(client)

    asyncio.run(exercise())
    assert service.automatic.restore.await_count == int(enabled)


@pytest.mark.parametrize("name", ["", "  ", "x\nname", "x" * 81, None])
def test_invalid_instance_name_is_rejected(tmp_path, name):
    with pytest.raises(ValueError, match="Instance name"):
        install_companion(FastAPI(), TOKEN, experiments_root=tmp_path, instance_name=name)


def test_instance_identity_and_unready_mcu_remain_distinct(tmp_path):
    app = FastAPI()

    def respond(request):
        assert request.method == "GET"
        return httpx.Response(
            200,
            json={
                "result": {
                    "status": {
                        "webhooks": {"state": "error", "state_message": "mcu: Unable to connect"},
                        "print_stats": {"state": "standby"},
                    }
                }
            },
        )

    install_companion(
        app,
        TOKEN,
        experiments_root=tmp_path,
        instance_name="Workshop printer",
        transport=httpx.MockTransport(respond),
    )
    with TestClient(app) as client:
        response = client.get("/mobile/api/printer/status", headers={"X-KlipperLearn-Token": TOKEN})
        assert response.status_code == 200
        assert response.json()["result"]["instance_name"] == "Workshop printer"
        assert response.json()["result"]["status"]["webhooks"]["state"] == "error"
        assert client.get("/mobile/api/printer/status").status_code == 401
