import json
from pathlib import Path
from unittest.mock import patch

import pytest

from klipperlearn.jev_adapter import (
    JEVClient,
    JEVError,
    build_decision_request,
    parse_jev_response,
)


def candidates():
    return [
        {
            "id": "no_change",
            "parameter": None,
            "value": None,
            "bounds": None,
            "maximum_step": 0,
            "description": "Keep the verified baseline.",
        },
        {
            "id": "pa_plus",
            "parameter": "pressure_advance",
            "value": 0.03,
            "bounds": [0, 0.2],
            "maximum_step": 0.005,
            "description": "Increase pressure advance by one bounded step.",
        },
    ]


def test_native_jev_request_is_compact_and_typed():
    request = build_decision_request(
        {"trial": "a" * 32, "features": {"image_edge": 0.2}, "weights": {"data": 0.4, "human": 0.6}},
        candidates(),
    )
    assert request["model"] == "jev-latest"
    assert request["questions"]["candidate"]["type"] == "choice"
    assert request["questions"]["accept"]["type"] == "noul"
    assert set(request["questions"]["candidate"]["criteria"]) == {"no_change", "pa_plus"}
    json.dumps(request, allow_nan=False)


def test_jev_response_selects_only_supplied_candidate():
    result = parse_jev_response(
        {
            "model": "jev-1.13.0",
            "answers": {
                "candidate": {"type": "choice", "choice": "pa_plus", "confidence": 0.9},
                "accept": {"type": "noul", "noul": 0.8},
            },
        },
        candidates(),
    )
    assert result["status"] == "candidate"
    assert result["candidate"]["parameter"] == "pressure_advance"


def test_jev_abstains_when_confidence_is_low_or_no_change():
    response = {
        "answers": {
            "candidate": {"type": "choice", "choice": "pa_plus", "confidence": 0.4},
            "accept": {"type": "noul", "noul": 0.9},
        }
    }
    assert parse_jev_response(response, candidates())["status"] == "abstain"
    response["answers"]["candidate"]["choice"] = "no_change"
    response["answers"]["candidate"]["confidence"] = 1
    assert parse_jev_response(response, candidates())["candidate"] is None


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: {**value, "parameter": "G1"},
        lambda value: {**value, "value": 999},
        lambda value: {**value, "description": ""},
    ],
)
def test_invalid_candidate_is_rejected(mutator):
    values = candidates()
    values[1] = mutator(values[1])
    with pytest.raises(JEVError):
        build_decision_request({}, values)


def test_forbidden_state_fields_and_duplicate_response_fields_are_rejected():
    with pytest.raises(JEVError):
        build_decision_request({"api_key": "secret"}, candidates())
    with pytest.raises(JEVError):
        JEVClient("https://example.invalid", "safe-key").decide({"x": 1})
    from klipperlearn.jev_adapter import _unique_pairs

    with pytest.raises(JEVError):
        json.loads('{"answers":{},"answers":{}}', object_pairs_hook=_unique_pairs)


def test_client_uses_server_side_bearer_and_returns_typed_body():
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, _limit):
            return b'{"answers":{"candidate":{"type":"choice","choice":"no_change","confidence":1},"accept":{"type":"noul","noul":1}}}'

    class Opener:
        def open(self, request, timeout):
            assert request.get_header("Authorization") == "Bearer server-key-only"
            assert timeout == 15.0
            return Response()

    with patch("klipperlearn.jev_adapter.build_opener", return_value=Opener()):
        result = JEVClient("https://example.invalid", "server-key-only").decide(
            build_decision_request({}, candidates())
        )
    assert result["answers"]["candidate"]["choice"] == "no_change"


def test_client_uses_local_credential_connector_without_exposing_a_key(tmp_path: Path):
    connector = tmp_path / "connect_jev.bat"
    connector.write_text("@echo off", encoding="utf-8")
    client = JEVClient("", "", connector_path=connector, profile="lareliquia")

    def run(command, **kwargs):
        assert kwargs["capture_output"] is True
        command_text = " ".join(command)
        assert "query" in command_text
        assert "lareliquia" in command_text
        return type("Completed", (), {
            "returncode": 0,
            "stdout": json.dumps({
                "status": "connected",
                "model": "jev-1.13.0",
                "answers": {
                    "candidate": {"value": "no_change", "confidence": 1},
                    "accept": {"value": 1},
                },
            }),
        })()

    with patch("klipperlearn.jev_adapter.subprocess.run", side_effect=run):
        result = client.decide(build_decision_request({}, candidates()))
    assert result["status"] == "connected"
    assert result["answers"]["candidate"]["choice"] == "no_change"
    assert result["answers"]["accept"]["noul"] == 1


def test_from_env_discovers_the_local_connector(monkeypatch, tmp_path: Path):
    connector = tmp_path / "connect_jev.bat"
    connector.write_text("@echo off", encoding="utf-8")
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("JEV_CONNECTOR_PATH", str(connector))
    client = JEVClient.from_env()
    assert client is not None
    assert client.configured is True
    assert client.api_key == ""
