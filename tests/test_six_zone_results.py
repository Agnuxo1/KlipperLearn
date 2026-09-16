from fastapi import FastAPI
from klipperlearn.companion import _TrialTelemetryStore
from klipperlearn.learning_service import LearningService
from klipperlearn.six_zone_batch import build_six_zone_batch
from klipperlearn.six_zone_results import update_batch_results
from test_six_zone_batch import SPEC, RESTORE


def test_six_results_are_idempotent_same_session_and_missing_views_are_not_zero(tmp_path):
    service = LearningService(
        FastAPI(), "test", "http://printer", tmp_path, _TrialTelemetryStore(tmp_path)
    )
    trial = service.store.create_trial(
        {
            "printer_id": "p",
            "session_id": "same-print",
            "model_sha256": "a" * 64,
            "material": "PLA",
            "nozzle_mm": 0.4,
        },
        {},
    )
    run = {
        "id": "b" * 32,
        "job_key": "test",
        "filename": "six.gcode",
        "phase": "complete",
        "trial_id": trial["id"],
    }
    service.save_run(run)
    manifest = build_six_zone_batch(SPEC, [4, 4.4, 4.8, 5.2, 5.6, 6], RESTORE)["manifest"]
    service.setting(
        "automatic_print:six.gcode", {"batch_manifest": manifest, "source_prefix_bytes": 60}
    )
    for zone in manifest["zones"]:
        service.event(
            run,
            "printer_sample",
            status={
                "virtual_sdcard": {"file_position": zone["start_byte"] + 100 + 60},
                "print_stats": {"print_duration": 10},
            },
        )
    update_batch_results(service)
    first = service.setting("latest_batch")
    update_batch_results(service)
    assert service.setting("latest_batch") == first
    assert len(service.store.list_trials()) == 7
    for zone in first["zones"]:
        child = service.store.get_trial(zone["trial_id"])
        assert child["context"]["session_id"] == "same-print"
        assert child["evidence"]["telemetry_parent_trial_id"] == trial["id"]
        assert child["evidence"]["capture_window_utc"][0] is not None
        assert zone["score"] is None and zone["data_score"] is None and zone["usable_views"] == 0
    # Rating the current child progresses the review queue without rewriting it.
    pending = service.setting("review_pending")["trial_id"]
    service.store.rate_trial(pending, {"speed": 3, "surface": 4, "geometry": 4})
    update_batch_results(service)
    assert service.setting("review_pending")["trial_id"] != pending
    assert service.store.get_trial(pending)["score"] is None
