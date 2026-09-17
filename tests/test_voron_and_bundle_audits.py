"""Local evidence packet integrity and exact paired-preset ZIP validation."""

import copy
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from klipperlearn.ecosystem_evidence import EvidenceError
from klipperlearn.voron_review import DECLARATIONS, verify_packet


def packet(root):
    trials = []
    for index in range(2):
        raw = b"\xff\xd8synthetic-test-not-a-real-photo" + bytes([index]) + b"\xff\xd9"
        name = f"photo-{index}.jpg"
        (root / name).write_bytes(raw)
        trials.append(
            {
                "trial_id": f"trial-{index}",
                "session_id": f"session-{index}",
                "benchmark_sha256": "a" * 64,
                "configuration_sha256": "b" * 64,
                "completed": True,
                "layer_height_mm": 0.2,
                "layer_count": 60,
                "photo": name,
                "photo_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return {
        "schema": "klipperlearn.voron-evidence/v1",
        "printer_id": "voron-test",
        "voron_model": "Trident",
        "configuration_sha256": "b" * 64,
        "benchmark_sha256": "a" * 64,
        "declarations": dict.fromkeys(DECLARATIONS, True),
        "trials": trials,
    }


def test_verified_bytes_do_not_certify_voron_or_real_photos(tmp_path):
    value = packet(tmp_path)
    original = copy.deepcopy(value)
    result = verify_packet(value, tmp_path)
    assert result["ready_for_human_review"]
    assert result["photo_files_hash_verified"] == 2
    assert (
        not result["voron_compatibility_certified"] and not result["image_content_quality_verified"]
    )
    assert not result["declarations_independently_verified"] and not result["commands_allowed"]
    assert value == original and str(tmp_path) not in json.dumps(result)


@pytest.mark.parametrize("declaration", DECLARATIONS)
def test_no_physical_or_human_review_cannot_qualify(declaration, tmp_path):
    value = packet(tmp_path)
    value["declarations"][declaration] = False
    result = verify_packet(value, tmp_path)
    assert not result["ready_for_human_review"] and declaration in result["blockers"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("photo", "../outside.jpg"),
        ("photo", "/etc/passwd"),
        ("photo", "C:/file.jpg"),
        ("photo", "a\\b.jpg"),
        ("photo", "x//a.jpg"),
        ("photo_sha256", "0" * 64),
        ("layer_height_mm", True),
        ("layer_count", True),
        ("session_id", "session-0"),
        ("trial_id", "trial-0"),
        ("configuration_sha256", "c" * 64),
    ],
)
def test_untrusted_voron_evidence_rejected(field, value, tmp_path):
    data = packet(tmp_path)
    data["trials"][1][field] = value
    with pytest.raises((EvidenceError, OSError)):
        verify_packet(data, tmp_path)


def test_inconsistent_layers_and_incomplete_trials_stay_blocked(tmp_path):
    data = packet(tmp_path)
    data["trials"][1]["layer_count"] = 30
    data["trials"][1]["completed"] = False
    result = verify_packet(data, tmp_path)
    assert set(result["blockers"]) == {"inconsistent_layers", "unfinished_trial"}


def sample_session():
    return json.loads(
        (Path(__file__).resolve().parents[1] / "examples/synthetic-slicer-session.json").read_text()
    )


def make_bundle(tmp_path, mutate=None):
    from klipperlearn.slicer_optimizer import build_profiles

    session = sample_session()
    result = build_profiles(session)
    files = dict(result["files"])
    files["review.json"] = {k: v for k, v in result.items() if k != "files"}
    if mutate:
        mutate(files)
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, json.dumps(value))
    return session, path


def test_exact_bundle_matches_session_without_native_import_claim(tmp_path):
    from klipperlearn.orca_bundle_audit import audit_bundle

    session, path = make_bundle(tmp_path)
    before = path.read_bytes()
    result = audit_bundle(session, path)
    assert result["matches_reviewed_session"] and result["profile_count"] == 6
    assert result["synthetic"] and not result["native_slicer_import_verified"]
    assert not result["configuration_installed"] and path.read_bytes() == before


@pytest.mark.parametrize(
    "key,value",
    [
        ("layer_height", "0.8"),
        ("machine_start_gcode", "G28"),
        ("name", "wrong-pair"),
        ("inherits", "other printer"),
        ("outer_wall_speed", "999"),
    ],
)
def test_changed_presets_not_certified_as_reviewed(key, value, tmp_path):
    from klipperlearn.orca_bundle_audit import audit_bundle

    session, path = make_bundle(
        tmp_path, lambda files: files["klipperlearn_quality_process.json"].update({key: value})
    )
    with pytest.raises(EvidenceError):
        audit_bundle(session, path)


def test_extra_zip_paths_rejected_without_extraction(tmp_path):
    from klipperlearn.orca_bundle_audit import audit_bundle

    session, path = make_bundle(tmp_path, lambda files: files.update({"../outside.json": {}}))
    with pytest.raises(EvidenceError):
        audit_bundle(session, path)
    assert not (tmp_path.parent / "outside.json").exists()


def test_duplicate_zip_names_rejected(tmp_path):
    from klipperlearn.orca_bundle_audit import audit_bundle

    session, path = make_bundle(tmp_path)
    with pytest.warns(UserWarning), zipfile.ZipFile(path, "a") as archive:
        archive.writestr("review.json", "{}")
    with pytest.raises(EvidenceError):
        audit_bundle(session, path)
