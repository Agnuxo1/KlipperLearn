from pathlib import Path
import unittest

from klipperlearn.trial_telemetry import (
    TRIAL_TELEMETRY_SCHEMA,
    TrialTelemetryError,
    aggregate_audio_features,
    aggregate_motion,
    aggregate_orientation,
    audit_trial_telemetry,
    build_trial_telemetry,
    validate_trial_telemetry,
)


def permissions(*, motion=True, orientation=True, audio=True):
    return {
        "motion": {
            "requested": motion,
            "granted": motion,
            "state": "granted" if motion else "not_requested",
        },
        "orientation": {
            "requested": orientation,
            "granted": orientation,
            "state": "granted" if orientation else "not_requested",
        },
        "audio": {
            "requested": audio,
            "granted": audio,
            "state": "granted" if audio else "not_requested",
        },
    }


def sample_payload():
    return build_trial_telemetry(
        trial_id="trial-001",
        started_at_utc="2026-09-09T10:00:00Z",
        ended_at_utc="2026-09-09T10:00:02Z",
        permissions=permissions(),
        motion=[
            {
                "t_ms": 0,
                "timestamp_utc": "2026-09-09T10:00:00Z",
                "linear_acceleration_mps2": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
            {
                "t_ms": 1000,
                "timestamp_utc": "2026-09-09T10:00:01Z",
                "linear_acceleration_mps2": {"x": 3.0, "y": 4.0, "z": 0.0},
                "rotation_rate_dps": {"x": 0.0, "y": 0.0, "z": 2.0},
            },
        ],
        orientation=[
            {
                "t_ms": 0,
                "timestamp_utc": "2026-09-09T10:00:00Z",
                "alpha_deg": 10.0,
                "beta_deg": 20.0,
                "gamma_deg": -5.0,
                "absolute": True,
            },
            {
                "t_ms": 1000,
                "timestamp_utc": "2026-09-09T10:00:01Z",
                "alpha_deg": 14.0,
                "beta_deg": 18.0,
                "gamma_deg": -4.0,
                "absolute": False,
            },
        ],
        audio_features=[
            {
                "t_ms": 250,
                "timestamp_utc": "2026-09-09T10:00:00.250Z",
                "rms_dbfs": -32.0,
                "peak_dbfs": -12.0,
                "dominant_frequency_hz": 42.0,
                "dominant_magnitude_db": -18.0,
                "bands_dbfs": {"low": -30.0, "mid": -40.0},
                "sample_rate_hz": 48000,
            }
        ],
        capabilities={
            "motion": {"available": True},
            "orientation": {"available": True},
            "audio": {"available": True},
        },
    )


class TrialTelemetryTests(unittest.TestCase):
    def test_builds_trial_bound_timestamps_and_aggregate_metrics(self):
        payload = sample_payload()

        self.assertEqual(payload["schema"], TRIAL_TELEMETRY_SCHEMA)
        self.assertEqual(payload["trial_id"], "trial-001")
        self.assertEqual(payload["metrics"]["motion"]["sample_count"], 2)
        self.assertAlmostEqual(
            payload["metrics"]["motion"]["linear_acceleration_magnitude_mps2"]["max"],
            5.0,
        )
        self.assertEqual(payload["metrics"]["orientation"]["absolute_sample_count"], 1)
        self.assertEqual(payload["metrics"]["audio"]["dominant_frequency_hz"], 42.0)
        for collection in payload["samples"].values():
            for sample in collection:
                self.assertEqual(sample["trial_id"], "trial-001")
                self.assertIn("t_ms", sample)
                self.assertIn("timestamp_utc", sample)

    def test_audio_contract_rejects_raw_audio_and_reports_audit_issue(self):
        payload = sample_payload()
        payload["samples"]["audio_features"][0]["waveform"] = [0.1, 0.2]

        with self.assertRaisesRegex(TrialTelemetryError, "raw audio"):
            validate_trial_telemetry(payload)
        report = audit_trial_telemetry(payload)
        self.assertFalse(report["eligible_as_trial_telemetry"])
        self.assertIn("raw_audio_must_not_be_present", report["issues"])

    def test_unavailable_source_degrades_without_blocking_other_sources(self):
        payload = build_trial_telemetry(
            trial_id="trial-degraded",
            started_at_utc="2026-09-09T10:00:00Z",
            ended_at_utc="2026-09-09T10:00:01Z",
            permissions=permissions(orientation=False, audio=False),
            motion=[
                {
                    "t_ms": 0,
                    "timestamp_utc": "2026-09-09T10:00:00Z",
                    "acceleration_including_gravity_mps2": {"x": 0.0, "y": 0.0, "z": 9.8},
                }
            ],
        )

        self.assertEqual(payload["metrics"]["motion"]["sample_count"], 1)
        self.assertIn("orientation:not_requested", payload["degradation"])
        self.assertIn("audio:no_samples", payload["degradation"])
        self.assertTrue(audit_trial_telemetry(payload)["eligible_as_trial_telemetry"])

    def test_timestamp_order_and_trial_association_are_checked(self):
        payload = sample_payload()
        payload["samples"]["motion"][1]["t_ms"] = -1
        with self.assertRaisesRegex(TrialTelemetryError, "must not be negative"):
            validate_trial_telemetry(payload)

        payload = sample_payload()
        payload["samples"]["orientation"][0]["trial_id"] = "other-trial"
        with self.assertRaisesRegex(TrialTelemetryError, "no coincide"):
            validate_trial_telemetry(payload)

    def test_aggregators_are_safe_for_empty_windows(self):
        self.assertEqual(aggregate_motion([])["sample_count"], 0)
        self.assertEqual(aggregate_orientation([])["absolute_sample_count"], 0)
        self.assertIsNone(aggregate_audio_features([])["dominant_frequency_hz"])

    def test_static_collector_is_opt_in_and_has_no_raw_audio_path(self):
        source = (
            Path(__file__).parents[1] / "src" / "klipperlearn" / "static" / "trial-telemetry.js"
        ).read_text(encoding="utf-8")
        for required in (
            "requestPermissions",
            "requestPermission",
            "getUserMedia",
            "devicemotion",
            "deviceorientation",
            "trial_id",
            "timestamp_utc",
            "raw_audio_saved: false",
        ):
            self.assertIn(required, source)
        self.assertNotIn("MediaRecorder", source)
        self.assertNotIn("fetch(", source)
        self.assertNotIn("XMLHttpRequest", source)


if __name__ == "__main__":
    unittest.main()
