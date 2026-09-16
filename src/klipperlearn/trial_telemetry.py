"""Validation and aggregation for passive, web-collected trial telemetry.

The browser-side collector in ``static/trial-telemetry.js`` is deliberately
standalone.  This module gives its JSON export a small, reviewable contract:
the export is tied to one trial, every sample has relative and wall-clock
timestamps, and microphone data is limited to short-lived aggregate features.

There is no printer, network, companion, or persistence integration here.
``validate_trial_telemetry`` returns a normalized copy and
``audit_trial_telemetry`` provides a non-throwing report suitable for a review
screen or an offline import check.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
import math
import re
from typing import Any


TRIAL_TELEMETRY_SCHEMA = "klipperlearn.trial-telemetry/v1"
TRIAL_TELEMETRY_SOURCE = "web"
MAX_TRIAL_ID_LENGTH = 120
MAX_MOTION_SAMPLES = 16_384
MAX_ORIENTATION_SAMPLES = 16_384
MAX_AUDIO_FEATURES = 4_096

_SAFE_TRIAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")
_SOURCES = ("motion", "orientation", "audio")
_PERMISSION_STATES = frozenset(
    {"granted", "denied", "unavailable", "not_requested", "prompt", "partial"}
)
_RAW_AUDIO_KEYS = frozenset(
    {
        "audio_blob",
        "audio_buffer",
        "audio_data",
        "audio_samples",
        "media_recorder",
        "pcm",
        "pcm_samples",
        "raw_audio",
        "recording",
        "time_data",
        "time_domain",
        "time_domain_data",
        "waveform",
    }
)
_AUDIO_CONTEXT_KEYS = frozenset({"audio", "audio_features", "microphone"})
_AUDIO_CONTEXT_RAW_KEYS = frozenset({"data", "samples", "values"})


class TrialTelemetryError(ValueError):
    """Raised when a trial telemetry export cannot be accepted safely."""


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrialTelemetryError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise TrialTelemetryError(f"{field} must be a finite number")
    return number


def _optional_finite_number(value: object, field: str) -> float | None:
    if value is None:
        return None
    return _finite_number(value, field)


def _non_empty_text(value: object, field: str, *, max_length: int = 240) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise TrialTelemetryError(f"{field} must be non-empty text")
    if any(ord(character) < 32 for character in value):
        raise TrialTelemetryError(f"{field} must not contain control characters")
    return value


def _trial_id(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) > MAX_TRIAL_ID_LENGTH
        or not _SAFE_TRIAL_ID.fullmatch(value)
    ):
        raise TrialTelemetryError("trial_id no tiene un formato seguro")
    return value


def _timestamp(value: object, field: str, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise TrialTelemetryError(f"{field} must be a UTC timestamp")
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TrialTelemetryError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise TrialTelemetryError(f"{field} must include a time zone")
    return candidate


def _raw_audio_present(value: object, *, audio_context: bool = False) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in _RAW_AUDIO_KEYS or (audio_context and lowered in _AUDIO_CONTEXT_RAW_KEYS):
                return True
            if _raw_audio_present(
                item,
                audio_context=audio_context or lowered in _AUDIO_CONTEXT_KEYS,
            ):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_raw_audio_present(item, audio_context=audio_context) for item in value)
    return False


def _normalize_vector(value: object, field: str) -> dict[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TrialTelemetryError(f"{field} must be a vector")
    vector: dict[str, float] = {}
    for axis in ("x", "y", "z"):
        if axis in value and value[axis] is not None:
            vector[axis] = _finite_number(value[axis], f"{field}.{axis}")
    return vector or None


def _normalize_sample_header(
    sample: Mapping[str, Any], trial_id: str, field: str
) -> dict[str, Any]:
    timestamp = _timestamp(
        sample.get("timestamp_utc", sample.get("captured_at_utc")),
        f"{field}.timestamp_utc",
    )
    t_ms = _finite_number(sample.get("t_ms"), f"{field}.t_ms")
    if t_ms < 0:
        raise TrialTelemetryError(f"{field}.t_ms must not be negative")
    sample_trial_id = sample.get("trial_id")
    if sample_trial_id is not None and _trial_id(sample_trial_id) != trial_id:
        raise TrialTelemetryError(f"{field}.trial_id no coincide con trial_id")
    return {"trial_id": trial_id, "t_ms": t_ms, "timestamp_utc": timestamp}


def _normalize_motion(samples: object, trial_id: str) -> list[dict[str, Any]]:
    if not isinstance(samples, list):
        raise TrialTelemetryError("samples.motion must be a list")
    if len(samples) > MAX_MOTION_SAMPLES:
        raise TrialTelemetryError("samples.motion exceeds the permitted limit")
    normalized: list[dict[str, Any]] = []
    previous = -1.0
    for index, raw in enumerate(samples):
        field = f"samples.motion[{index}]"
        if not isinstance(raw, Mapping):
            raise TrialTelemetryError(f"{field} must be an object")
        item = _normalize_sample_header(raw, trial_id, field)
        if item["t_ms"] < previous:
            raise TrialTelemetryError(f"{field}.t_ms is not monotonic")
        previous = item["t_ms"]
        for source_key, output_key in (
            ("linear_acceleration_mps2", "linear_acceleration_mps2"),
            ("acceleration_including_gravity_mps2", "acceleration_including_gravity_mps2"),
            ("rotation_rate_dps", "rotation_rate_dps"),
        ):
            vector = _normalize_vector(raw.get(source_key), f"{field}.{source_key}")
            if vector is not None:
                item[output_key] = vector
        interval_ms = _optional_finite_number(raw.get("interval_ms"), f"{field}.interval_ms")
        if interval_ms is not None:
            if interval_ms < 0:
                raise TrialTelemetryError(f"{field}.interval_ms must not be negative")
            item["interval_ms"] = interval_ms
        if not any(
            key in item
            for key in (
                "linear_acceleration_mps2",
                "acceleration_including_gravity_mps2",
                "rotation_rate_dps",
            )
        ):
            raise TrialTelemetryError(f"{field} contains no valid motion signal")
        normalized.append(item)
    return normalized


def _normalize_orientation(samples: object, trial_id: str) -> list[dict[str, Any]]:
    if not isinstance(samples, list):
        raise TrialTelemetryError("samples.orientation must be a list")
    if len(samples) > MAX_ORIENTATION_SAMPLES:
        raise TrialTelemetryError("samples.orientation exceeds the permitted limit")
    normalized: list[dict[str, Any]] = []
    previous = -1.0
    for index, raw in enumerate(samples):
        field = f"samples.orientation[{index}]"
        if not isinstance(raw, Mapping):
            raise TrialTelemetryError(f"{field} must be an object")
        item = _normalize_sample_header(raw, trial_id, field)
        if item["t_ms"] < previous:
            raise TrialTelemetryError(f"{field}.t_ms is not monotonic")
        previous = item["t_ms"]
        for angle in ("alpha_deg", "beta_deg", "gamma_deg"):
            value = _optional_finite_number(raw.get(angle), f"{field}.{angle}")
            if value is not None:
                item[angle] = value
        if "absolute" in raw:
            if type(raw["absolute"]) is not bool:
                raise TrialTelemetryError(f"{field}.absolute must be a boolean")
            item["absolute"] = raw["absolute"]
        if not any(angle in item for angle in ("alpha_deg", "beta_deg", "gamma_deg")):
            raise TrialTelemetryError(f"{field} contains no valid orientation")
        normalized.append(item)
    return normalized


def _normalize_bands(value: object, field: str) -> dict[str, float]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TrialTelemetryError(f"{field} must be an object")
    bands: dict[str, float] = {}
    for name, number in value.items():
        if not isinstance(name, str) or not name or len(name) > 32:
            raise TrialTelemetryError(f"{field} contains an invalid band name")
        bands[name] = _finite_number(number, f"{field}.{name}")
    return bands


def _normalize_audio(samples: object, trial_id: str) -> list[dict[str, Any]]:
    if not isinstance(samples, list):
        raise TrialTelemetryError("samples.audio_features must be a list")
    if len(samples) > MAX_AUDIO_FEATURES:
        raise TrialTelemetryError("samples.audio_features exceeds the permitted limit")
    normalized: list[dict[str, Any]] = []
    previous = -1.0
    for index, raw in enumerate(samples):
        field = f"samples.audio_features[{index}]"
        if not isinstance(raw, Mapping):
            raise TrialTelemetryError(f"{field} must be an object")
        item = _normalize_sample_header(raw, trial_id, field)
        if item["t_ms"] < previous:
            raise TrialTelemetryError(f"{field}.t_ms is not monotonic")
        previous = item["t_ms"]
        for name in (
            "rms_dbfs",
            "peak_dbfs",
            "dominant_frequency_hz",
            "dominant_magnitude_db",
        ):
            value = _optional_finite_number(raw.get(name), f"{field}.{name}")
            if value is not None:
                item[name] = value
        sample_rate = _optional_finite_number(raw.get("sample_rate_hz"), f"{field}.sample_rate_hz")
        if sample_rate is not None:
            if sample_rate <= 0:
                raise TrialTelemetryError(f"{field}.sample_rate_hz must be positive")
            item["sample_rate_hz"] = sample_rate
        fft_size = raw.get("fft_size")
        if fft_size is not None:
            if isinstance(fft_size, bool) or not isinstance(fft_size, int) or fft_size <= 0:
                raise TrialTelemetryError(f"{field}.fft_size must be a positive integer")
            item["fft_size"] = fft_size
        bands = _normalize_bands(raw.get("bands_dbfs"), f"{field}.bands_dbfs")
        if bands:
            item["bands_dbfs"] = bands
        method = raw.get("method")
        if method is not None:
            item["method"] = _non_empty_text(method, f"{field}.method", max_length=120)
        if not any(
            key in item
            for key in (
                "rms_dbfs",
                "peak_dbfs",
                "dominant_frequency_hz",
                "dominant_magnitude_db",
                "bands_dbfs",
            )
        ):
            raise TrialTelemetryError(f"{field} contains no aggregated acoustic features")
        normalized.append(item)
    return normalized


def _normalize_permissions(value: object) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        raise TrialTelemetryError("permissions must explicitly declare every source")
    normalized: dict[str, dict[str, Any]] = {}
    for source in _SOURCES:
        raw = value.get(source)
        if not isinstance(raw, Mapping):
            raise TrialTelemetryError(f"permissions.{source} must be an object")
        requested = raw.get("requested")
        granted = raw.get("granted")
        state = raw.get("state")
        if type(requested) is not bool or type(granted) is not bool:
            raise TrialTelemetryError(
                f"permissions.{source} requiere requested y granted booleanos"
            )
        if not isinstance(state, str) or state not in _PERMISSION_STATES:
            raise TrialTelemetryError(f"permissions.{source}.state is invalid")
        if granted and (not requested or state != "granted"):
            raise TrialTelemetryError(f"permissions.{source} declara granted de forma incoherente")
        if state == "granted" and not granted:
            raise TrialTelemetryError(f"permissions.{source}.state granted requiere granted=true")
        item: dict[str, Any] = {
            "requested": requested,
            "granted": granted,
            "state": state,
        }
        for key in ("api", "reason"):
            if key in raw and raw[key] is not None:
                item[key] = _non_empty_text(raw[key], f"permissions.{source}.{key}", max_length=160)
        normalized[source] = item
    return normalized


def _normalize_capabilities(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TrialTelemetryError("capabilities must be an object")
    normalized: dict[str, Any] = {}
    if "secure_context" in value:
        if type(value["secure_context"]) is not bool:
            raise TrialTelemetryError("capabilities.secure_context must be a boolean")
        normalized["secure_context"] = value["secure_context"]
    for source in _SOURCES:
        raw = value.get(source)
        if raw is None:
            continue
        if not isinstance(raw, Mapping) or type(raw.get("available")) is not bool:
            raise TrialTelemetryError(f"capabilities.{source} must declare available")
        item = {"available": raw["available"]}
        if raw.get("reason") is not None:
            item["reason"] = _non_empty_text(
                raw["reason"],
                f"capabilities.{source}.reason",
                max_length=160,
            )
        normalized[source] = item
    return normalized


def _scalar_stats(values: Sequence[float]) -> dict[str, float] | None:
    if not values:
        return None
    mean = sum(values) / len(values)
    return {
        "mean": mean,
        "min": min(values),
        "max": max(values),
        "rms": math.sqrt(sum(value * value for value in values) / len(values)),
    }


def _vector_magnitudes(samples: Iterable[Mapping[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for sample in samples:
        vector = sample.get(key)
        if isinstance(vector, Mapping):
            axes = [vector[axis] for axis in ("x", "y", "z") if axis in vector]
            if axes:
                values.append(math.sqrt(sum(value * value for value in axes)))
    return values


def _timeline(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {"sample_count": 0, "first_t_ms": None, "last_t_ms": None, "duration_ms": 0.0}
    first = float(samples[0]["t_ms"])
    last = float(samples[-1]["t_ms"])
    return {
        "sample_count": len(samples),
        "first_t_ms": first,
        "last_t_ms": last,
        "duration_ms": max(0.0, last - first),
    }


def aggregate_motion(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize motion samples without retaining another copy of their vectors."""

    result = _timeline(samples)
    result.update(
        {
            "linear_acceleration_magnitude_mps2": _scalar_stats(
                _vector_magnitudes(samples, "linear_acceleration_mps2")
            ),
            "acceleration_including_gravity_magnitude_mps2": _scalar_stats(
                _vector_magnitudes(samples, "acceleration_including_gravity_mps2")
            ),
            "rotation_rate_magnitude_dps": _scalar_stats(
                _vector_magnitudes(samples, "rotation_rate_dps")
            ),
        }
    )
    return result


def aggregate_orientation(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize orientation angles and their observed ranges."""

    result = _timeline(samples)
    result["absolute_sample_count"] = sum(1 for sample in samples if sample.get("absolute") is True)
    for angle in ("alpha_deg", "beta_deg", "gamma_deg"):
        result[angle] = _scalar_stats(
            [float(sample[angle]) for sample in samples if angle in sample]
        )
    return result


def aggregate_audio_features(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize feature windows; raw waveform data is never accepted here."""

    result = _timeline(samples)
    rms_values = [float(sample["rms_dbfs"]) for sample in samples if "rms_dbfs" in sample]
    peak_values = [float(sample["peak_dbfs"]) for sample in samples if "peak_dbfs" in sample]
    dominant = [sample for sample in samples if "dominant_frequency_hz" in sample]
    result.update(
        {
            "mean_rms_dbfs": sum(rms_values) / len(rms_values) if rms_values else None,
            "peak_rms_dbfs": max(rms_values) if rms_values else None,
            "peak_dbfs": max(peak_values) if peak_values else None,
            "dominant_frequency_hz": (
                max(
                    dominant,
                    key=lambda sample: sample.get("dominant_magnitude_db", float("-inf")),
                )["dominant_frequency_hz"]
                if dominant
                else None
            ),
            "dominant_magnitude_db": (
                max((float(sample["dominant_magnitude_db"]) for sample in dominant), default=None)
            ),
        }
    )
    band_values: dict[str, list[float]] = {}
    for sample in samples:
        bands = sample.get("bands_dbfs")
        if isinstance(bands, Mapping):
            for name, value in bands.items():
                band_values.setdefault(str(name), []).append(float(value))
    result["mean_bands_dbfs"] = {
        name: sum(values) / len(values) for name, values in sorted(band_values.items())
    }
    return result


def _generated_degradation(
    permissions: Mapping[str, Mapping[str, Any]],
    motion: Sequence[Mapping[str, Any]],
    orientation: Sequence[Mapping[str, Any]],
    audio: Sequence[Mapping[str, Any]],
) -> list[str]:
    sample_counts = {"motion": len(motion), "orientation": len(orientation), "audio": len(audio)}
    reasons: list[str] = []
    for source in _SOURCES:
        permission = permissions[source]
        if permission["state"] != "granted":
            reasons.append(f"{source}:{permission['state']}")
        if sample_counts[source] == 0:
            reasons.append(f"{source}:no_samples")
    return reasons


def _normalize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if _raw_audio_present(payload):
        raise TrialTelemetryError(
            "The export contains raw audio; only aggregated features are accepted"
        )
    if payload.get("schema") != TRIAL_TELEMETRY_SCHEMA:
        raise TrialTelemetryError("schema de trial telemetry no soportado")
    trial_id = _trial_id(payload.get("trial_id"))
    started_at = _timestamp(payload.get("started_at_utc"), "started_at_utc")
    ended_at = _timestamp(payload.get("ended_at_utc"), "ended_at_utc", required=False)
    if ended_at is not None and datetime.fromisoformat(
        ended_at.replace("Z", "+00:00")
    ) < datetime.fromisoformat(started_at.replace("Z", "+00:00")):
        raise TrialTelemetryError("ended_at_utc must not precede started_at_utc")

    permissions = _normalize_permissions(payload.get("permissions"))
    privacy = payload.get("privacy")
    if not isinstance(privacy, Mapping) or privacy.get("raw_audio_saved") is not False:
        raise TrialTelemetryError("privacy.raw_audio_saved must be false")
    audio_storage = privacy.get("audio_storage", "aggregated_metrics_only")
    if audio_storage not in {"aggregated_metrics_only", "aggregated_features_only"}:
        raise TrialTelemetryError("privacy.audio_storage must declare aggregated metrics")

    samples = payload.get("samples")
    if not isinstance(samples, Mapping):
        raise TrialTelemetryError("samples must be an object")
    motion = _normalize_motion(samples.get("motion", []), trial_id)
    orientation = _normalize_orientation(samples.get("orientation", []), trial_id)
    audio = _normalize_audio(samples.get("audio_features", []), trial_id)

    if motion and not permissions["motion"]["granted"]:
        raise TrialTelemetryError("motion samples exist without granted permission")
    if orientation and not permissions["orientation"]["granted"]:
        raise TrialTelemetryError("orientation samples exist without granted permission")
    if audio and not permissions["audio"]["granted"]:
        raise TrialTelemetryError("audio features exist without granted permission")

    capabilities = _normalize_capabilities(payload.get("capabilities"))
    degradation = _generated_degradation(permissions, motion, orientation, audio)
    return {
        "schema": TRIAL_TELEMETRY_SCHEMA,
        "source": TRIAL_TELEMETRY_SOURCE,
        "trial_id": trial_id,
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "permissions": permissions,
        "capabilities": capabilities,
        "privacy": {
            "raw_audio_saved": False,
            "audio_storage": "aggregated_metrics_only",
        },
        "samples": {
            "motion": motion,
            "orientation": orientation,
            "audio_features": audio,
        },
        "metrics": {
            "motion": aggregate_motion(motion),
            "orientation": aggregate_orientation(orientation),
            "audio": aggregate_audio_features(audio),
        },
        "degradation": degradation,
    }


def validate_trial_telemetry(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a normalized, safe copy or raise :class:`TrialTelemetryError`."""

    if not isinstance(payload, Mapping):
        raise TrialTelemetryError("trial telemetry must be an object")
    normalized = _normalize_payload(payload)
    # Buffer overflow is evidence about acquisition quality, not a successful
    # measurement. Preserve it instead of silently dropping browser counters.
    if "dropped_samples" in payload:
        dropped = payload["dropped_samples"]
        if not isinstance(dropped, Mapping) or set(dropped) != {"motion", "orientation", "audio"}:
            raise TrialTelemetryError("Invalid dropped_samples")
        if any(type(value) is not int or value < 0 for value in dropped.values()):
            raise TrialTelemetryError("dropped_samples requiere enteros no negativos")
        normalized["dropped_samples"] = dict(dropped)
    return normalized


def build_trial_telemetry(
    *,
    trial_id: str,
    started_at_utc: str,
    ended_at_utc: str | None,
    permissions: Mapping[str, Any],
    motion: Sequence[Mapping[str, Any]] | None = None,
    orientation: Sequence[Mapping[str, Any]] | None = None,
    audio_features: Sequence[Mapping[str, Any]] | None = None,
    capabilities: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the same normalized export contract used by the web collector."""

    payload = {
        "schema": TRIAL_TELEMETRY_SCHEMA,
        "source": TRIAL_TELEMETRY_SOURCE,
        "trial_id": trial_id,
        "started_at_utc": started_at_utc,
        "ended_at_utc": ended_at_utc,
        "permissions": permissions,
        "capabilities": capabilities or {},
        "privacy": {"raw_audio_saved": False, "audio_storage": "aggregated_metrics_only"},
        "samples": {
            "motion": list(motion or []),
            "orientation": list(orientation or []),
            "audio_features": list(audio_features or []),
        },
    }
    return validate_trial_telemetry(payload)


def audit_trial_telemetry(payload: object) -> dict[str, Any]:
    """Audit an export without raising or retaining raw audio data."""

    if not isinstance(payload, Mapping):
        return {
            "schema": TRIAL_TELEMETRY_SCHEMA,
            "trial_id": None,
            "motion_samples": 0,
            "orientation_samples": 0,
            "audio_feature_samples": 0,
            "issues": ["trial_telemetry_must_be_object"],
            "eligible_as_trial_telemetry": False,
        }

    samples = payload.get("samples")
    motion = samples.get("motion", []) if isinstance(samples, Mapping) else []
    orientation = samples.get("orientation", []) if isinstance(samples, Mapping) else []
    audio = samples.get("audio_features", []) if isinstance(samples, Mapping) else []
    issues: list[str] = []
    if _raw_audio_present(payload):
        issues.append("raw_audio_must_not_be_present")
    try:
        normalized = validate_trial_telemetry(payload)
    except TrialTelemetryError as exc:
        issues.append(str(exc))
        normalized = None
    result: dict[str, Any] = {
        "schema": TRIAL_TELEMETRY_SCHEMA,
        "trial_id": payload.get("trial_id"),
        "motion_samples": len(motion) if isinstance(motion, list) else 0,
        "orientation_samples": len(orientation) if isinstance(orientation, list) else 0,
        "audio_feature_samples": len(audio) if isinstance(audio, list) else 0,
        "issues": list(dict.fromkeys(issues)),
        "eligible_as_trial_telemetry": not issues,
    }
    if normalized is not None:
        result["metrics"] = normalized["metrics"]
        result["degradation"] = normalized["degradation"]
    return result


__all__ = [
    "MAX_AUDIO_FEATURES",
    "MAX_MOTION_SAMPLES",
    "MAX_ORIENTATION_SAMPLES",
    "TRIAL_TELEMETRY_SCHEMA",
    "TrialTelemetryError",
    "aggregate_audio_features",
    "aggregate_motion",
    "aggregate_orientation",
    "audit_trial_telemetry",
    "build_trial_telemetry",
    "validate_trial_telemetry",
]
