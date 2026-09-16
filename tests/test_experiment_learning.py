import copy
import math
import unittest

from klipperlearn.experiment_learning import propose_from_history


WEIGHTS = "40-60-v1"


def context(
    session_id: str,
    *,
    printer_id: str = "printer-a",
    model_sha256: str = "model-a",
    material: str = "PLA",
    nozzle_mm: float = 0.4,
    **extras: object,
) -> dict[str, object]:
    return {
        "printer_id": printer_id,
        "model_sha256": model_sha256,
        "material": material,
        "nozzle_mm": nozzle_mm,
        "session_id": session_id,
        **extras,
    }


def record(
    identifier: str,
    session_id: str,
    value: float,
    score: float | None,
    *,
    parameters: dict[str, object] | None = None,
    status: str = "scored",
    ratings: dict[str, int] | None = None,
    weights_version: str = WEIGHTS,
    evidence: dict[str, object] | None = None,
    **context_overrides: object,
) -> dict[str, object]:
    item: dict[str, object] = {
        "id": identifier,
        "context": context(session_id, **context_overrides),
        "parameters": parameters or {"pressure_advance": value, "temperature": 205},
        "score": score,
        "ratings": {"speed": 3, "surface": 3, "geometry": 3} if ratings is None else ratings,
        "weights_version": weights_version,
        "status": status,
    }
    if evidence is not None:
        item["evidence"] = evidence
    return item


def curve_records(
    *,
    parameter: str = "pressure_advance",
    context_kwargs: dict[str, object] | None = None,
) -> list[dict[str, object]]:
    context_kwargs = context_kwargs or {}
    values_and_scores = ((0.25, 20.0), (0.45, 100.0), (0.65, 20.0))
    return [
        record(
            identifier,
            session,
            value,
            score,
            parameters={parameter: value, "temperature": 205},
            **context_kwargs,
        )
        for identifier, session, (value, score) in zip(
            ("a", "b", "c"), ("session-a", "session-b", "session-c"), values_and_scores
        )
    ]


class ExperimentLearningTests(unittest.TestCase):
    def test_isolates_printer_material_model_and_extra_context(self) -> None:
        records = curve_records()
        records.extend(
            [
                record("other-printer", "other-printer-session", 0.45, 0, printer_id="printer-b"),
                record("other-material", "other-material-session", 0.45, 0, material="ABS"),
                record("other-model", "other-model-session", 0.45, 0, model_sha256="model-b"),
                record("other-extra", "other-extra-session", 0.45, 0, chamber="open"),
            ]
        )

        result = propose_from_history(records, "a", "pressure_advance", [0.0, 1.0], 0.1, 0.4)

        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["used_ids"], ["a", "b", "c"])
        for identifier in ("other-printer", "other-material", "other-model", "other-extra"):
            self.assertIn("context_mismatch", result["excluded_reasons"][identifier])

    def test_excludes_confounded_parameters(self) -> None:
        records = curve_records()
        records.append(
            record(
                "confounded",
                "confounded-session",
                0.5,
                0,
                parameters={"pressure_advance": 0.5, "temperature": 215},
            )
        )

        result = propose_from_history(records, "a", "pressure_advance", [0.0, 1.0], 0.1, 0.4)

        self.assertEqual(result["status"], "proposed")
        self.assertNotIn("confounded", result["used_ids"])
        self.assertIn("parameters_mismatch", result["excluded_reasons"]["confounded"])

    def test_missing_ratings_are_excluded(self) -> None:
        records = curve_records()
        records.append(record("missing-rating", "missing-rating-session", 0.55, 100, ratings=None))
        records[-1].pop("ratings")

        result = propose_from_history(records, "a", "pressure_advance", [0.0, 1.0], 0.1, 0.4)

        self.assertEqual(result["status"], "proposed")
        self.assertNotIn("missing-rating", result["used_ids"])
        self.assertIn("missing_ratings", result["excluded_reasons"]["missing-rating"])

    def test_zero_score_is_real_evidence_and_pending_is_ignored(self) -> None:
        records = curve_records()
        records.append(record("zero", "zero-session", 0.8, 0.0))
        records.append(record("pending", "pending-session", 0.9, None, status="pending"))

        result = propose_from_history(records, "a", "pressure_advance", [0.0, 1.0], 0.1, 0.4)

        self.assertEqual(result["status"], "proposed")
        self.assertIn("zero", result["used_ids"])
        self.assertIn("pending", result["excluded_reasons"])
        self.assertIn("pending", result["excluded_reasons"]["pending"])
        self.assertEqual(result["best_observed"]["id"], "b")

    def test_three_sessions_fit_curve_and_carries_explicit_safety_metadata(self) -> None:
        records = curve_records()
        original = copy.deepcopy(records)

        result = propose_from_history(records, "a", "pressure_advance", [0.0, 1.0], 0.1, 0.38)

        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["trained_on_n"], 3)
        self.assertAlmostEqual(result["next_trial"]["value"], 0.45, places=5)
        self.assertTrue(result["based_on_user_supplied_scores"])
        self.assertFalse(result["validated_on_printer"])
        self.assertFalse(result["automatic_control"])
        self.assertEqual(result["used_ids"], ["a", "b", "c"])
        self.assertEqual(records, original)

    def test_one_session_per_observation_excludes_ambiguous_duplicates(self) -> None:
        records = curve_records()
        records.extend(
            [
                record("duplicate-low", "session-a", 0.2, 0),
                record("duplicate-high", "session-a", 0.8, 100),
            ]
        )

        result = propose_from_history(records, "a", "pressure_advance", [0.0, 1.0], 0.1, 0.4)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["used_ids"], ["b", "c"])
        for identifier in ("a", "duplicate-low", "duplicate-high"):
            self.assertIn("ambiguous_session_duplicate", result["excluded_reasons"][identifier])
        self.assertIn("insufficient_sessions", result["flags"])

    def test_shaper_is_gated_even_when_user_evidence_claims_validation(self) -> None:
        records = curve_records(parameter="shaper_freq_x")
        for item in records:
            item["evidence"] = {"validated": True, "dedicated_accelerometer": True}

        result = propose_from_history(records, "a", "shaper_freq_x", [20.0, 100.0], 10.0, 45.0)

        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["next_trial"])
        self.assertEqual(result["used_ids"], [])
        self.assertIn("shaper_evidence_not_integrated", result["flags"])
        self.assertIn("dedicated", result["rationale"])
        self.assertFalse(result["validated_on_printer"])

    def test_rejects_mixed_synthetic_history(self) -> None:
        records = curve_records()
        records[0]["evidence"] = {"synthetic": True}

        with self.assertRaisesRegex(ValueError, "Synthetic.*mixed"):
            propose_from_history(records, "a", "pressure_advance", [0.0, 1.0], 0.1, 0.4)

    def test_rejects_invalid_context_and_duplicate_ids(self) -> None:
        invalid_context = curve_records()
        invalid_context[1]["context"].pop("material")
        with self.assertRaises(ValueError):
            propose_from_history(invalid_context, "a", "pressure_advance", [0.0, 1.0], 0.1, 0.4)

        duplicate_ids = curve_records()
        duplicate_ids[1]["id"] = duplicate_ids[0]["id"]
        with self.assertRaisesRegex(ValueError, "duplicado"):
            propose_from_history(duplicate_ids, "a", "pressure_advance", [0.0, 1.0], 0.1, 0.4)

    def test_requires_finite_bounded_scores_weights_and_parameter_values(self) -> None:
        records = curve_records()
        records.append(record("nan-score", "nan-score-session", 0.8, math.nan))
        records.append(
            record("wrong-weights", "wrong-weights-session", 0.8, 100, weights_version="other")
        )
        records.append(record("nan-parameter", "nan-parameter-session", math.nan, 100))

        result = propose_from_history(records, "a", "pressure_advance", [0.0, 1.0], 0.1, 0.4)

        self.assertEqual(result["status"], "proposed")
        self.assertIn("invalid_score", result["excluded_reasons"]["nan-score"])
        self.assertIn("weights_version_mismatch", result["excluded_reasons"]["wrong-weights"])
        self.assertIn("invalid_parameter_value", result["excluded_reasons"]["nan-parameter"])


if __name__ == "__main__":
    unittest.main()
