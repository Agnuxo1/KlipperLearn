"""Validation for privacy-preserving phone sensor captures.

The mobile application deliberately exports features, not raw microphone audio or
video.  This module reads that evidence without contacting Moonraker or a printer.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

MOBILE_SENSOR_SCHEMA = "klipperlearn.mobile-sensor/v1"
MAX_MOBILE_EXPORT_BYTES = 25 * 1024 * 1024
MAX_MOBILE_FRAME_BYTES = 12 * 1024 * 1024
_SAFE_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


def _is_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_timeline(samples: object, name: str, issues: list[str]) -> int:
    if not isinstance(samples, list):
        issues.append(f"invalid_samples:{name}")
        return 0
    previous = -1.0
    valid = 0
    for index, sample in enumerate(samples):
        if not isinstance(sample, dict) or not _is_finite_number(sample.get("t_ms")):
            issues.append(f"invalid_timestamp:{name}:{index}")
            continue
        timestamp = float(sample["t_ms"])
        if timestamp < 0 or timestamp < previous:
            issues.append(f"non_monotonic_timestamp:{name}:{index}")
        previous = timestamp
        valid += 1
    return valid


def _network_delivery_mode(privacy: dict[str, Any], issues: list[str]) -> str:
    transmission = privacy.get("network_transmission")
    if transmission is False:
        return "manual_download"
    if not isinstance(transmission, dict):
        issues.append("invalid_network_transmission_policy")
        return "invalid"
    if transmission.get("enabled") is not True:
        issues.append("local_lan_upload_must_be_explicitly_enabled")
    if transmission.get("scope") != "local_lan":
        issues.append("network_scope_must_be_local_lan")
    if transmission.get("method") != "manual_authenticated_upload":
        issues.append("network_method_must_be_manual_authenticated_upload")
    return "local_lan_manual_upload"


def audit_mobile_export(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit a mobile-sensor JSON export without changing it or copying its media."""
    issues: list[str] = []
    if payload.get("schema") != MOBILE_SENSOR_SCHEMA:
        issues.append("unsupported_mobile_sensor_schema")

    session = payload.get("session")
    if not isinstance(session, dict):
        issues.append("missing_session")
        session = {}
    for key in ("id", "started_at_utc", "ended_at_utc", "placement"):
        if not session.get(key):
            issues.append(f"missing_session:{key}")

    privacy = payload.get("privacy")
    if not isinstance(privacy, dict):
        issues.append("missing_privacy_declaration")
        privacy = {}
    if privacy.get("raw_audio_saved") is not False:
        issues.append("raw_audio_must_not_be_present")
    delivery_mode = _network_delivery_mode(privacy, issues)

    samples = payload.get("samples")
    if not isinstance(samples, dict):
        issues.append("missing_samples")
        samples = {}
    motion_count = _validate_timeline(samples.get("motion", []), "motion", issues)
    orientation_count = _validate_timeline(samples.get("orientation", []), "orientation", issues)
    audio_count = _validate_timeline(samples.get("audio_features", []), "audio_features", issues)
    if not motion_count and not audio_count:
        issues.append("no_vibration_or_acoustic_evidence")

    for index, feature in enumerate(samples.get("audio_features", [])):
        if not isinstance(feature, dict):
            continue
        if not _is_finite_number(feature.get("sample_rate_hz")) or feature["sample_rate_hz"] <= 0:
            issues.append(f"invalid_audio_sample_rate:{index}")

    return {
        "schema": MOBILE_SENSOR_SCHEMA,
        "mode": "read_only",
        "session_id": session.get("id"),
        "motion_samples": motion_count,
        "orientation_samples": orientation_count,
        "audio_feature_samples": audio_count,
        "camera_frame_count": len(payload.get("camera_frames", []))
        if isinstance(payload.get("camera_frames", []), list)
        else 0,
        "delivery_mode": delivery_mode,
        "issues": issues,
        "eligible_as_sensor_evidence": not issues,
        "training_eligible": False,
        "training_note": (
            "Phone sensor captures are calibration evidence. They are not defect-image training "
            "examples until paired with a reviewed print session."
        ),
    }


def audit_mobile_export_file(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "schema": MOBILE_SENSOR_SCHEMA,
            "mode": "read_only",
            "path": str(source),
            "issues": [f"invalid_mobile_export:{exc}"],
            "eligible_as_sensor_evidence": False,
            "training_eligible": False,
        }
    if not isinstance(payload, dict):
        payload = {}
    result = audit_mobile_export(payload)
    result["path"] = str(source)
    return result


class MobileInbox:
    """Local-only, append-only receiver for explicitly uploaded phone evidence."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    @staticmethod
    def _canonical_bytes(payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    @staticmethod
    def _validate_session_id(session_id: object) -> str:
        if not isinstance(session_id, str) or not _SAFE_SESSION_ID.fullmatch(session_id):
            raise ValueError("Invalid mobile session id.")
        return session_id

    def _session_dir(self, session_id: str) -> Path:
        candidate = (self.root / session_id).resolve()
        if candidate.parent != self.root:
            raise ValueError("Mobile session path escaped the inbox.")
        return candidate

    def store_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Store a validated export once; an identical retry is idempotent."""
        audit = audit_mobile_export(payload)
        if not audit["eligible_as_sensor_evidence"]:
            raise ValueError("Mobile export failed audit: " + ", ".join(audit["issues"]))
        if audit["delivery_mode"] != "local_lan_manual_upload":
            raise ValueError("Local receiver accepts only explicit manual local-LAN uploads.")
        session_id = self._validate_session_id(audit["session_id"])
        encoded = self._canonical_bytes(payload)
        if len(encoded) > MAX_MOBILE_EXPORT_BYTES:
            raise ValueError("Mobile export exceeds the local receiver size limit.")
        digest = hashlib.sha256(encoded).hexdigest()
        self.root.mkdir(parents=True, exist_ok=True)
        target = self._session_dir(session_id)
        sensor_file = target / "sensor.json"
        if target.exists():
            if (
                sensor_file.is_file()
                and hashlib.sha256(sensor_file.read_bytes()).hexdigest() == digest
            ):
                return {
                    "session_id": session_id,
                    "sha256": digest,
                    "already_received": True,
                    "expected_camera_frames": audit["camera_frame_count"],
                }
            raise FileExistsError("A different mobile session already uses this id.")
        target.mkdir()
        try:
            sensor_file.write_bytes(encoded)
        except OSError:
            target.rmdir()
            raise
        return {
            "session_id": session_id,
            "sha256": digest,
            "already_received": False,
            "expected_camera_frames": audit["camera_frame_count"],
        }

    def store_frame(self, session_id: str, filename: str, content: bytes) -> dict[str, Any]:
        """Accept one manually captured JPEG only when its manifest hash matches."""
        session_id = self._validate_session_id(session_id)
        if Path(filename).name != filename or not filename.lower().endswith(".jpg"):
            raise ValueError("Invalid mobile camera frame filename.")
        if len(content) > MAX_MOBILE_FRAME_BYTES:
            raise ValueError("Mobile camera frame exceeds the local receiver size limit.")
        session_dir = self._session_dir(session_id)
        sensor_file = session_dir / "sensor.json"
        if not sensor_file.is_file():
            raise FileNotFoundError("Mobile session was not received.")
        payload = json.loads(sensor_file.read_text(encoding="utf-8"))
        expected = next(
            (
                frame
                for frame in payload.get("camera_frames", [])
                if isinstance(frame, dict) and frame.get("filename") == filename
            ),
            None,
        )
        if not expected:
            raise ValueError("Camera frame was not declared by the mobile export.")
        digest = hashlib.sha256(content).hexdigest()
        if expected.get("sha256") != digest or expected.get("byte_count") != len(content):
            raise ValueError("Camera frame failed size or SHA-256 verification.")
        frame_dir = session_dir / "frames"
        frame_dir.mkdir(exist_ok=True)
        target = frame_dir / filename
        if target.exists():
            if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
                return {"filename": filename, "sha256": digest, "already_received": True}
            raise FileExistsError("A different camera frame already uses this filename.")
        target.write_bytes(content)
        return {"filename": filename, "sha256": digest, "already_received": False}
