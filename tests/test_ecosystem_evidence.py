"""Offline compatibility and privacy regressions for the evidence adapters."""

import copy
import json
import math

import pytest

from klipperlearn.ecosystem_evidence import (
    EvidenceError,
    HISTORY_STATES,
    finite_number,
    load_document,
    main,
    normalize_history,
    status_report,
    write_new,
)


def job(**updates):
    record = {
        "job_id": "000001",
        "status": "completed",
        "print_duration": 120,
        "total_duration": 150,
        "start_time": 1000,
        "end_time": 1150,
        "filament_used": 800,
        "exists": True,
        "metadata": {"layer_height": 0.2, "layer_count": 60},
        "filename": "private-name.gcode",
        "user": "private-user",
    }
    record.update(updates)
    return record


def normalized(records):
    return normalize_history(
        {"result": {"count": len(records), "jobs": records}},
        printer_id="printer-one",
        workflow="operator_chatgpt",
    )


@pytest.mark.parametrize(
    "value", [True, False, "1", math.inf, -math.inf, math.nan, -1, 10**400, {}, [], None]
)
def test_only_finite_nonnegative_numeric_metrics(value):
    assert finite_number(value) is None


def test_history_preserves_times_and_cohort_without_inventing_quality():
    source = [job()]
    original = copy.deepcopy(source)
    report = normalized(source)
    row = report["jobs"][0]
    assert row["print_duration_seconds"] == 120
    assert row["total_duration_seconds"] == 150
    assert row["nonprinting_duration_seconds"] == 30
    assert row["timing_eligible"] and not row["benchmark_eligible"]
    assert not row["quality_assessed"] and not row["full_geometry_verified"]
    assert row["workflow"] == "operator_chatgpt"
    assert source == original
    assert "private-name" not in json.dumps(report) and "private-user" not in json.dumps(report)
    assert not report["collection_completeness_verified"]
    assert not row["source_file_identity_verified"]


@pytest.mark.parametrize("state", sorted(HISTORY_STATES | {"COMPLETE", "success", "other"}))
def test_only_documented_completed_jobs_have_completion(state):
    result = normalized([job(status=state)])["jobs"][0]
    assert result["completed"] is (state == "completed")
    assert result["timing_eligible"] is (state == "completed")


@pytest.mark.parametrize(
    "updates,issue",
    [
        ({"print_duration": True}, "invalid_duration"),
        ({"total_duration": 30}, "print_duration_exceeds_total"),
        ({"start_time": 2000}, "end_precedes_start"),
        ({"end_time": None}, "missing_or_invalid_timestamps"),
        ({"start_time": "1000"}, "missing_or_invalid_timestamps"),
    ],
)
def test_inconsistent_history_cannot_be_used_as_timing_evidence(updates, issue):
    row = normalized([job(**updates)])["jobs"][0]
    assert issue in row["issues"] and not row["timing_eligible"]


def test_duplicates_and_invalid_entries_are_not_independent_trials():
    report = normalized([job(), job(), None, {"job_id": "../bad"}])
    assert all(not row["timing_eligible"] for row in report["jobs"])
    assert len(report["invalid_entries"]) == 2
    assert report["input_job_count"] == 4 and report["normalized_job_count"] == 2


@pytest.mark.parametrize("state", [None, {}, ["ready"], "unknown"])
def test_status_unknown_inputs_do_not_crash_or_grant_permission(state):
    result = status_report({"result": {"status": {"webhooks": {"state": state}}}})
    assert result["klipper_state"] == "unknown"
    assert not result["commands_allowed"]


def test_mcu_error_distinct_from_missing_backend_and_private_text_filtered():
    report = status_report(
        {
            "result": {
                "status": {
                    "webhooks": {
                        "state": "error",
                        "state_message": "mcu: Unable to connect private-token",
                    },
                    "print_stats": {"state": "standby"},
                }
            }
        }
    )
    assert report["diagnostic"] == "mcu_connection_unavailable"
    assert report["server_response_parsed"] and not report["between_prints_reported"]
    assert "private-token" not in json.dumps(report)


def test_ready_snapshot_is_never_freshness_or_motion_authorization():
    report = status_report(
        {
            "status": {
                "webhooks": {"state": "ready"},
                "print_stats": {"state": "complete"},
                "configfile": {
                    "settings": {
                        "printer": {"kinematics": "corexy", "max_accel": 1500, "max_velocity": 200},
                        "extruder": {"nozzle_diameter": 0.4},
                        "private": "secret",
                    }
                },
                "toolhead": {"axis_minimum": [0, 0, 0, 0], "axis_maximum": [200, 200, 200, 0]},
            }
        }
    )
    assert report["between_prints_reported"]
    assert report["kinematics"] == "corexy" and report["axis_maximum_mm"] == [200, 200, 200]
    assert not report["commands_allowed"] and not report["freshness_verified"]
    assert "secret" not in json.dumps(report)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":NaN}',
        b'{"x":1e999}',
        b"[]",
        b'{"x":"\\ud800"}',
        b"\xff",
        b"",
        b'{"x":' + b"[" * 100,
    ],
)
def test_strict_json_rejects_ambiguous_or_malformed_documents(tmp_path, raw):
    path = tmp_path / "input.json"
    path.write_bytes(raw)
    with pytest.raises((EvidenceError, UnicodeError)):
        load_document(path)
    assert path.read_bytes() == raw


def test_no_overwrite_and_cli_has_no_network_arguments(tmp_path, capsys):
    path = tmp_path / "input.json"
    path.write_text(json.dumps({"jobs": [job()]}))
    output = tmp_path / "report.json"
    args = [
        "history",
        "--input",
        str(path),
        "--printer-id",
        "test",
        "--workflow",
        "manual",
        "--output",
        str(output),
    ]
    assert main(args) == 0
    before = output.read_bytes()
    assert main(args) == 2 and output.read_bytes() == before
    assert "private-name" not in capsys.readouterr().out
    with pytest.raises(FileExistsError):
        write_new(output, b"changed")


@pytest.mark.parametrize("doc", [{}, {"jobs": {}}, {"result": []}, {"jobs": [job()] * 10001}])
def test_bad_history_container_rejected(doc):
    with pytest.raises(EvidenceError):
        normalize_history(doc, printer_id="test", workflow="klipperlearn")


@pytest.mark.parametrize("flag", [True, False])
def test_synthetic_provenance_is_retained(flag):
    result = normalize_history(
        {"synthetic": flag, "jobs": []}, printer_id="demo", workflow="manual"
    )
    assert result["synthetic"] is flag
    status = status_report({"synthetic": flag, "result": {"status": {}}})
    assert status["synthetic"] is flag


@pytest.mark.parametrize("flag", ["true", 1, None, []])
def test_synthetic_provenance_cannot_be_coerced(flag):
    with pytest.raises(ValueError):
        normalize_history({"synthetic": flag, "jobs": []}, printer_id="demo", workflow="manual")
    with pytest.raises(ValueError):
        status_report({"synthetic": flag, "result": {"status": {}}})
