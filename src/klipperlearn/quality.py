"""Quality scoring for human labels and future local CNN outputs."""

from __future__ import annotations

from collections import defaultdict
from .domain import DEFECT_KEYS, Finding

WEIGHTS = {
    "visible_lamination": 0.6,
    "corner_blobs": 1.0,
    "under_extrusion": 1.0,
    "over_extrusion": 0.9,
    "stringing": 0.5,
    "warping": 1.0,
    "bridging": 0.7,
    "ringing": 0.7,
    "thermal_damage": 0.9,
}


def reviewed_metrics(findings: list[Finding], source: str | None = None) -> set[str]:
    """Return metrics that were explicitly reviewed.

    Missing metrics are deliberately not interpreted as zero-severity findings.
    """
    return {
        finding.metric
        for finding in findings
        if finding.confidence > 0 and (source is None or finding.source == source)
    }


def missing_metrics(findings: list[Finding], source: str | None = None) -> list[str]:
    present = reviewed_metrics(findings, source=source)
    return [metric for metric in DEFECT_KEYS if metric not in present]


def aggregate_findings(findings: list[Finding]) -> dict[str, float]:
    """Confidence-weighted severity for explicitly present defect labels only."""
    totals: dict[str, float] = defaultdict(float)
    confidence: dict[str, float] = defaultdict(float)
    for finding in findings:
        totals[finding.metric] += finding.severity * finding.confidence
        confidence[finding.metric] += finding.confidence
    return {
        metric: totals[metric] / confidence[metric] for metric in DEFECT_KEYS if confidence[metric]
    }


def quality_score(findings: list[Finding], *, require_complete: bool = True) -> float:
    """Return a 0-100 score for an explicitly reviewed set of labels.

    A partial review has no defensible global score because an omitted label means
    "not reviewed", not "defect absent". Callers may opt out only for exploratory
    per-metric work where the incompleteness is displayed separately.
    """
    missing = missing_metrics(findings)
    if require_complete and missing:
        raise ValueError(f"Quality score requires a complete review; missing: {', '.join(missing)}")
    aggregate = aggregate_findings(findings)
    penalty = sum(aggregate[key] * WEIGHTS[key] for key in DEFECT_KEYS) / sum(WEIGHTS.values())
    return round(100.0 * (1.0 - penalty), 2)
