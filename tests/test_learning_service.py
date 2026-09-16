import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
import httpx

from klipperlearn.companion import _TrialTelemetryStore
from klipperlearn.learning_service import LearningService


def test_print_lifecycle_is_automatic_persistent_and_read_only(tmp_path):
    state = {
        "webhooks": {"state": "ready"},
        "print_stats": {"filename": "test.gcode", "state": "printing", "print_duration": 1},
        "configfile": {"settings": {"extruder": {"nozzle_diameter": 0.4}}},
        "toolhead": {"max_accel": 1000},
        "extruder": {"pressure_advance": 0.03, "temperature": 210, "target": 210},
        "heater_bed": {"temperature": 60, "target": 60},
        "gcode_move": {"extrude_factor": 1},
        "virtual_sdcard": {"progress": 0.1},
    }
    calls = []
    start_time = [1000]

    def respond(request):
        calls.append((request.method, request.url.path))
        assert request.method == "GET", "Observer must never move or heat the printer"
        if request.url.path == "/printer/objects/query":
            return httpx.Response(200, json={"result": {"status": state}})
        if request.url.path == "/server/files/metadata":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "filament_type": "PLA",
                        "nozzle_diameter": 0.4,
                        "print_start_time": start_time[0],
                    }
                },
            )
        if request.url.path == "/server/files/gcodes/test.gcode":
            return httpx.Response(200, content=b"; real file fixture\nG1 X1\n")
        return httpx.Response(404)

    transport = httpx.MockTransport(respond)
    telemetry = _TrialTelemetryStore(tmp_path)
    service = LearningService(
        FastAPI(), "test-token", "http://printer.test:7125", tmp_path, telemetry, transport
    )
    service.internal = AsyncMock(return_value={"views": [{"status": "saved"}]})

    async def exercise():
        async with httpx.AsyncClient(
            base_url="http://printer.test:7125", transport=transport
        ) as client:
            await service.tick(client)
            first = service.current_run()
            assert first["trial_id"] == telemetry.get_active()["trial_id"]
            assert len(service.store.list_trials()) == 1
            await service.tick(client)
            assert len(service.store.list_trials()) == 1
            restored = LearningService(
                FastAPI(), "test-token", "http://printer.test:7125", tmp_path, telemetry, transport
            )
            assert restored.current_run()["id"] == first["id"]
            state["print_stats"].update(state="complete", print_duration=60)
            with patch("klipperlearn.learning_service.asyncio.sleep", new=AsyncMock()):
                await service.tick(client)
            assert telemetry.get_active()["trial_id"] is None
            assert service.setting("review_pending")["trial_id"] == first["trial_id"]
            service.internal.assert_awaited_once()
            state["print_stats"].update(state="printing", print_duration=1)
            with pytest.raises(ValueError, match="fresh print identity"):
                await service.tick(client)
            assert len(service.store.list_trials()) == 1
            assert service.current_run()["phase"] == "complete"
            start_time[0] += 100
            await service.tick(client)
            assert len(service.store.list_trials()) == 2
            assert service.current_run()["id"] != first["id"]

    asyncio.run(exercise())
    assert all(method == "GET" for method, _ in calls)


def test_learning_analysis_does_not_overwrite_historical_human_revisions(tmp_path):
    service = LearningService(
        FastAPI(), "test-token", "http://printer.test", tmp_path, _TrialTelemetryStore(tmp_path)
    )
    trial = service.store.create_trial(
        {
            "printer_id": "p",
            "session_id": "s",
            "model_sha256": "a" * 64,
            "material": "PLA",
            "nozzle_mm": 0.4,
        },
        {},
    )
    before = service.store.rate_trial(trial["id"], {"speed": 4, "surface": 4, "geometry": 4})
    summary = service.learn()
    after = service.store.get_trial(trial["id"])
    assert summary["validated_models"] == 0
    assert before["revisions"] == after["revisions"]
    assert after["score"] is None
    assert after["learning"]["model_validated"] is False


def test_final_photo_pair_retains_phone_until_complete_without_duplicate_capture(tmp_path):
    service = LearningService(
        FastAPI(), "test", "http://printer", tmp_path, _TrialTelemetryStore(tmp_path)
    )
    trial = service.store.create_trial(
        {
            "printer_id": "p",
            "session_id": "s",
            "model_sha256": "a" * 64,
            "material": "PLA",
            "nozzle_mm": 0.4,
        },
        {},
    )
    run = {
        "id": "b" * 32,
        "job_key": "fixture",
        "filename": "f.gcode",
        "phase": "printing",
        "trial_id": trial["id"],
        "owned_telemetry": True,
        "context": {"provenance": {"metadata": {"fields": {"object_height": 0.6}}}},
    }
    service.telemetry.claim_if_empty(trial["id"])
    current = {
        "print_stats": {"state": "complete"},
        "toolhead": {"position": [260, 205, 5], "axis_maximum": [270, 215, 195]},
    }

    async def exercise():
        service.internal = AsyncMock(
            side_effect=[
                {"id": "job", "status": "pending"},
                {"views": []},
                {"id": "job", "status": "pending"},
            ]
        )
        await service.finish_run(run, current)
        assert service.current_run()["phase"] == "finishing"
        assert service.telemetry.get_active()["trial_id"] == trial["id"]
        finished_at = run["finished_at"]
        service.internal = AsyncMock(return_value={"id": "job", "status": "complete"})
        with patch("klipperlearn.learning_service.asyncio.sleep", new=AsyncMock()):
            await service.finish_run(run, current)
        assert run["phase"] == "complete" and run["finished_at"] == finished_at
        assert service.telemetry.get_active()["trial_id"] is None
        service.internal.assert_awaited_once_with("GET", "photo-pairs/job")

    asyncio.run(exercise())
