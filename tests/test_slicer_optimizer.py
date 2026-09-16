"""All records are synthetic fixtures. No slicer or printer is contacted."""

import copy
import hashlib
import json

import pytest

from klipperlearn.slicer_optimizer import (
    OptimizerError,
    advisor_request,
    build_profiles,
    configuration_sha256,
    digest,
    loads,
    main,
    review_session,
    validate_proposal,
    validate_session,
)


def session_fixture():
    preset = "Synthetic printer 0.4 nozzle"
    session = {
        "schema": "klipperlearn.slicer-session/v1",
        "synthetic": True,
        "printer": {
            "brand": "Example",
            "model": "Synthetic fixture",
            "preset": preset,
            "nozzle_mm": 0.4,
            "firmware": "Klipper",
        },
        "material": "Synthetic PLA test fixture",
        "benchmark": {"sha256": "a" * 64, "layer_height_mm": 0.2, "layer_count": 240},
        "base_process": {
            "name": "Existing test process",
            "version": "2.3.0.0",
            "inherits": "Test parent",
            "type": "process",
            "compatible_printers": [preset],
            "layer_height": "0.2",
            "outer_wall_speed": "40",
            "default_acceleration": "1000",
            "sparse_infill_density": "15%",
            "machine_start_gcode": "G28 ; unchanged fixture",
        },
        "base_filament": {
            "name": "Existing test filament",
            "version": "2.3.0.0",
            "inherits": "Test PLA",
            "type": "filament",
            "compatible_printers": [preset],
            "filament_flow_ratio": ["0.98"],
            "filament_max_volumetric_speed": ["10"],
            "enable_pressure_advance": ["1"],
            "pressure_advance": ["0.04"],
            "nozzle_temperature": ["210"],
            "setting_id": "old-private-id",
        },
        "limits": {
            "process.outer_wall_speed": {"min": 20, "max": 60, "max_step": 5},
            "filament.filament_max_volumetric_speed": {"min": 5, "max": 12, "max_step": 0.5},
        },
        "policy": {"minimum_repeats": 2, "quality_floor": 3.5, "maximum_time_cv": 0.1},
        "candidates": [
            {"id": "baseline", "process": {}, "filament": {}},
            {"id": "detail", "process": {"outer_wall_speed": 35}, "filament": {}},
            {"id": "fast", "process": {"outer_wall_speed": 45}, "filament": {}},
        ],
        "trials": [],
    }
    for candidate, seconds, score in zip(
        session["candidates"], (1800, 2400, 1500), (4.4, 4.9, 3.8)
    ):
        for repeat in range(2):
            identity = f"{candidate['id']}-{repeat}"
            session["trials"].append(
                {
                    "id": identity,
                    "session_id": "run-" + identity,
                    "candidate_id": candidate["id"],
                    "configuration_sha256": configuration_sha256(session, candidate),
                    "benchmark_sha256": "a" * 64,
                    "layer_height_mm": 0.2,
                    "layer_count": 240,
                    "completed": True,
                    "full_model": True,
                    "print_seconds": seconds + repeat,
                    "total_seconds": seconds + repeat + 120,
                    "surface_score": score,
                    "geometry_score": score,
                    "human_reviewed": True,
                    "photo_sha256": [hashlib.sha256(identity.encode()).hexdigest()],
                }
            )
    return session


def test_three_modes_select_whole_configurations_without_mutation():
    session = session_fixture()
    before = copy.deepcopy(session)
    result = build_profiles(session)
    assert result["review"]["selected"] == {
        "Quality": "detail",
        "Standard": "baseline",
        "Speed": "fast",
    }
    assert len(result["files"]) == 6
    for name, profile in result["files"].items():
        assert "DEMO" in profile["name"]
        if name.endswith("process.json"):
            assert profile["machine_start_gcode"] == session["base_process"]["machine_start_gcode"]
            assert profile["layer_height"] == "0.2" and profile["sparse_infill_density"] == "15%"
        else:
            assert profile["nozzle_temperature"] == ["210"]
            assert "setting_id" not in profile
    assert session == before and result["printer_commands"] is False


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("completed", False, "not_completed"),
        ("full_model", False, "partial_model"),
        ("layer_count", 121, "incomparable_geometry_or_layers"),
        ("layer_height_mm", 0.4, "incomparable_geometry_or_layers"),
        ("configuration_sha256", "b" * 64, "configuration_identity_mismatch"),
        ("benchmark_sha256", "b" * 64, "incomparable_geometry_or_layers"),
        ("photo_sha256", [], "photographs_missing"),
        ("human_reviewed", False, "human_review_missing"),
        ("surface_score", None, "human_review_missing"),
    ],
)
def test_incomparable_or_incomplete_trials_never_qualify(field, value, reason):
    session = session_fixture()
    session["trials"][0][field] = value
    result = review_session(session)
    assert reason in result["excluded"][0]["reasons"]
    assert result["status"] == "more_evidence_required"
    with pytest.raises(OptimizerError):
        build_profiles(session)


@pytest.mark.parametrize("field", ["session_id", "photo_sha256"])
def test_reused_evidence_does_not_count_as_independent_repeat(field):
    session = session_fixture()
    session["trials"][1][field] = session["trials"][0][field]
    result = review_session(session)
    assert "reused_session_or_photograph" in result["excluded"][0]["reasons"]


def test_failed_candidate_is_not_selected_despite_previous_success():
    session = session_fixture()
    failed = copy.deepcopy(session["trials"][-1])
    failed.update(id="failed", session_id="failed", completed=False)
    session["trials"].append(failed)
    result = review_session(session)
    assert "fast" not in result["selected"].values()


def test_noisy_timing_or_poor_quality_abstains():
    for key, value in (("print_seconds", 30), ("geometry_score", 1)):
        session = session_fixture()
        session["trials"][-1][key] = value
        assert "fast" not in review_session(session)["selected"].values()


def test_baseline_only_may_win_all_modes_without_inventing_improvements():
    session = session_fixture()
    session["candidates"] = session["candidates"][:1]
    session["trials"] = session["trials"][:2]
    assert set(review_session(session)["selected"].values()) == {"baseline"}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, 10**400, "fast", None])
def test_bad_values_are_rejected(bad):
    session = session_fixture()
    session["candidates"][1]["process"]["outer_wall_speed"] = bad
    with pytest.raises(OptimizerError):
        review_session(session)


@pytest.mark.parametrize(
    "key", ["layer_height", "machine_start_gcode", "nozzle_temperature", "unknown"]
)
def test_ai_cannot_change_locked_or_unknown_settings(key):
    session = session_fixture()
    session["candidates"][1]["process"][key] = 2
    with pytest.raises(OptimizerError):
        validate_session(session)


def test_proposal_is_single_step_bound_to_exact_session_and_evidence():
    session = session_fixture()
    proposal = {
        "schema": "klipperlearn.slicer-proposal/v1",
        "session_sha256": digest(session),
        "anchor_candidate_id": "baseline",
        "parameter": "process.outer_wall_speed",
        "value": 42,
        "evidence_trial_ids": ["baseline-0", "baseline-1"],
        "rationale": "Test a smaller measured step.",
    }
    before = copy.deepcopy(session)
    result = validate_proposal(session, proposal)
    assert result["candidate"]["process"] == {"outer_wall_speed": 42}
    assert result["applied"] is False and session == before
    assert len(result["files"]) == 2
    assert all("UNVALIDATED TRIAL" in p["name"] for p in result["files"].values())
    process = result["files"]["klipperlearn_unvalidated_trial_process.json"]
    assert process["outer_wall_speed"] == "42" and process["layer_height"] == "0.2"
    assert process["machine_start_gcode"] == before["base_process"]["machine_start_gcode"]
    for key, value in (
        ("session_sha256", "0" * 64),
        ("value", 60),
        ("value", 40),
        ("evidence_trial_ids", ["invented"]),
        ("parameter", "process.machine_start_gcode"),
    ):
        with pytest.raises(OptimizerError):
            validate_proposal(session, {**proposal, key: value})
    with pytest.raises(OptimizerError):
        validate_proposal(session, {**proposal, "gcode": "G28"})


def test_advisor_request_does_not_include_base_scripts_or_pretend_hashes_are_photos():
    result = advisor_request(session_fixture())
    assert "machine_start_gcode" not in json.dumps(result)
    assert result["images_attached"] is False
    assert result["review"]["independently_verified"] is False


@pytest.mark.parametrize(
    "raw",
    ['{"x":1,"x":2}', '{"x":NaN}', '{"x":"\\ud800"}', "[]", "{}" * 1024 * 1024],
    ids=["duplicate", "nonfinite", "unicode", "array", "oversized"],
)
def test_strict_json(raw):
    with pytest.raises(OptimizerError):
        loads(raw)


@pytest.mark.parametrize(
    "key", ["password", "api_key", "printhost_apikey", "print_host", "cloud_token"]
)
def test_sensitive_connection_keys_are_rejected(key):
    session = session_fixture()
    session["base_process"][key] = "fixture-value"
    with pytest.raises(OptimizerError):
        advisor_request(session)


def test_unknown_compatibility_and_unresolved_settings_are_rejected():
    session = session_fixture()
    session["base_process"]["compatible_printers"] = []
    with pytest.raises(OptimizerError):
        build_profiles(session)
    session = session_fixture()
    session["base_process"]["outer_wall_speed"] = "50%"
    with pytest.raises(OptimizerError):
        build_profiles(session)


def test_changing_base_profile_invalidates_prior_records():
    session = session_fixture()
    session["base_process"]["sparse_infill_density"] = "5%"
    assert not review_session(session)["selected"]


def test_cli_writes_exclusively_and_never_replaces_existing_output(tmp_path):
    source = tmp_path / "session.json"
    source.write_text(json.dumps(session_fixture()))
    output = tmp_path / "profiles.zip"
    assert main(["profiles", "--session", str(source), "--output", str(output)]) == 0
    before = output.read_bytes()
    assert main(["profiles", "--session", str(source), "--output", str(output)]) == 2
    assert output.read_bytes() == before


def test_baseline_must_resolve_and_obey_every_declared_limit():
    value = session_fixture()
    first = next(iter(value["limits"]))
    kind, key = first.split(".")
    value["base_" + kind][key] = "500" if kind == "process" else ["500"]
    with pytest.raises(OptimizerError):
        review_session(value)
    value = session_fixture()
    value["base_" + kind].pop(key, None)
    with pytest.raises(OptimizerError):
        review_session(value)
