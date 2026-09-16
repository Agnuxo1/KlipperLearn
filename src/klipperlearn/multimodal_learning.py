"""Small local, auditable learner. No downloaded weights or printer commands.

Image/phone features predict historical user scores, not physical resonance
frequencies. Every validation prediction excludes its own printing session.
An unvalidated model abstains. Missing sensors are explicit, never zero evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import statistics

VERSION = "multimodal-ridge-v2"
MIN_SESSIONS = 8
KEYS = (
    "image_mean",
    "image_contrast",
    "image_edge",
    "image_laplacian",
    "image_clipped",
    "image_entropy",
    "image_blue",
    "image_red",
    "image_edge_x",
    "image_edge_y",
    "acceleration_x_rms",
    "acceleration_y_rms",
    "acceleration_z_rms",
    "rotation_x_rms",
    "rotation_y_rms",
    "rotation_z_rms",
    "audio_rms_dbfs",
    "audio_peak_dbfs",
    "audio_dominant_hz",
    "orientation_alpha_std",
    "orientation_beta_std",
    "orientation_gamma_std",
    "motion_rate_hz",
    "motion_jitter_cv",
    "print_duration_s",
    "hotend_error_c",
    "bed_error_c",
)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (ValueError, OverflowError):
        return False


def safe_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Evidence path is outside the store or missing")
    return path


def image_features(path):
    import numpy as np
    from PIL import Image

    with Image.open(path) as image:
        if image.width * image.height > 20_000_000 or min(image.size) < 64:
            raise ValueError("Unsupported image dimensions")
        image = image.convert("RGB")
        image.thumbnail((384, 384))
        rgb = np.asarray(image, dtype=float) / 255
    gray = rgb @ np.array([0.299, 0.587, 0.114])
    dx, dy = np.diff(gray, axis=1), np.diff(gray, axis=0)
    lap = gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:] - 4 * gray[1:-1, 1:-1]
    hist = np.histogram(gray, bins=32, range=(0, 1))[0].astype(float)
    hist = hist[hist > 0] / hist.sum()
    return {
        "image_mean": float(gray.mean()),
        "image_contrast": float(gray.std()),
        "image_edge": float((np.abs(dx).mean() + np.abs(dy).mean()) / 2),
        "image_laplacian": float(lap.var()),
        "image_clipped": float(((gray > 0.98) | (gray < 0.02)).mean()),
        "image_entropy": float(-(hist * np.log2(hist)).sum()),
        "image_blue": float((rgb[:, :, 2] - rgb[:, :, 1]).mean()),
        "image_red": float((rgb[:, :, 0] - rgb[:, :, 1]).mean()),
        "image_edge_x": float(np.abs(dx).mean()),
        "image_edge_y": float(np.abs(dy).mean()),
    }


def extract_features(root, trial, printer_samples=()):
    """Read immutable evidence; return features, coverage, hashes and exclusions."""
    values = {key: None for key in KEYS}
    pictures, hashes, views, issues = [], [], set(), []
    for photo in trial.get("photos", []):
        try:
            path = safe_path(root, photo["relative_path"])
            if path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("Oversized photo")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != photo["sha256"]:
                raise ValueError("Photo hash mismatch")
            features = image_features(path)
            hashes.append(actual)
            if features["image_contrast"] < 0.02 or features["image_clipped"] > 0.65:
                issues.append("photo_exposure_or_contrast")
                continue
            pictures.append(features)
            name = photo.get("original_name", "")
            if name.startswith("camera-"):
                views.add(name[7:].rsplit("-", 1)[0])
            elif "torch-on" in name or "torch-off" in name:
                views.add("phone-torch-on" if "torch-on" in name else "phone-torch-off")
            else:
                views.add("manual-unregistered-view")
        except (OSError, ValueError, KeyError):
            issues.append("unusable_or_missing_photo")
    if pictures:
        for key in pictures[0]:
            values[key] = statistics.mean(picture[key] for picture in pictures)

    streams = {key: {} for key in ("motion", "orientation", "audio_features")}
    trial_id = (trial.get("evidence") or {}).get("telemetry_parent_trial_id") or trial["id"]
    if not isinstance(trial_id, str) or not __import__("re").fullmatch("[0-9a-f]{32}", trial_id):
        raise ValueError("Invalid telemetry identity")
    window = (trial.get("evidence") or {}).get("capture_window_utc")
    directory = Path(root) / "assets" / "telemetry"
    candidates = list((directory / (trial_id + ".json.chunks")).glob("*.json"))
    if (directory / (trial_id + ".json")).is_file():
        candidates.append(directory / (trial_id + ".json"))
    for candidate in candidates:
        try:
            path = safe_path(root, candidate.relative_to(root))
            if path.stat().st_size > 8 * 1024 * 1024:
                raise ValueError("Oversized telemetry chunk")
            raw = path.read_bytes()
            payload = json.loads(raw)
            if payload.get("trial_id") != trial_id:
                raise ValueError("Wrong telemetry trial")
            hashes.append(hashlib.sha256(raw).hexdigest())
            origin = payload.get("started_at_utc")
            for kind in streams:
                for sample in payload.get("samples", {}).get(kind, []):
                    if window:
                        from datetime import datetime

                        try:
                            stamp = datetime.fromisoformat(
                                sample["timestamp_utc"].replace("Z", "+00:00")
                            )
                            if (
                                not window[0]
                                or not window[1]
                                or not datetime.fromisoformat(window[0])
                                <= stamp
                                <= datetime.fromisoformat(window[1])
                            ):
                                continue
                        except (ValueError, KeyError, TypeError):
                            continue
                    identity = (origin, sample.get("t_ms"), sample.get("timestamp_utc"))
                    streams[kind][identity] = sample
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            issues.append("invalid_telemetry_chunk")

    def column(kind, key, axis=None):
        result = []
        for sample in streams[kind].values():
            value = sample.get(key)
            if axis:
                value = value.get(axis) if isinstance(value, dict) else None
            if finite(value):
                result.append(value)
        return result

    for axis in ("x", "y", "z"):
        for prefix, field in [
            ("acceleration", "linear_acceleration_mps2"),
            ("rotation", "rotation_rate_dps"),
        ]:
            numbers = column("motion", field, axis)
            if numbers:
                values[f"{prefix}_{axis}_rms"] = math.sqrt(
                    statistics.mean(number * number for number in numbers)
                )
    for axis in ("alpha", "beta", "gamma"):
        numbers = column("orientation", axis + "_deg")
        if len(numbers) > 1:
            values["orientation_" + axis + "_std"] = statistics.pstdev(numbers)
    for key, source in [
        ("audio_rms_dbfs", "rms_dbfs"),
        ("audio_peak_dbfs", "peak_dbfs"),
        ("audio_dominant_hz", "dominant_frequency_hz"),
    ]:
        numbers = column("audio_features", source)
        if numbers:
            values[key] = statistics.mean(numbers)
    timelines = {}
    for (origin, t, _), sample in streams["motion"].items():
        if finite(t):
            timelines.setdefault(origin, set()).add(t)
    intervals = [
        right - left
        for times in timelines.values()
        for left, right in zip(sorted(times), sorted(times)[1:])
        if 0 < right - left < 1000
    ]
    if intervals:
        mean = statistics.mean(intervals)
        values["motion_rate_hz"] = 1000 / mean
        values["motion_jitter_cv"] = statistics.pstdev(intervals) / mean
    durations = [sample.get("print_stats", {}).get("print_duration") for sample in printer_samples]
    durations = [value for value in durations if finite(value)]
    if durations:
        values["print_duration_s"] = max(durations) - min(durations) if window else max(durations)
    for key, section in [("hotend_error_c", "extruder"), ("bed_error_c", "heater_bed")]:
        errors = [
            abs(sample[section]["temperature"] - sample[section]["target"])
            for sample in printer_samples
            if finite(sample.get(section, {}).get("temperature"))
            and finite(sample.get(section, {}).get("target"))
            and sample[section]["target"] > 0
        ]
        if errors:
            values[key] = statistics.mean(errors)
    evidence = trial.get("evidence") or {}
    synthetic = evidence.get("synthetic") is True or evidence.get("test_only") is True
    coverage = {kind: len(samples) for kind, samples in streams.items()}
    coverage.update(
        photos=len(pictures), camera_views=sorted(views), printer_samples=len(printer_samples)
    )
    if not pictures:
        issues.append("no_usable_photos")
    if synthetic:
        issues.append("synthetic_evidence")
    return {
        "version": VERSION,
        "features": values,
        "coverage": coverage,
        "issues": sorted(set(issues)),
        "eligible": bool(pictures)
        and not synthetic
        and not any(i in issues for i in ("unusable_or_missing_photo", "invalid_telemetry_chunk")),
        "input_sha256": digest(
            {"hashes": sorted(set(hashes)), "printer": printer_samples, "features": values}
        ),
        "view_signature": digest(sorted(views)),
        "photo_sha256": sorted(photo["sha256"] for photo in trial.get("photos", [])),
    }


def context_key(trial, features):
    context = trial["context"]
    return digest(
        {key: context.get(key) for key in ("printer_id", "material", "nozzle_mm", "model_sha256")}
        | {"views": features["view_signature"]}
    )


def fit_model(rows):
    """Leave an entire printing session out of each validation fold."""
    import numpy as np

    unique = {}
    trial_ids = set()
    for row in rows:
        if (
            row["trial_id"] not in trial_ids
            and row["features"]["eligible"]
            and finite(row.get("human_score"))
        ):
            unique.setdefault(row["session_id"], []).append(row)
            trial_ids.add(row["trial_id"])
    selected = [row for group in unique.values() for row in group]
    result = {
        "version": VERSION,
        "validated": False,
        "sessions": len(unique),
        "minimum_sessions": MIN_SESSIONS,
        "reason": "insufficient_independent_sessions",
    }
    if len(unique) < MIN_SESSIONS:
        return result
    if len({row["context_key"] for row in selected}) != 1:
        raise ValueError("Cannot mix material, machine, model or camera setups")
    raw = np.array(
        [
            [
                row["features"]["features"][key]
                if finite(row["features"]["features"][key])
                else np.nan
                for key in KEYS
            ]
            for row in selected
        ]
    )
    y = np.array([row["human_score"] for row in selected], dtype=float)

    def fit(x, target):
        # Compute imputation/scaling inside each training fold, never on its test sample.
        median = np.array(
            [np.median(col[np.isfinite(col)]) if np.isfinite(col).any() else 0 for col in x.T]
        )
        filled = np.where(np.isfinite(x), x, median)
        scale = filled.std(axis=0)
        scale[scale < 1e-8] = 1
        design = np.column_stack([np.ones(len(x)), (filled - median) / scale, ~np.isfinite(x)])
        regularizer = np.eye(design.shape[1]) * 10
        regularizer[0, 0] = 0
        beta = np.linalg.solve(design.T @ design + regularizer, design.T @ target)
        return median, scale, beta

    def predict(x, fitted):
        median, scale, beta = fitted
        filled = np.where(np.isfinite(x), x, median)
        return np.column_stack([np.ones(len(x)), (filled - median) / scale, ~np.isfinite(x)]) @ beta

    predictions, naive = np.zeros(len(selected)), np.zeros(len(selected))
    for session in unique:
        held_out = np.array([row["session_id"] == session for row in selected])
        mask = ~held_out
        predictions[held_out] = predict(raw[held_out], fit(raw[mask], y[mask]))
        naive[held_out] = float(y[mask].mean())
    errors = np.abs(y - predictions)
    mae = float(errors.mean())
    baseline_mae = float(np.abs(y - naive).mean())
    validated = float(y.std()) >= 3 and mae <= 12 and mae < baseline_mae * 0.9
    median, scale, beta = fit(raw, y)
    result.update(
        validated=validated,
        reason="validated_by_independent_sessions" if validated else "does_not_beat_baseline",
        mae=mae,
        baseline_mae=baseline_mae,
        error_p95=float(np.quantile(errors, 0.95)),
        median=median.tolist(),
        scale=scale.tolist(),
        coefficients=beta.tolist(),
        trials=[row["trial_id"] for row in selected],
        cross_validated_scores={
            row["trial_id"]: float(min(100, max(0, prediction)))
            for row, prediction in zip(selected, predictions)
        },
        feature_keys=list(KEYS),
    )
    result["model_sha256"] = digest(result)
    return result


def predict_score(model, feature_record):
    """Abstain on corrupt models, invalid arithmetic or out-of-distribution inputs."""
    if not isinstance(model, dict) or not isinstance(feature_record, dict):
        return None
    if model.get("validated") is not True or feature_record.get("eligible") is not True:
        return None
    if model.get("version") != VERSION or model.get("feature_keys") != list(KEYS):
        return None
    import numpy as np

    try:
        features = feature_record["features"]
        values = [features[key] for key in KEYS]
        if any(value is not None and not finite(value) for value in values):
            return None
        raw = np.array([np.nan if value is None else value for value in values], dtype=float)
        median = np.array(model["median"], dtype=float)
        scale = np.array(model["scale"], dtype=float)
        coefficients = np.array(model["coefficients"], dtype=float)
        if median.shape != (len(KEYS),) or scale.shape != (len(KEYS),):
            return None
        if coefficients.shape != (1 + 2 * len(KEYS),):
            return None
        if not all(np.isfinite(array).all() for array in (median, scale, coefficients)):
            return None
        if np.any(scale <= 0):
            return None
        if model.get("model_sha256") != digest(
            {key: value for key, value in model.items() if key != "model_sha256"}
        ):
            return None
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            normalized = (np.where(np.isfinite(raw), raw, median) - median) / scale
            if not np.isfinite(normalized).all() or np.any(np.abs(normalized) > 4):
                return None
            design = np.concatenate([[1.0], normalized, ~np.isfinite(raw)])
            result = float(design @ coefficients)
        if not math.isfinite(result):
            return None
        return min(100.0, max(0.0, result))
    except (KeyError, TypeError, ValueError, OverflowError, FloatingPointError):
        return None


def weighted_score(data_score, human_score):
    if not finite(data_score) or not finite(human_score):
        return None
    if not 0 <= data_score <= 100 or not 0 <= human_score <= 100:
        raise ValueError("Scores out of range")
    return 0.4 * data_score + 0.6 * human_score
