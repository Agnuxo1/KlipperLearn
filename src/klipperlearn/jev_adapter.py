"""Small, strict adapter for TypeSafe Jev decisions.

Jev receives a compact state and chooses one candidate supplied by KlipperLearn.
It never receives printer credentials, paths or executable commands, and this
module never talks to Klipper.  Physical application remains a separate,
bounded operation in the companion.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


DEFAULT_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
DEFAULT_CONNECTOR_PATH = r"E:\Rescate-C-2026-09-21\Documents\JEV-Orchestrator\connect_jev.bat"
MAX_STATE_BYTES = 512 * 1024
MAX_RESPONSE_BYTES = 512 * 1024
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
SECRET_KEY_RE = re.compile(
    r"(?i)(?:password|passwd|api.?key|access.?token|auth.?token|secret|authorization|private.?key)"
)
SECRET_VALUE_RE = re.compile(r"(?i)(?:sk-|ghp_|jv_live_|apikey_|bearer\s+)[A-Za-z0-9_.:-]{12,}")

# The provider can rank candidates for these values, but only the printer
# controller's narrower allowlist can be applied to Klipper directly.
# (minimum, maximum, largest single-trial step). Steps are sized so that a short
# series of supervised trials (e.g. six bed plots) can still move meaningfully.
PARAMETER_LIMITS: dict[str, tuple[float, float, float]] = {
    "pressure_advance": (0.0, 0.2, 0.02),
    "accel_mm_s2": (100.0, 10000.0, 1000.0),
    "speed_factor_pct": (50.0, 200.0, 25.0),
    "bridge_speed_mm_s": (10.0, 80.0, 10.0),
    "extrusion_factor": (0.8, 1.2, 0.02),
    "flow_multiplier": (0.95, 1.05, 0.005),
    "hotend_temp_c": (180.0, 275.0, 5.0),
    "max_volumetric_flow_mm3_s": (0.1, 100.0, 1.0),
    "outer_speed_mm_s": (1.0, 500.0, 10.0),
    "inner_speed_mm_s": (1.0, 500.0, 10.0),
    "fan_percent": (0.0, 100.0, 50.0),
}


class JEVError(ValueError):
    """Safe contract or transport error; never contains provider secrets."""


class JEVUnavailable(JEVError):
    """No server-side JEV credentials/configuration are available."""


def _finite(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _safe_json(value: Any, *, depth: int = 0) -> None:
    if depth > 12:
        raise JEVError("JEV state is too deeply nested")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or SECRET_KEY_RE.search(key):
                raise JEVError("JEV state contains a forbidden field")
            _safe_json(key, depth=depth + 1)
            _safe_json(item, depth=depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _safe_json(item, depth=depth + 1)
    elif isinstance(value, str):
        if len(value) > 16_384 or SECRET_VALUE_RE.search(value):
            raise JEVError("JEV state contains forbidden text")
        value.encode("utf-8")
    elif value is None or isinstance(value, bool):
        return
    elif _finite(value):
        return
    else:
        raise JEVError("JEV state contains an unsupported value")


def _encoded(value: Any, field: str, limit: int) -> str:
    _safe_json(value)
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise JEVError(f"{field} is not valid JSON") from exc
    if len(raw.encode("utf-8")) > limit:
        raise JEVError(f"{field} exceeds its size limit")
    return raw


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise JEVError("JEV returned duplicate JSON fields")
        result[key] = value
    return result


def _number(value: Any, field: str, low: float, high: float) -> float:
    if not _finite(value) or not low <= float(value) <= high:
        raise JEVError(f"{field} is outside the permitted range")
    return float(value)


def _candidate(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise JEVError("Each JEV candidate must be an object")
    expected = {"id", "parameter", "value", "bounds", "maximum_step", "description"}
    if set(value) != expected:
        raise JEVError("A JEV candidate has missing or unexpected fields")
    identifier = value["id"]
    if not isinstance(identifier, str) or not ID_RE.fullmatch(identifier):
        raise JEVError("JEV candidate id is invalid")
    parameter = value["parameter"]
    if identifier == "no_change":
        if parameter is not None or value["value"] is not None or value["bounds"] is not None:
            raise JEVError("no_change must not contain a printer value")
        maximum_step = 0.0
    else:
        if parameter not in PARAMETER_LIMITS:
            raise JEVError("JEV candidate parameter is not allowlisted")
        low, high, step_limit = PARAMETER_LIMITS[parameter]
        bounds = value["bounds"]
        if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
            raise JEVError("JEV candidate bounds must be [min, max]")
        bound_lo = _number(bounds[0], "candidate bounds", low, high)
        bound_hi = _number(bounds[1], "candidate bounds", low, high)
        if bound_lo >= bound_hi:
            raise JEVError("JEV candidate bounds must be increasing")
        _number(value["value"], "candidate value", bound_lo, bound_hi)
        maximum_step = _number(value["maximum_step"], "candidate maximum_step", 0.0, step_limit)
        if maximum_step <= 0:
            raise JEVError("JEV candidate maximum_step must be positive")
    description = value["description"]
    if not isinstance(description, str) or not 1 <= len(description) <= 512:
        raise JEVError("JEV candidate description is invalid")
    _safe_json(dict(value))
    return {
        "id": identifier,
        "parameter": parameter,
        "value": None if value["value"] is None else float(value["value"]),
        "bounds": None if value["bounds"] is None else [float(value["bounds"][0]), float(value["bounds"][1])],
        "maximum_step": maximum_step,
        "description": description,
    }


def build_decision_request(
    state: Mapping[str, Any] | Sequence[Any] | str,
    candidates: Sequence[Mapping[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Build a token-efficient native Jev request from precomputed evidence."""

    if not isinstance(model, str) or not 1 <= len(model) <= 128 or not ID_RE.fullmatch(model):
        raise JEVError("JEV model is invalid")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise JEVError("JEV candidates must be a sequence")
    normalized = [_candidate(item) for item in candidates]
    if not 2 <= len(normalized) <= 64 or not any(item["id"] == "no_change" for item in normalized):
        raise JEVError("JEV needs 2-64 candidates including no_change")
    if len({item["id"] for item in normalized}) != len(normalized):
        raise JEVError("JEV candidates must have unique ids")
    _encoded(state, "state", MAX_STATE_BYTES)
    criteria = {item["id"]: item["description"] for item in normalized}
    request = {
        "model": model,
        "state": state,
        "questions": {
            "candidate": {
                "type": "choice",
                "instructions": "Choose exactly one candidate. Select no_change if evidence is insufficient or unsafe.",
                "criteria": criteria,
            },
            "accept": {
                "type": "noul",
                "instructions": "Is the selected candidate supported by the supplied comparable evidence and safe to test once?",
            },
        },
    }
    _encoded(request, "JEV request", MAX_STATE_BYTES + 32_768)
    return request


def parse_jev_response(
    response: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    minimum_confidence: float = 0.65,
    minimum_acceptance: float = 0.65,
) -> dict[str, Any]:
    """Convert typed Jev answers into one candidate or an explicit abstention."""

    if not 0 <= minimum_confidence <= 1 or not 0 <= minimum_acceptance <= 1:
        raise JEVError("JEV thresholds must be between 0 and 1")
    if not isinstance(response, Mapping) or not isinstance(response.get("answers"), Mapping):
        raise JEVError("JEV response has no typed answers")
    answers = response["answers"]
    choice = answers.get("candidate")
    accept = answers.get("accept")
    if not isinstance(choice, Mapping) or choice.get("type") != "choice":
        raise JEVError("JEV candidate answer is not a choice")
    if not isinstance(accept, Mapping) or accept.get("type") != "noul":
        raise JEVError("JEV acceptance answer is not a noul")
    identifier = choice.get("choice")
    normalized_candidates = [_candidate(item) for item in candidates]
    candidates_by_id = {item["id"]: item for item in normalized_candidates}
    if identifier not in candidates_by_id:
        raise JEVError("JEV selected an unavailable candidate")
    confidence = _number(choice.get("confidence"), "JEV confidence", 0.0, 1.0)
    acceptance = _number(accept.get("noul"), "JEV acceptance", 0.0, 1.0)
    candidate = candidates_by_id[identifier]
    result = {
        "schema": "klipperlearn.jev-decision/v1",
        "status": "abstain"
        if identifier == "no_change" or confidence < minimum_confidence or acceptance < minimum_acceptance
        else "candidate",
        "candidate": None if identifier == "no_change" else candidate,
        "candidate_id": identifier,
        "confidence": confidence,
        "acceptance": acceptance,
        "model": response.get("model") if isinstance(response.get("model"), str) else None,
        "reason": (
            "JEV selected no_change or did not meet the configured confidence gates."
            if identifier == "no_change" or confidence < minimum_confidence or acceptance < minimum_acceptance
            else "JEV selected one bounded candidate from the supplied evidence."
        ),
    }
    return result


def _connector_command(path: Path, arguments: Sequence[str]) -> list[str]:
    """Build a non-secret command for the local Windows credential connector."""

    command = [str(path), *arguments]
    if os.name == "nt" and path.suffix.lower() in {".bat", ".cmd"}:
        return [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/s",
            "/c",
            subprocess.list2cmdline(command),
        ]
    return command


def _normalize_connector_response(response: Mapping[str, Any]) -> dict[str, Any]:
    """Translate the local connector's compact ``value`` answers to API shape."""

    answers = response.get("answers")
    if not isinstance(answers, Mapping):
        raise JEVError("JEV connector returned no typed answers")
    normalized_answers: dict[str, Any] = {}
    for question_id, answer in answers.items():
        if not isinstance(question_id, str) or not isinstance(answer, Mapping):
            raise JEVError("JEV connector returned malformed answers")
        item = dict(answer)
        if "type" not in item and "value" in item:
            if question_id == "candidate":
                item["type"] = "choice"
                item["choice"] = item["value"]
            elif question_id == "accept":
                item["type"] = "noul"
                item["noul"] = item["value"]
        normalized_answers[question_id] = item
    normalized = dict(response)
    normalized["answers"] = normalized_answers
    return normalized


@dataclass(frozen=True)
class JEVClient:
    """Server-side native Jev client; credentials never leave this process."""

    url: str
    api_key: str
    model: str = DEFAULT_MODEL
    timeout_seconds: float = 15.0
    connector_path: Path | None = None
    profile: str | None = None

    @classmethod
    def from_env(cls) -> "JEVClient | None":
        api_key = os.environ.get("JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY")
        connector_value = os.environ.get("JEV_CONNECTOR_PATH", DEFAULT_CONNECTOR_PATH)
        connector_path = Path(connector_value) if connector_value else None
        if connector_path is not None and not connector_path.is_file():
            connector_path = None
        if not api_key and connector_path is None:
            return None
        url = os.environ.get("JEV_API_URL", DEFAULT_URL)
        model = os.environ.get("JEV_MODEL", DEFAULT_MODEL)
        if not isinstance(url, str) or not url.startswith("https://"):
            raise JEVError("JEV_API_URL must be an HTTPS URL")
        if not isinstance(api_key, str) or not 8 <= len(api_key) <= 4096 or any(c.isspace() for c in api_key):
            if api_key:
                raise JEVError("JEV_API_KEY is invalid")
        if not isinstance(model, str) or not ID_RE.fullmatch(model):
            raise JEVError("JEV_MODEL is invalid")
        profile = os.environ.get("JEV_PROFILE") or None
        if profile is not None and not ID_RE.fullmatch(profile):
            raise JEVError("JEV_PROFILE is invalid")
        return cls(url.rstrip("/"), api_key or "", model, connector_path=connector_path, profile=profile)

    @property
    def configured(self) -> bool:
        return bool(self.api_key or self.connector_path)

    def decide(self, request_payload: Mapping[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise JEVUnavailable("JEV is not configured on this host")
        if self.connector_path is not None and not self.api_key:
            return self._decide_via_connector(request_payload)
        body = _encoded(request_payload, "JEV request", MAX_STATE_BYTES + 32_768).encode("utf-8")
        request = Request(
            self.url,
            data=body,
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=self.timeout_seconds) as result:
                raw = result.read(MAX_RESPONSE_BYTES + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise JEVError("JEV request failed") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise JEVError("JEV response exceeds the size limit")
        try:
            decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
        except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
            raise JEVError("JEV returned invalid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise JEVError("JEV returned a non-object response")
        _safe_json(decoded)
        return dict(decoded)

    def _decide_via_connector(self, request_payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request_payload, Mapping):
            raise JEVError("JEV request must be an object")
        if "state" not in request_payload or "questions" not in request_payload:
            raise JEVError("JEV connector request is missing state or questions")
        if self.connector_path is None:
            raise JEVUnavailable("JEV connector is not configured on this host")

        state_json = _encoded(request_payload["state"], "JEV state", MAX_STATE_BYTES)
        questions_json = _encoded(request_payload["questions"], "JEV questions", 32_768)
        with tempfile.TemporaryDirectory(prefix="klipperlearn-jev-") as directory:
            root = Path(directory)
            state_file = root / "state.json"
            questions_file = root / "questions.json"
            state_file.write_text(state_json, encoding="utf-8")
            questions_file.write_text(questions_json, encoding="utf-8")
            arguments = [
                "query",
                "--state-file",
                str(state_file),
                "--questions-file",
                str(questions_file),
            ]
            if self.profile:
                arguments.extend(("--profile", self.profile))
            try:
                completed = subprocess.run(
                    _connector_command(self.connector_path, arguments),
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                )
            except (OSError, subprocess.SubprocessError, TimeoutError) as exc:
                raise JEVError("JEV connector request failed") from exc
        if completed.returncode != 0:
            raise JEVError("JEV connector request failed")
        raw = completed.stdout.encode("utf-8")
        if len(raw) > MAX_RESPONSE_BYTES:
            raise JEVError("JEV connector response exceeds the size limit")
        try:
            decoded = json.loads(completed.stdout, object_pairs_hook=_unique_pairs)
        except (UnicodeError, ValueError, TypeError, RecursionError) as exc:
            raise JEVError("JEV connector returned invalid JSON") from exc
        if not isinstance(decoded, Mapping) or not isinstance(decoded.get("answers"), Mapping):
            raise JEVError("JEV connector returned no typed answers")
        _safe_json(decoded)
        return _normalize_connector_response(decoded)


__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_URL",
    "JEVClient",
    "JEVError",
    "JEVUnavailable",
    "PARAMETER_LIMITS",
    "build_decision_request",
    "parse_jev_response",
]
