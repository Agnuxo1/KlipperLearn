"Offline proposals from experiment history.\n\nThis module converts persisted records into input for\ncalibration_loop.propose_next_trial. It does not access the network, alter the\nstore, or control a printer. Proposals are experimental suggestions and are\nnever applied automatically by this module.\n"

from __future__ import annotations

from collections.abc import Iterable, Mapping
import json
import math
from typing import Any

from . import calibration_loop


WEIGHTS_VERSION = "40-60-v1"
_REQUIRED_CONTEXT = frozenset({"printer_id", "model_sha256", "material", "nozzle_mm", "session_id"})
_SHAPER_PARAMETERS = frozenset({"shaper_freq_x", "shaper_freq_y"})


def _error(message: str) -> None:
    raise ValueError(message)


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _error(f"{field} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        _error(f"{field} must be a finite number")
    return number


def _validate_json_value(value: Any, field: str) -> None:
    """Validate the small JSON subset used for exact context comparisons."""

    if value is None or isinstance(value, bool) or isinstance(value, str):
        return
    if type(value) is int:
        return
    if type(value) is float:
        if not math.isfinite(value):
            _error(f"{field} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                _error(f"{field} contains a non-string key")
            _validate_json_value(item, f"{field}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{field}[{index}]")
        return
    _error(f"{field} is not valid JSON")


def _canonical_json(value: Any, field: str) -> str:
    _validate_json_value(value, field)
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} cannot be compared reliably") from exc


def _validate_context(context: Any, index: int) -> dict[str, Any]:
    field = f"records[{index}].context"
    if not isinstance(context, Mapping):
        _error(f"{field} is invalid: an object is required")

    try:
        missing = _REQUIRED_CONTEXT - set(context)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    if missing:
        _error(f"{field} is invalid: missing " + ", ".join(sorted(missing)))

    for key in ("printer_id", "model_sha256", "material", "session_id"):
        value = context[key]
        if not isinstance(value, str) or not value.strip():
            _error(f"{field}.{key} is invalid")
    nozzle = _finite_number(context["nozzle_mm"], f"{field}.nozzle_mm")
    if nozzle <= 0.0:
        _error(f"{field}.nozzle_mm must be positive")

        # Validate extras too: they participate in exact equality and must not be
        # silently discarded or allowed to contain non-deterministic objects.
    _canonical_json(dict(context), field)
    return dict(context)


def _validate_bounds(bounds: Any) -> tuple[float, float]:
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
        _error("bounds must have the form [lo, hi]")
    lo = _finite_number(bounds[0], "bounds[0]")
    hi = _finite_number(bounds[1], "bounds[1]")
    if not lo < hi:
        _error("bounds requiere lo < hi")
    return lo, hi


def _context_signature(context: Mapping[str, Any]) -> str:
    comparable = {key: value for key, value in context.items() if key != "session_id"}
    return _canonical_json(comparable, "context")


def _parameters_signature(parameters: Any, parameter: str) -> str | None:
    if not isinstance(parameters, Mapping):
        return None
    comparable = {key: value for key, value in parameters.items() if key != parameter}
    try:
        return _canonical_json(comparable, "parameters")
    except ValueError:
        return None


def _parameter_value(parameters: Any, parameter: str) -> tuple[float | None, str | None]:
    if not isinstance(parameters, Mapping):
        return None, "invalid_parameters"
    if parameter not in parameters:
        return None, "missing_parameter"
    try:
        return _finite_number(parameters[parameter], f"parameters.{parameter}"), None
    except ValueError:
        return None, "invalid_parameter_value"


def _score_value(record: Mapping[str, Any]) -> tuple[float | None, str | None]:
    # A pending record is provenance only, even if a malformed record happens
    # to carry another field that looks like a score.
    if record.get("status") == "pending" or record.get("score") is None:
        return None, "pending"
    try:
        score = _finite_number(record["score"], "score")
    except (KeyError, ValueError):
        return None, "invalid_score"
    if not 0.0 <= score <= 100.0:
        return None, "invalid_score"
    return score, None


def _synthetic_marker(record: Mapping[str, Any]) -> bool:
    """Read provenance markers only; never interpret ``validated`` as authority."""

    markers: list[bool] = []
    candidates: list[Any] = []
    if "synthetic" in record:
        candidates.append(record["synthetic"])
    evidence = record.get("evidence")
    if isinstance(evidence, Mapping):
        if "synthetic" in evidence:
            candidates.append(evidence["synthetic"])
        data = evidence.get("data")
        if isinstance(data, Mapping) and "synthetic" in data:
            candidates.append(data["synthetic"])

    for marker in candidates:
        if type(marker) is not bool:
            _error("synthetic must be a boolean when present")
        markers.append(marker)
    if len(set(markers)) > 1:
        _error("Un registro contiene marcadores synthetic contradictorios")
    return markers[0] if markers else False


def _add_reason(excluded: dict[str, list[str]], record_id: str, reason: str) -> None:
    reasons = excluded.setdefault(record_id, [])
    if reason not in reasons:
        reasons.append(reason)


def _decorate(
    result: Mapping[str, Any],
    *,
    used_ids: list[str],
    excluded_reasons: dict[str, list[str]],
) -> dict[str, Any]:
    decorated = dict(result)
    # These are explicit contract fields, not values inferred from user
    # evidence. The score is user-supplied/reviewed and never printer validation.
    decorated["based_on_user_supplied_scores"] = True
    decorated["validated_on_printer"] = False
    decorated["automatic_control"] = False
    decorated["used_ids"] = list(used_ids)
    decorated["excluded_reasons"] = {
        record_id: list(reasons) for record_id, reasons in excluded_reasons.items()
    }
    return decorated


def _blocked_shaper(
    parameter: str,
    *,
    used_ids: list[str],
    excluded_reasons: dict[str, list[str]],
) -> dict[str, Any]:
    result = {
        "status": "blocked",
        "parameter": parameter,
        "model_kind": calibration_loop.MODEL_KIND,
        "trained_on_n": 0,
        "best_observed": None,
        "next_trial": None,
        "validated_on_printer": False,
        "automatic_control": False,
        "rationale": (
            "Input shaping is blocked in this API because dedicated evidence is not integrated. No suggestion is generated."
        ),
        "flags": [
            "reviewed_evidence_only",
            "no_printer_validation",
            "no_automatic_control",
            "shaper_evidence_not_integrated",
        ],
    }
    return _decorate(
        result,
        used_ids=used_ids,
        excluded_reasons=excluded_reasons,
    )


def propose_from_history(
    records: Iterable[Mapping[str, Any]],
    anchor_id: str,
    parameter: str,
    bounds: list[float] | tuple[float, float],
    maximum_step: float,
    current: float,
) -> dict[str, Any]:
    """Propose one bounded trial from compatible, reviewed history.

    Records are compared with the anchor using all context fields except
    ``session_id`` and all parameter fields except ``parameter``. At most one
    unambiguous observation from each session reaches the calibration loop.
    """

    if isinstance(records, (str, bytes, Mapping)):
        _error("records must be a sequence of records")
    try:
        materialized = list(records)
    except TypeError as exc:
        raise ValueError("records must be a sequence of records") from exc

    if not isinstance(anchor_id, str) or not anchor_id:
        _error("anchor_id must be non-empty text")
    if not isinstance(parameter, str) or not parameter:
        _error("parameter must be non-empty text")
    lo, hi = _validate_bounds(bounds)
    normalized_step = _finite_number(maximum_step, "maximum_step")
    if normalized_step <= 0.0:
        _error("maximum_step must be positive")
    normalized_current = _finite_number(current, "current")
    if not lo <= normalized_current <= hi:
        _error("current must be within bounds")

    by_id: dict[str, Mapping[str, Any]] = {}
    contexts: dict[str, dict[str, Any]] = {}
    context_signatures: dict[str, str] = {}
    synthetic_values: dict[str, bool] = {}
    for index, record in enumerate(materialized):
        if not isinstance(record, Mapping):
            _error(f"records[{index}] must be an object")
        record_id = record.get("id")
        if not isinstance(record_id, str) or not record_id:
            _error(f"records[{index}].id must be non-empty text")
        if record_id in by_id:
            _error(f"id de record duplicado: {record_id}")

        context = _validate_context(record.get("context"), index)
        by_id[record_id] = record
        contexts[record_id] = context
        context_signatures[record_id] = _context_signature(context)
        synthetic_values[record_id] = _synthetic_marker(record)

    if anchor_id not in by_id:
        _error(f"anchor_id not found: {anchor_id}")
    anchor = by_id[anchor_id]
    anchor_context_signature = context_signatures[anchor_id]
    anchor_parameters_signature = _parameters_signature(anchor.get("parameters"), parameter)
    if anchor_parameters_signature is None:
        _error("The anchor contains invalid parameters")

    excluded: dict[str, list[str]] = {}
    eligible: list[dict[str, Any]] = []

    for record in materialized:
        record_id = record["id"]
        context = contexts[record_id]
        if context_signatures[record_id] != anchor_context_signature:
            _add_reason(excluded, record_id, "context_mismatch")
            continue

        parameters_signature = _parameters_signature(record.get("parameters"), parameter)
        if parameters_signature is None:
            _add_reason(excluded, record_id, "invalid_parameters")
            continue
        if parameters_signature != anchor_parameters_signature:
            _add_reason(excluded, record_id, "parameters_mismatch")
            continue

        score, score_reason = _score_value(record)
        if score_reason is not None:
            _add_reason(excluded, record_id, score_reason)
            continue

        ratings = record.get("ratings")
        if "ratings" not in record or ratings is None:
            _add_reason(excluded, record_id, "missing_ratings")
            continue
        if not isinstance(ratings, Mapping):
            _add_reason(excluded, record_id, "invalid_ratings")
            continue

        if record.get("weights_version") != WEIGHTS_VERSION:
            _add_reason(excluded, record_id, "weights_version_mismatch")
            continue

        value, value_reason = _parameter_value(record.get("parameters"), parameter)
        if value_reason is not None:
            _add_reason(excluded, record_id, value_reason)
            continue
        if score is None or value is None:
            _add_reason(excluded, record_id, "invalid_observation")
            continue
        if not lo <= value <= hi:
            _add_reason(excluded, record_id, "parameter_out_of_bounds")
            continue

        session_id = context["session_id"]
        eligible.append(
            {
                "id": record_id,
                "value": value,
                "loss": 1.0 - (score / 100.0),
                "session_id": session_id,
                "synthetic": synthetic_values[record_id],
            }
        )

    synthetic_kinds = {item["synthetic"] for item in eligible}
    if len(synthetic_kinds) > 1:
        _error("Synthetic and non-synthetic records must not be mixed")

    by_session: dict[str, list[dict[str, Any]]] = {}
    for item in eligible:
        by_session.setdefault(item["session_id"], []).append(item)

    selected: list[dict[str, Any]] = []
    for item in eligible:
        if len(by_session[item["session_id"]]) != 1:
            _add_reason(excluded, item["id"], "ambiguous_session_duplicate")
            continue
        selected.append(item)

    used_ids = [item["id"] for item in selected]
    if parameter in _SHAPER_PARAMETERS:
        # The records above are deliberately not treated as shaper evidence;
        # this API has no integrated dedicated accelerometer/chart pathway.
        return _blocked_shaper(
            parameter,
            used_ids=[],
            excluded_reasons=excluded,
        )

    payload = {
        "parameter": parameter,
        "bounds": [lo, hi],
        "maximum_step": normalized_step,
        "current": normalized_current,
        "trials": [
            {
                "id": item["id"],
                "value": item["value"],
                "loss": item["loss"],
                "reviewed": True,
                "session_id": item["session_id"],
            }
            for item in selected
        ],
    }
    if True in synthetic_kinds:
        payload["synthetic"] = True

    result = calibration_loop.propose_next_trial(payload)
    decorated = _decorate(
        result,
        used_ids=used_ids,
        excluded_reasons=excluded,
    )

    session_count = len({item["session_id"] for item in selected})
    if session_count < 3:
        flags = list(decorated.get("flags", []))
        if "insufficient_sessions" not in flags:
            flags.append("insufficient_sessions")
        decorated["flags"] = flags
    return decorated


__all__ = ["propose_from_history"]
