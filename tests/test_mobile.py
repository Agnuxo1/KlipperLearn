import hashlib
from pathlib import Path
import tempfile
import unittest

from klipperlearn.mobile import MOBILE_SENSOR_SCHEMA, MobileInbox, audit_mobile_export


def valid_export() -> dict:
    return {
        "schema": MOBILE_SENSOR_SCHEMA,
        "session": {
            "id": "mobile-test",
            "started_at_utc": "2026-09-01T00:00:00Z",
            "ended_at_utc": "2026-09-01T00:00:01Z",
            "placement": "fixed_top_frame",
        },
        "privacy": {"network_transmission": False, "raw_audio_saved": False},
        "samples": {
            "motion": [
                {"t_ms": 0, "linear_acceleration_mps2": {"x": 0.0, "y": 0.0, "z": 0.0}},
                {"t_ms": 10, "linear_acceleration_mps2": {"x": 0.1, "y": 0.0, "z": 0.0}},
            ],
            "orientation": [],
            "audio_features": [],
        },
        "camera_frames": [],
    }


class MobileSensorAuditTests(unittest.TestCase):
    def test_valid_motion_evidence_is_accepted_without_training_eligibility(self) -> None:
        result = audit_mobile_export(valid_export())
        self.assertTrue(result["eligible_as_sensor_evidence"])
        self.assertFalse(result["training_eligible"])
        self.assertEqual(result["motion_samples"], 2)

    def test_raw_audio_or_invalid_timeline_is_rejected(self) -> None:
        payload = valid_export()
        payload["privacy"]["raw_audio_saved"] = True
        payload["samples"]["motion"][1]["t_ms"] = -1
        result = audit_mobile_export(payload)
        self.assertFalse(result["eligible_as_sensor_evidence"])
        self.assertIn("raw_audio_must_not_be_present", result["issues"])
        self.assertIn("non_monotonic_timestamp:motion:1", result["issues"])

    def test_local_lan_delivery_is_explicit_and_the_inbox_verifies_camera_bytes(self) -> None:
        payload = valid_export()
        frame = b"mobile-camera-frame"
        payload["privacy"]["network_transmission"] = {
            "enabled": True,
            "scope": "local_lan",
            "method": "manual_authenticated_upload",
        }
        payload["camera_frames"] = [
            {
                "filename": "frame-001.jpg",
                "byte_count": len(frame),
                "sha256": hashlib.sha256(frame).hexdigest(),
            }
        ]
        self.assertEqual(audit_mobile_export(payload)["delivery_mode"], "local_lan_manual_upload")
        with tempfile.TemporaryDirectory() as directory:
            inbox = MobileInbox(Path(directory) / "inbox")
            receipt = inbox.store_export(payload)
            retry = inbox.store_export(payload)
            frame_receipt = inbox.store_frame("mobile-test", "frame-001.jpg", frame)
            frame_retry = inbox.store_frame("mobile-test", "frame-001.jpg", frame)

            self.assertFalse(receipt["already_received"])
            self.assertTrue(retry["already_received"])
            self.assertFalse(frame_receipt["already_received"])
            self.assertTrue(frame_retry["already_received"])
            self.assertEqual(
                (
                    Path(directory) / "inbox" / "mobile-test" / "frames" / "frame-001.jpg"
                ).read_bytes(),
                frame,
            )
