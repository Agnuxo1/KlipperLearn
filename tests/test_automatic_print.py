import asyncio

import httpx
import pytest
from fastapi import FastAPI

from klipperlearn.companion import _TrialTelemetryStore
from klipperlearn.learning_service import LearningService


def state(mode="standby"):
    return {
        "webhooks": {"state": "ready"},
        "print_stats": {"state": mode, "filename": ""},
        "extruder": {"pressure_advance": 0.02},
        "gcode_move": {"extrude_factor": 1.0},
        "toolhead": {"max_accel": 1500.0},
        "configfile": {"settings": {"printer": {"max_accel": 3000.0}}},
    }


def test_preparation_never_starts_print_and_verifies_uploaded_copy(tmp_path):
    service = LearningService(
        FastAPI(), "test", "http://printer", tmp_path, _TrialTelemetryStore(tmp_path)
    )
    manager = service.automatic
    files = {"part.gcode": b"M221 S100\nG1 X1 E1\nM104 S0\n"}
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, content=files[request.url.path.rsplit("/", 1)[-1]])
        assert request.url.path == "/server/files/upload"
        body = request.read()
        # Extract the one file from HTTPX's multipart fixture.
        filename = body.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
        filepart = body.split(b'filename="', 1)[1].split(b"\r\n\r\n", 1)[1]
        files[filename] = filepart.rsplit(b"\r\n--", 1)[0]
        return httpx.Response(200, json={"result": {"item": {"path": filename}}})

    async def exercise():
        async with httpx.AsyncClient(
            base_url="http://printer", transport=httpx.MockTransport(respond)
        ) as client:
            operation = await manager.prepare(client, "part.gcode", state())
            assert not operation["audit"]["changed"]
            assert files["part.gcode"] == b"M221 S100\nG1 X1 E1\nM104 S0\n"
            assert manager.pending()["phase"] == "prepared"
            with pytest.raises(ValueError, match="previous"):
                await manager.prepare(client, "part.gcode", state())

    asyncio.run(exercise())
    assert not any("/printer/" in path for _, path in calls)


def test_cancel_restore_is_exact_once_and_restart_verifies(tmp_path):
    service = LearningService(
        FastAPI(), "test", "http://printer", tmp_path, _TrialTelemetryStore(tmp_path)
    )
    manager = service.automatic
    operation = {
        "id": "fixture",
        "filename": "KL-Learn-fixture.gcode",
        "phase": "start_sent",
        "restore": {"extrusion_factor": 1},
        "audit": {
            "changed": True,
            "parameter": "flow_multiplier",
            "value": 1.005,
            "restore_commands": ["M221 S100"],
        },
    }
    manager.save(operation)
    current = state("cancelled")
    current["print_stats"]["filename"] = operation["filename"]
    current["gcode_move"]["extrude_factor"] = 1.005
    posts = []

    def respond(request):
        posts.append(request.read())
        return httpx.Response(200, json={"result": "ok"})

    async def exercise():
        async with httpx.AsyncClient(
            base_url="http://printer", transport=httpx.MockTransport(respond)
        ) as client:
            await manager.restore(client, current)
            assert manager.pending()["phase"] == "restore_sent"
            await manager.restore(client, current)
            assert len(posts) == 1
            restored = LearningService(
                FastAPI(), "test", "http://printer", tmp_path, _TrialTelemetryStore(tmp_path)
            )
            current["gcode_move"]["extrude_factor"] = 1.0
            await restored.automatic.restore(client, current)
            assert restored.automatic.pending()["phase"] == "restored"

    asyncio.run(exercise())


def test_external_setting_is_not_overwritten(tmp_path):
    service = LearningService(
        FastAPI(), "test", "http://printer", tmp_path, _TrialTelemetryStore(tmp_path)
    )
    manager = service.automatic
    manager.save(
        {
            "id": "fixture",
            "filename": "test.gcode",
            "phase": "start_sent",
            "restore": {"extrusion_factor": 1.0},
            "audit": {
                "changed": True,
                "parameter": "flow_multiplier",
                "value": 1.005,
                "restore_commands": ["M221 S100"],
            },
        }
    )
    current = state("cancelled")
    current["print_stats"]["filename"] = "test.gcode"
    current["gcode_move"]["extrude_factor"] = 0.95
    asyncio.run(manager.restore(None, current))
    assert manager.pending()["phase"] == "restore_review_required"


def test_batch_cancel_restores_only_owned_flow_and_acceleration_once(tmp_path):
    service = LearningService(
        FastAPI(), "test", "http://printer", tmp_path, _TrialTelemetryStore(tmp_path)
    )
    manager = service.automatic
    manager.save(
        {
            "id": "test",
            "filename": "six.gcode",
            "phase": "start_sent",
            "restore": {"extrusion_factor": 0.98, "accel_mm_s2": 500},
            "audit": {
                "changed": True,
                "parameter": "batch_settings",
                "expected": {"extrusion_factor": 1, "accel_mm_s2": 750},
                "restore_commands": ["M221 S98", "SET_VELOCITY_LIMIT ACCEL=500"],
            },
        }
    )
    current = state("cancelled")
    current["print_stats"]["filename"] = "six.gcode"
    current["toolhead"]["max_accel"] = 750
    calls = []

    async def exercise():
        async with httpx.AsyncClient(
            base_url="http://printer",
            transport=httpx.MockTransport(
                lambda request: (
                    calls.append(request.read()) or httpx.Response(200, json={"result": "ok"})
                )
            ),
        ) as client:
            await manager.restore(client, current)
            await manager.restore(client, current)
            assert len(calls) == 1 and manager.pending()["phase"] == "restore_sent"
            current["gcode_move"]["extrude_factor"] = 0.98
            current["toolhead"]["max_accel"] = 500
            await manager.restore(client, current)
            assert manager.pending()["phase"] == "restored"

    asyncio.run(exercise())
