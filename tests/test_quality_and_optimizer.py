import unittest

from klipperlearn.domain import DEFECT_KEYS, Finding, ParameterBounds
from klipperlearn.optimizer import propose_profiles
from klipperlearn.quality import quality_score


class QualityAndOptimizerTests(unittest.TestCase):
    def test_human_evidence_changes_detail_candidate(self) -> None:
        severities = {metric: 0.0 for metric in DEFECT_KEYS}
        severities.update({"corner_blobs": 0.8, "under_extrusion": 0.6})
        findings = [
            Finding(metric, severity, 1.0, "human") for metric, severity in severities.items()
        ]
        result = propose_profiles(findings)
        detail = next(item for item in result["candidates"] if item["name"] == "detail")
        self.assertLess(detail["settings"]["volumetric_flow_mm3_s"], 12.0)
        self.assertGreater(detail["settings"]["pressure_advance"], 0.025)
        self.assertTrue(detail["requires_human_review"])

    def test_quality_score_is_bounded(self) -> None:
        findings = [
            Finding(metric, float(metric == "warping"), 1.0, "human") for metric in DEFECT_KEYS
        ]
        score = quality_score(findings)
        self.assertGreaterEqual(score, 0.0)
        self.assertLess(score, 100.0)

    def test_partial_review_has_no_global_score_or_profile(self) -> None:
        findings = [Finding("warping", 0.2, 1.0, "human")]
        with self.assertRaises(ValueError):
            quality_score(findings)
        with self.assertRaises(ValueError):
            propose_profiles(findings)

    def test_bounds_reject_unsafe_proposal(self) -> None:
        with self.assertRaises(ValueError):
            ParameterBounds().validate({"hotend_temp_c": 300.0})
