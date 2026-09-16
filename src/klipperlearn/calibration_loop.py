"Bounded local experimental planning for the next trial.\n\nThis module operates only on reviewed observations. It has no machine access,\nno default machine configuration, and neither constructs nor executes G-code.\nProposals remain within the maximum step specified in the input payload.\n"

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
import math
from pathlib import Path
from typing import Any


MODEL_KIND = "experimental_quadratic_surrogate"
PARAMETERS = frozenset(
    {
        "pressure_advance",
        "extrusion_factor",
        "accel_mm_s2",
        "shaper_freq_x",
        "shaper_freq_y",
    }
)
SOURCE_KINDS = frozenset({"reviewed_chart", "dedicated_accelerometer", "phone_frame"})
SOURCE_FIELDS = frozenset({"kind", "axis", "scale_verified", "speed_verified"})
TRIAL_FIELDS = frozenset({"id", "value", "loss", "reviewed", "session_id"})
TOP_LEVEL_FIELDS = frozenset(
    {
        "parameter",
        "bounds",
        "maximum_step",
        "current",
        "trials",
        "source",
        # These two fields are documentation metadata only; they never affect a proposal.
        "synthetic",
        "note",
    }
)
REQUIRED_FIELDS = frozenset({"parameter", "bounds", "maximum_step", "current", "trials"})
RIDGE = 1e-8
_EPSILON = 1e-12


def _error(message: str) -> None:
    raise ValueError(message)


def _finite_number(value: Any, field: str) -> float:
    """Validate a JSON number and return it as a finite float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _error(f"{field} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        _error(f"{field} must be a finite number")
    return number


def _non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _error(f"{field} must be non-empty text")
    return value


def _validate_bounds(value: Any) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        _error("bounds must have the form [lo, hi]")
    lo = _finite_number(value[0], "bounds[0]")
    hi = _finite_number(value[1], "bounds[1]")
    if not lo < hi:
        _error("bounds requiere lo < hi")
    return lo, hi


def _validate_source(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _error("source must be an object")
    unknown = set(value) - SOURCE_FIELDS
    if unknown:
        _error("source contiene campos no soportados: " + ", ".join(sorted(map(str, unknown))))
    missing = SOURCE_FIELDS - set(value)
    if missing:
        _error("source carece de campos: " + ", ".join(sorted(missing)))

    kind = value["kind"]
    axis = value["axis"]
    if not isinstance(kind, str):
        _error("source.kind must be text")
    if not isinstance(axis, str):
        _error("source.axis must be text")
    if kind not in SOURCE_KINDS:
        _error("source.kind is not permitted")
    if axis not in {"x", "y"}:
        _error("source.axis must be 'x' or 'y'")
    if type(value["scale_verified"]) is not bool:
        _error("source.scale_verified must be a boolean")
    if type(value["speed_verified"]) is not bool:
        _error("source.speed_verified must be a boolean")
    return {
        "kind": kind,
        "axis": axis,
        "scale_verified": value["scale_verified"],
        "speed_verified": value["speed_verified"],
    }


def _validate_trials(
    value: Any,
    lo: float,
    hi: float,
) -> tuple[list[dict[str, Any]], int]:
    """Validate all records, returning only reviewed records for fitting."""
    if not isinstance(value, list):
        _error("trials must be a list")

    seen_ids: set[str] = set()
    reviewed_trials: list[dict[str, Any]] = []
    unreviewed_count = 0
    for index, raw_trial in enumerate(value):
        field_prefix = f"trials[{index}]"
        if not isinstance(raw_trial, Mapping):
            _error(f"{field_prefix} must be an object")
        unknown = set(raw_trial) - TRIAL_FIELDS
        if unknown:
            _error(
                f"{field_prefix} contiene campos no soportados: "
                + ", ".join(sorted(map(str, unknown)))
            )
        missing = TRIAL_FIELDS - set(raw_trial)
        if missing:
            _error(f"{field_prefix} carece de campos: " + ", ".join(sorted(missing)))

        trial_id = _non_empty_string(raw_trial["id"], f"{field_prefix}.id")
        if trial_id in seen_ids:
            _error(f"id de trial duplicado: {trial_id}")
        seen_ids.add(trial_id)

        trial_value = _finite_number(raw_trial["value"], f"{field_prefix}.value")
        if not lo <= trial_value <= hi:
            _error(f"{field_prefix}.value must be within bounds")
        loss = _finite_number(raw_trial["loss"], f"{field_prefix}.loss")
        if not 0.0 <= loss <= 1.0:
            _error(f"{field_prefix}.loss must be between 0 and 1")
        if type(raw_trial["reviewed"]) is not bool:
            _error(f"{field_prefix}.reviewed must be a boolean")
        session_id = _non_empty_string(raw_trial["session_id"], f"{field_prefix}.session_id")

        normalized = {
            "id": trial_id,
            "value": trial_value,
            "loss": loss,
            "reviewed": raw_trial["reviewed"],
            "session_id": session_id,
        }
        if raw_trial["reviewed"]:
            reviewed_trials.append(normalized)
        else:
            # An unreviewed record is provenance, not training evidence.
            unreviewed_count += 1

    return reviewed_trials, unreviewed_count


def _shaper_source_reason(parameter: str, source: dict[str, Any] | None) -> str | None:
    """Return a blocking reason when source evidence cannot support a shaper axis."""
    if not parameter.startswith("shaper_freq_"):
        return None
    expected_axis = parameter[-1]
    if source is None:
        return (
            "A valid source is missing for the shaper parameter; no usable evidence is available."
        )
    if source["axis"] != expected_axis:
        return f"source.axis must match axis {expected_axis} for the shaper parameter."
    if source["kind"] == "phone_frame":
        return "phone_frame is never a valid input-shaping evidence source."
    if source["kind"] == "reviewed_chart":
        if not (source["scale_verified"] and source["speed_verified"]):
            return "A reviewed_chart for input shaping requires verified scale and speed."
        return None
        # A dedicated accelerometer is accepted after the axis check. Its own
        # calibration/provenance is represented by the source kind.
    return None


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= _EPSILON * max(1.0, abs(left), abs(right))


def _solve_3x3(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Solve a 3x3 system by Gaussian elimination with partial pivoting."""
    augmented = [list(row) + [rhs[index]] for index, row in enumerate(matrix)]
    for column in range(3):
        pivot_row = max(range(column, 3), key=lambda row: abs(augmented[row][column]))
        pivot = augmented[pivot_row][column]
        if not math.isfinite(pivot) or abs(pivot) <= _EPSILON:
            return None
        if pivot_row != column:
            augmented[column], augmented[pivot_row] = augmented[pivot_row], augmented[column]

        for row in range(column + 1, 3):
            factor = augmented[row][column] / augmented[column][column]
            for item in range(column, 4):
                augmented[row][item] -= factor * augmented[column][item]

    solution = [0.0, 0.0, 0.0]
    for row in range(2, -1, -1):
        remainder = augmented[row][3] - sum(
            augmented[row][column] * solution[column] for column in range(row + 1, 3)
        )
        diagonal = augmented[row][row]
        if not math.isfinite(diagonal) or abs(diagonal) <= _EPSILON:
            return None
        solution[row] = remainder / diagonal
        if not math.isfinite(solution[row]):
            return None
    return solution


def _fit_standardized_quadratic(
    trials: list[dict[str, Any]],
) -> tuple[list[float], float, float, float] | None:
    """Fit loss ~ 1 + z + z² using a small ridge-regularized normal system."""
    values = [trial["value"] for trial in trials]
    magnitude = max(abs(value) for value in values)
    if not math.isfinite(magnitude) or magnitude <= 0.0:
        return None
        # Work in [-1, 1] before subtracting or squaring. Finite JSON numbers can
        # still overflow when summed or squared (for example, values near 1e308).
    normalized_values = [value / magnitude for value in values]
    center = sum(normalized_values) / len(normalized_values)
    variance = sum((value - center) ** 2 for value in normalized_values) / len(normalized_values)
    scale = math.sqrt(variance)
    if not math.isfinite(center) or not math.isfinite(scale) or scale <= 0.0:
        return None

    normal = [[0.0, 0.0, 0.0] for _ in range(3)]
    rhs = [0.0, 0.0, 0.0]
    for trial, normalized_value in zip(trials, normalized_values):
        z = (normalized_value - center) / scale
        features = (1.0, z, z * z)
        for row in range(3):
            rhs[row] += features[row] * trial["loss"]
            for column in range(3):
                normal[row][column] += features[row] * features[column]

                # Ridge keeps the tiny surrogate numerically well behaved. The intercept
                # is regularized too because this is a deliberately small, self-contained
                # model rather than a statistical estimator with a fitted prior.
    for diagonal in range(3):
        normal[diagonal][diagonal] += RIDGE
    coefficients = _solve_3x3(normal, rhs)
    if coefficients is None:
        return None
    return coefficients, center, scale, magnitude


def _best_observed(trials: list[dict[str, Any]], current: float) -> dict[str, Any] | None:
    if not trials:
        return None
    best_index, best = min(
        enumerate(trials),
        key=lambda item: (item[1]["loss"], abs(item[1]["value"] - current), item[0]),
    )
    del best_index  # The index is used only for deterministic tie-breaking.
    return dict(best)


def _local_direction(trials: list[dict[str, Any]], current: float) -> int | None:
    """Choose one side from observed losses without claiming an improvement."""
    left = [trial for trial in trials if trial["value"] < current]
    right = [trial for trial in trials if trial["value"] > current]
    if not left and not right:
        return None
    if not left:
        return 1
    if not right:
        return -1

    left_best = min(left, key=lambda trial: (trial["loss"], abs(trial["value"] - current)))
    right_best = min(right, key=lambda trial: (trial["loss"], abs(trial["value"] - current)))
    if left_best["loss"] < right_best["loss"] - _EPSILON:
        return -1
    if right_best["loss"] < left_best["loss"] - _EPSILON:
        return 1

        # Equal side minima do not establish a preference. Select the nearer
        # measured side deterministically while still making only one step.
    left_distance = abs(left_best["value"] - current)
    right_distance = abs(right_best["value"] - current)
    return -1 if left_distance <= right_distance else 1


def _local_candidate(
    direction: int,
    current: float,
    lo: float,
    hi: float,
    maximum_step: float,
) -> float | None:
    safe_lo = max(lo, current - maximum_step)
    safe_hi = min(hi, current + maximum_step)
    candidate = current + direction * maximum_step
    candidate = min(safe_hi, max(safe_lo, candidate))
    if _close(candidate, current):
        return None
    return candidate


def _result(
    *,
    status: str,
    parameter: str,
    trained_on_n: int,
    best_observed: dict[str, Any] | None,
    next_trial: dict[str, Any] | None,
    rationale: str,
    flags: list[str],
) -> dict[str, Any]:
    return {
        "status": status,
        "parameter": parameter,
        "model_kind": MODEL_KIND,
        "trained_on_n": trained_on_n,
        "best_observed": best_observed,
        "next_trial": next_trial,
        "validated_on_printer": False,
        "automatic_control": False,
        "rationale": rationale,
        "flags": flags,
    }


def propose_next_trial(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return one bounded next trial, or a blocked result when evidence is insufficient.

    The accepted payload has ``parameter``, ``bounds`` as ``[lo, hi]``,
    ``maximum_step``, ``current`` and a list of trial records. ``source`` is
    required for shaper parameters. Records with ``reviewed`` false are
    validated for provenance but excluded from the fit.
    """
    if not isinstance(payload, Mapping):
        _error("payload must be an object")
    unknown = set(payload) - TOP_LEVEL_FIELDS
    if unknown:
        _error("payload contiene campos no soportados: " + ", ".join(sorted(map(str, unknown))))
    missing = REQUIRED_FIELDS - set(payload)
    if missing:
        _error("payload carece de campos: " + ", ".join(sorted(missing)))

    parameter = payload["parameter"]
    if not isinstance(parameter, str):
        _error("parameter must be text")
    if parameter not in PARAMETERS:
        _error("parameter is not permitted")
    lo, hi = _validate_bounds(payload["bounds"])
    maximum_step = _finite_number(payload["maximum_step"], "maximum_step")
    if maximum_step <= 0.0:
        _error("maximum_step must be positive")
    current = _finite_number(payload["current"], "current")
    if not lo <= current <= hi:
        _error("current must be within bounds")

    if "synthetic" in payload and type(payload["synthetic"]) is not bool:
        _error("synthetic must be a boolean")
    if "note" in payload and not isinstance(payload["note"], str):
        _error("note must be text")

    source = _validate_source(payload["source"]) if "source" in payload else None
    source_reason = _shaper_source_reason(parameter, source)
    reviewed_trials, unreviewed_count = _validate_trials(payload["trials"], lo, hi)
    best = _best_observed(reviewed_trials, current)
    common_flags = ["reviewed_evidence_only", "no_printer_validation", "no_automatic_control"]
    if payload.get("synthetic", False):
        common_flags.append("synthetic_evidence")
    if unreviewed_count:
        common_flags.append("unreviewed_trials_ignored")

    if source_reason is not None:
        return _result(
            status="blocked",
            parameter=parameter,
            trained_on_n=0,
            best_observed=None,
            next_trial=None,
            rationale=source_reason + " No suggestion is generated.",
            flags=common_flags + ["invalid_shaper_source"],
        )

    distinct_values = {trial["value"] for trial in reviewed_trials}
    if len(distinct_values) < 3:
        return _result(
            status="blocked",
            parameter=parameter,
            trained_on_n=len(reviewed_trials),
            best_observed=best,
            next_trial=None,
            rationale=(
                "At least three distinct reviewed observation values are required to fit the quadratic surrogate. No suggestion is generated."
            ),
            flags=common_flags + ["insufficient_evidence"],
        )

    fit = _fit_standardized_quadratic(reviewed_trials)
    safe_lo = max(lo, current - maximum_step)
    safe_hi = min(hi, current + maximum_step)
    candidate: float | None = None
    method = ""
    vertex_was_clipped = False
    if fit is not None:
        coefficients, center, scale, magnitude = fit
        curvature = coefficients[2]
        if curvature > _EPSILON:
            vertex_z = -coefficients[1] / (2.0 * curvature)
            normalized_vertex = center + scale * vertex_z
            if math.isfinite(vertex_z) and not math.isnan(normalized_vertex):
                # Convert after the fit is normalized. An infinite physical
                # vertex still has a safe direction to clip, while NaN has no
                # defensible direction at all.
                vertex = normalized_vertex * magnitude
                if math.isfinite(vertex):
                    vertex_for_clipping = vertex
                elif normalized_vertex > 0.0:
                    vertex_for_clipping = math.inf
                else:
                    vertex_for_clipping = -math.inf
                if math.isfinite(vertex_for_clipping):
                    candidate = min(safe_hi, max(safe_lo, vertex_for_clipping))
                else:
                    candidate = safe_hi if vertex_for_clipping > 0.0 else safe_lo
                vertex_was_clipped = not (
                    math.isfinite(vertex_for_clipping) and _close(candidate, vertex_for_clipping)
                )
                if _close(candidate, current):
                    # There is no feasible movement in the model's direction
                    # at a bound. Do not replace it with a potentially
                    # contrary local heuristic.
                    candidate = None
                elif candidate is not None:
                    method = (
                        "quadratic_vertex_clipped" if vertex_was_clipped else "quadratic_vertex"
                    )

    if candidate is None:
        direction = _local_direction(reviewed_trials, current)
        if direction is not None and fit is not None and fit[0][2] > _EPSILON:
            # A convex fit with no feasible movement at the current bound must
            # remain blocked; falling back could reverse the fitted direction.
            direction = None
        if direction is not None:
            candidate = _local_candidate(direction, current, lo, hi, maximum_step)
            if candidate is not None:
                method = "local_exploration_left" if direction < 0 else "local_exploration_right"

    if candidate is None:
        return _result(
            status="blocked",
            parameter=parameter,
            trained_on_n=len(reviewed_trials),
            best_observed=best,
            next_trial=None,
            rationale=(
                "There is no feasible local direction within bounds and maximum_step; abstain rather than invent evidence or claim an optimum."
            ),
            flags=common_flags + ["no_safe_direction"],
        )

    if method == "quadratic_vertex":
        rationale = "The standardized ridge quadratic surrogate found a convex vertex within bounds and current +/- maximum_step. This is an experimental proposal, not a claimed optimum."
        method_flag = "quadratic_vertex"
    elif method == "quadratic_vertex_clipped":
        rationale = "The standardized ridge quadratic surrogate vertex is outside the permitted step; it was clipped to the intersection of bounds and current +/- maximum_step. This is an experimental proposal, not a claimed optimum."
        method_flag = "quadratic_vertex_clipped"
    else:
        direction_text = "left" if method.endswith("left") else "right"
        rationale = (
            f"The surrogate has no usable convex vertex within the permitted step; "
            f"explore one direction ({direction_text}). Available evidence does not establish "
            "this exploratory change as an improvement or an optimum."
        )
        method_flag = "local_exploration"

    return _result(
        status="proposed",
        parameter=parameter,
        trained_on_n=len(reviewed_trials),
        best_observed=best,
        next_trial={"parameter": parameter, "value": candidate},
        rationale=rationale,
        flags=common_flags
        + [
            method_flag,
            *(["exploration_not_demonstrated"] if method.startswith("local_exploration_") else []),
            "no_optimal_claim",
        ],
    )


def main(argv: Sequence[str] | None = None) -> int:
    "Read-only CLI: load JSON and write only the resulting JSON."
    parser = argparse.ArgumentParser(description="Propose a bounded calibration trial")
    parser.add_argument(
        "--input", required=True, help="Path to a JSON payload; use '-' for standard input"
    )
    arguments = parser.parse_args(argv)

    try:
        if arguments.input == "-":
            import sys

            payload = json.load(sys.stdin)
        else:
            payload = json.loads(Path(arguments.input).read_text(encoding="utf-8"))
        result = propose_next_trial(payload)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False))
        return 2

    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
