import hashlib
import json

import pytest

from klipperlearn.multimodal_learning import (
    KEYS,
    extract_features,
    fit_model,
    predict_score,
    weighted_score,
)


def rows(count=16):
    return [
        {
            "trial_id": str(i),
            "session_id": str(i),
            "context_key": "same-context",
            "human_score": 20 + i * 4,
            "features": {
                "eligible": True,
                "features": {key: float(i) if key == "image_edge" else None for key in KEYS},
            },
        }
        for i in range(count)
    ]


def test_model_abstains_until_validated_and_never_uses_own_label_for_validation():
    assert not fit_model(rows(4))["validated"]
    model = fit_model(rows())
    assert model["validated"]
    assert model["mae"] < model["baseline_mae"]
    assert len(model["cross_validated_scores"]) == 16
    assert model["cross_validated_scores"]["0"] != 20
    assert predict_score(model, rows()[4]["features"]) is not None
    outside = rows()[0]["features"]
    outside["features"]["image_edge"] = 1e6
    assert predict_score(model, outside) is None


def test_duplicate_sessions_not_counted_and_contexts_not_mixed():
    data = rows(8)
    for row in data:
        row["session_id"] = "one-session"
    assert fit_model(data)["sessions"] == 1
    assert not fit_model(data)["validated"]
    data = rows()
    data[0]["context_key"] = "different-material"
    with pytest.raises(ValueError, match="Cannot mix"):
        fit_model(data)


def test_constant_or_unrelated_labels_do_not_certify_a_model():
    data = rows()
    for row in data:
        row["human_score"] = 80
    assert not fit_model(data)["validated"]
    assert weighted_score(None, 80) is None
    assert weighted_score(20, 80) == 56


def test_feature_extraction_reads_every_phone_chunk_and_verifies_photo_hash(tmp_path):
    from PIL import Image
    import numpy as np

    image_path = tmp_path / "image.jpg"
    image = (np.random.default_rng(42).random((128, 128, 3)) * 220 + 15).astype("uint8")
    Image.fromarray(image).save(image_path)
    trial_id = "a" * 32
    directory = tmp_path / "assets" / "telemetry" / (trial_id + ".json.chunks")
    directory.mkdir(parents=True)
    for index in range(2):
        payload = {
            "trial_id": trial_id,
            "started_at_utc": "2026-09-13T12:00:00Z",
            "samples": {
                "motion": [
                    {
                        "t_ms": index * 20,
                        "timestamp_utc": str(index),
                        "linear_acceleration_mps2": {"x": 3, "y": 4, "z": 0},
                    }
                ]
            },
        }
        (directory / f"{index}.json").write_text(json.dumps(payload))
    photo = {
        "relative_path": "image.jpg",
        "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
        "original_name": "camera-eye-one.jpg",
    }
    trial = {"id": trial_id, "photos": [photo], "evidence": {}}
    features = extract_features(tmp_path, trial)
    assert features["eligible"]
    assert features["coverage"]["motion"] == 2
    assert features["features"]["motion_rate_hz"] == 50
    assert features["features"]["acceleration_x_rms"] == 3
    assert features["features"]["audio_rms_dbfs"] is None
    photo["sha256"] = "0" * 64
    assert not extract_features(tmp_path, trial)["eligible"]


def test_synthetic_evidence_never_enters_real_learning(tmp_path):
    result = extract_features(
        tmp_path, {"id": "b" * 32, "photos": [], "evidence": {"synthetic": True}}
    )
    assert not result["eligible"]
    assert "synthetic_evidence" in result["issues"]
