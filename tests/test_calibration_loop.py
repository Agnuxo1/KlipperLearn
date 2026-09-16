import math
import unittest

from klipperlearn.calibration_loop import propose_next_trial


def trial(
    identifier: str, value: float, loss: float, *, reviewed: bool = True
) -> dict[str, object]:
    return {
        "id": identifier,
        "value": value,
        "loss": loss,
        "reviewed": reviewed,
        "session_id": "synthetic-session",
    }


def payload(
    parameter: str = "pressure_advance",
    *,
    bounds: list[float] | None = None,
    maximum_step: float = 0.05,
    current: float = 0.38,
    trials: list[dict[str, object]] | None = None,
    source: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "parameter": parameter,
        "bounds": bounds or [0.0, 1.0],
        "maximum_step": maximum_step,
        "current": current,
        "trials": trials
        or [
            trial("a", 0.25, 0.0225),
            trial("b", 0.45, 0.0025),
            trial("c", 0.65, 0.0625),
        ],
        **({"source": source} if source is not None else {}),
    }


class CalibrationLoopTests(unittest.TestCase):
    def test_convex_parabola_proposes_vertex_and_separates_best_observed(self) -> None:
        result = propose_next_trial(payload())

        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["model_kind"], "experimental_quadratic_surrogate")
        self.assertEqual(result["trained_on_n"], 3)
        self.assertEqual(result["best_observed"]["id"], "b")
        self.assertAlmostEqual(result["best_observed"]["value"], 0.45)
        self.assertAlmostEqual(result["next_trial"]["value"], 0.40, places=5)
        self.assertNotEqual(result["best_observed"], result["next_trial"])
        self.assertNotIn("confidence", result)

    def test_insufficient_evidence_is_blocked_without_suggestion(self) -> None:
        result = propose_next_trial(payload(trials=[trial("a", 0.3, 0.1), trial("b", 0.4, 0.2)]))

        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["next_trial"])
        self.assertIn("insufficient_evidence", result["flags"])
        self.assertIn("three", result["rationale"])

    def test_local_proposal_respects_bounds_and_maximum_step(self) -> None:
        result = propose_next_trial(
            payload(
                current=0.5,
                maximum_step=0.1,
                trials=[trial("a", 0.7, 0.08), trial("b", 0.8, 0.01), trial("c", 0.9, 0.06)],
            )
        )

        self.assertEqual(result["status"], "proposed")
        proposed = result["next_trial"]["value"]
        self.assertGreaterEqual(proposed, 0.0)
        self.assertLessEqual(proposed, 1.0)
        self.assertLessEqual(abs(proposed - 0.5), 0.1 + 1e-12)
        self.assertAlmostEqual(proposed, 0.6)

    def test_convex_vertex_outside_step_is_clipped_not_reversed(self) -> None:
        result = propose_next_trial(
            payload(
                current=0.5,
                maximum_step=0.1,
                # loss = (value - 0.65)**2: vertex 0.65 exceeds safe_hi 0.6.
                # The best measured value (0.4) lies in the opposite direction.
                trials=[
                    trial("a", 0.2, 0.2025),
                    trial("b", 0.4, 0.0625),
                    trial("c", 0.95, 0.09),
                ],
            )
        )

        self.assertEqual(result["status"], "proposed")
        self.assertAlmostEqual(result["next_trial"]["value"], 0.6)
        self.assertIn("quadratic_vertex_clipped", result["flags"])

    def test_local_exploration_is_marked_as_not_demonstrated(self) -> None:
        result = propose_next_trial(
            payload(
                current=0.5,
                maximum_step=0.05,
                trials=[trial("a", 0.6, 0.1), trial("b", 0.7, 0.3), trial("c", 0.8, 0.2)],
            )
        )

        self.assertEqual(result["status"], "proposed")
        self.assertIn("exploration_not_demonstrated", result["flags"])
        self.assertIn("does not establish", result["rationale"])
        self.assertNotIn("respaldada por la menor pérdida", result["rationale"])

    def test_rejects_nan_and_duplicate_trial_references(self) -> None:
        with self.assertRaises(ValueError):
            propose_next_trial(payload(maximum_step=math.nan))

        duplicate_trials = [trial("same", 0.2, 0.1), trial("same", 0.4, 0.2), trial("c", 0.6, 0.1)]
        with self.assertRaises(ValueError):
            propose_next_trial(payload(trials=duplicate_trials))

    def test_large_finite_values_do_not_overflow_the_fit(self) -> None:
        for magnitude in (1e200, 1e308):
            result = propose_next_trial(
                payload(
                    bounds=[0.0, magnitude],
                    current=4e-1 * magnitude,
                    maximum_step=1e-1 * magnitude,
                    trials=[
                        trial("a", 2e-1 * magnitude, 0.2),
                        trial("b", 5e-1 * magnitude, 0.0),
                        trial("c", 8e-1 * magnitude, 0.2),
                    ],
                )
            )
            self.assertEqual(result["status"], "proposed")
            self.assertTrue(math.isfinite(result["next_trial"]["value"]))

    def test_unhashable_parameter_source_kind_and_axis_are_value_errors(self) -> None:
        bad_parameter = payload()
        bad_parameter["parameter"] = []
        with self.assertRaises(ValueError):
            propose_next_trial(bad_parameter)

        for field in ("kind", "axis"):
            bad_source = {
                "kind": "reviewed_chart",
                "axis": "x",
                "scale_verified": True,
                "speed_verified": True,
            }
            bad_source[field] = []
            bad_shaper = payload(parameter="shaper_freq_x", source=bad_source)
            with self.assertRaises(ValueError):
                propose_next_trial(bad_shaper)

    def test_unreviewed_records_do_not_become_evidence(self) -> None:
        result = propose_next_trial(
            payload(
                trials=[
                    trial("a", 0.2, 0.1, reviewed=False),
                    trial("b", 0.4, 0.2, reviewed=False),
                    trial("c", 0.6, 0.1, reviewed=False),
                ]
            )
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["trained_on_n"], 0)
        self.assertIsNone(result["best_observed"])
        self.assertIsNone(result["next_trial"])

    def test_synthetic_provenance_is_propagated_as_a_flag(self) -> None:
        synthetic_payload = payload()
        synthetic_payload["synthetic"] = True

        result = propose_next_trial(synthetic_payload)

        self.assertIn("synthetic_evidence", result["flags"])

    def test_phone_frame_is_never_valid_for_shaper(self) -> None:
        result = propose_next_trial(
            payload(
                parameter="shaper_freq_x",
                source={
                    "kind": "phone_frame",
                    "axis": "x",
                    "scale_verified": True,
                    "speed_verified": True,
                },
            )
        )

        self.assertEqual(result["status"], "blocked")
        self.assertIsNone(result["next_trial"])
        self.assertIn("invalid_shaper_source", result["flags"])

    def test_verified_optical_chart_is_accepted_for_matching_shaper_axis(self) -> None:
        result = propose_next_trial(
            payload(
                parameter="shaper_freq_x",
                bounds=[20.0, 100.0],
                current=48.0,
                maximum_step=10.0,
                trials=[trial("a", 35.0, 0.09), trial("b", 50.0, 0.01), trial("c", 65.0, 0.04)],
                source={
                    "kind": "reviewed_chart",
                    "axis": "x",
                    "scale_verified": True,
                    "speed_verified": True,
                },
            )
        )

        self.assertEqual(result["status"], "proposed")
        self.assertIsNotNone(result["next_trial"])
        self.assertLessEqual(abs(result["next_trial"]["value"] - 48.0), 10.0 + 1e-12)


if __name__ == "__main__":
    unittest.main()
