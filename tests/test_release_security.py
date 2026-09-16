"""Regression tests for the publication security review; no network or hardware."""

import asyncio
from copy import deepcopy
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import Headers

from klipperlearn.__main__ import _is_loopback_host
from klipperlearn.companion import install_companion, _iter_live_frames
from klipperlearn.config import load_settings
from klipperlearn.multimodal_learning import KEYS, fit_model, predict_score, finite
from klipperlearn.request_safety import read_limited_body, decode_json_object, token_matches
from klipperlearn.webapp import create_app

TOKEN = "release-test-token-not-a-real-secret"
AUTH = {"X-KlipperLearn-Token": TOKEN}
JPEG = b"\xff\xd8test fixture only\xff\xd9"


@pytest.mark.parametrize(
    "host,expected",
    [
        ("localhost", True),
        ("127.0.0.1", True),
        ("127.0.3.2", True),
        ("::1", True),
        ("127.attacker.invalid", False),
        ("127.0.0.1.attacker.invalid", False),
        ("0.0.0.0", False),
        ("192.168.50.2", False),
    ],
)
def test_loopback_identification_is_an_address_not_a_prefix(host, expected):
    assert _is_loopback_host(host) is expected


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("observer", "sample_interval_seconds", "nan"),
        ("observer", "sample_interval_seconds", "inf"),
        ("observer", "sample_interval_seconds", "true"),
        ("atlas", "margin_mm", "nan"),
        ("atlas", "cell_width_mm", "inf"),
        ("atlas", "bed_width_mm", "true"),
        ("observer", "save_frames_while_printing", '"false"'),
    ],
)
def test_invalid_toml_values_are_rejected(tmp_path, section, key, value):
    path = tmp_path / "settings.toml"
    path.write_text(
        '[moonraker]\nurl="http://printer.test:7125"\n' + "[" + section + "]\n" + key + "=" + value,
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_settings(path)


@pytest.mark.parametrize(
    "url",
    [
        "http://printer.test:0",
        "http://printer.test:wrong",
        "http://user:secret@printer.test",
        "http://printer.test/?key=secret",
        "http://printer.test/#fragment",
        "file:///private",
        "http://printer.test/path",
    ],
)
def test_unsafe_moonraker_configuration_url_is_rejected(tmp_path, url):
    path = tmp_path / "settings.toml"
    path.write_text("[moonraker]\nurl=" + repr(url), encoding="utf-8")
    with pytest.raises(ValueError):
        load_settings(path)


class StreamRequest:
    def __init__(self, chunks, headers=None):
        self.headers = Headers(headers or {})
        self.chunks = chunks
        self.read_chunks = 0

    async def stream(self):
        for chunk in self.chunks:
            self.read_chunks += 1
            yield chunk


def test_chunked_upload_is_stopped_before_reading_remaining_chunks():
    request = StreamRequest([b"123", b"456", b"never read"])
    with pytest.raises(HTTPException) as error:
        asyncio.run(read_limited_body(request, 5))
    assert error.value.status_code == 413
    assert request.read_chunks == 2


@pytest.mark.parametrize("length", ["-1", "NaN", "9999999999999", "1, 2"])
def test_bad_content_length_is_rejected_before_reading(length):
    request = StreamRequest([b"not read"], {"Content-Length": length})
    with pytest.raises(HTTPException) as error:
        asyncio.run(read_limited_body(request, 100))
    assert error.value.status_code == 400
    assert request.read_chunks == 0


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a":1,"a":2}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":1e999}',
        b"[]",
        b"\xff",
        b'{"a":"\\ud800"}',
        b'{"a":' + b"[" * 80 + b"0" + b"]" * 80 + b"}",
    ],
)
def test_json_rejects_ambiguous_or_nonfinite_values(raw):
    with pytest.raises(HTTPException) as error:
        decode_json_object(raw)
    assert error.value.status_code == 422


def test_unicode_or_oversized_tokens_fail_without_an_exception():
    assert not token_matches("invalid-" + chr(233), TOKEN)
    assert not token_matches("x" * 5000, TOKEN)
    assert not token_matches(None, TOKEN)
    assert token_matches(TOKEN, TOKEN)


def test_private_sessions_require_authentication_and_are_not_cacheable(tmp_path):
    app = create_app(tmp_path / "sessions", tmp_path / "mobile", TOKEN)
    with TestClient(app) as client:
        assert client.get("/sessions").status_code == 401
        assert client.get("/sessions/unknown").status_code == 401
        response = client.get("/sessions", headers=AUTH)
        assert response.status_code == 200
        assert response.json() == []
        assert response.headers["cache-control"] == "no-store"
        duplicate = [("X-KlipperLearn-Token", TOKEN), ("X-KlipperLearn-Token", TOKEN)]
        assert client.get("/sessions", headers=duplicate).status_code == 401
    assert not (tmp_path / "sessions").exists()


def test_camera_expiry_stop_and_cached_startup_never_serve_old_evidence(tmp_path):
    cache = tmp_path / "camera.jpg"
    cache.write_bytes(JPEG)
    app = FastAPI()
    viewer = install_companion(
        app, TOKEN, experiments_root=tmp_path / "experiments", camera_cache_path=cache
    )
    headers = {"X-KlipperLearn-Viewer": viewer}
    with TestClient(app) as client:
        assert client.get("/mobile/api/live/snapshot", headers=headers).status_code == 503
        assert (
            client.put(
                "/mobile/api/live/frame",
                content=JPEG,
                headers={**AUTH, "Content-Type": "image/jpeg"},
            ).status_code
            == 200
        )
        assert client.get("/mobile/api/live/snapshot", headers=headers).status_code == 200
        with patch("klipperlearn.companion.time.monotonic", return_value=1e20):
            assert client.get("/mobile/api/live/snapshot", headers=headers).status_code == 503
        assert client.delete("/mobile/api/live/frame", headers=AUTH).status_code == 200
        assert client.get("/mobile/api/live/snapshot", headers=headers).status_code == 503
        assert client.get("/mobile/api/live/stream", headers=headers).status_code == 503


def test_stalled_stream_ends_at_grace_deadline_without_replaying():
    async def exercise():
        now = [0.0]
        latest = {"jpeg": b"first", "at": 0.0, "seq": 1, "active": True}

        class Request:
            async def is_disconnected(self):
                return False

        async def sleep(_):
            now[0] += 10

        stream = _iter_live_frames(Request(), latest, clock=lambda: now[0], sleep=sleep)
        assert b"first" in await anext(stream)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        assert now[0] <= 40

    asyncio.run(exercise())


def test_bad_json_and_duplicate_tokens_do_not_reach_moonraker(tmp_path):
    calls = []

    def mock(request):
        calls.append(request)
        return httpx.Response(500)

    app = FastAPI()
    install_companion(app, TOKEN, experiments_root=tmp_path, transport=httpx.MockTransport(mock))
    with TestClient(app) as client:
        for raw in [b'{"extruder":NaN,"bed":0}', b'{"filename":"a.gcode","filename":"b.gcode"}']:
            assert (
                client.post("/mobile/api/printer/start", headers=AUTH, content=raw).status_code
                == 422
            )
        duplicate = [("X-KlipperLearn-Token", TOKEN), ("X-KlipperLearn-Token", TOKEN)]
        assert client.post("/mobile/api/printer/home", headers=duplicate).status_code == 401
    assert calls == []


def trained_fixture():
    rows = [
        {
            "trial_id": str(i),
            "session_id": str(i),
            "context_key": "same",
            "human_score": 20 + i * 4,
            "features": {
                "eligible": True,
                "features": {key: float(i) if key == "image_edge" else None for key in KEYS},
            },
        }
        for i in range(16)
    ]
    return fit_model(rows), rows[4]["features"]


@pytest.mark.parametrize("defect", ["nan", "inf", "shape", "zero_scale", "tampered", "bad_version"])
def test_corrupt_models_abstain_instead_of_manufacturing_a_score(defect):
    model, features = trained_fixture()
    assert predict_score(model, features) is not None
    corrupt = deepcopy(model)
    if defect == "nan":
        corrupt["coefficients"][0] = float("nan")
    elif defect == "inf":
        corrupt["scale"][0] = float("inf")
    elif defect == "shape":
        corrupt["median"] = []
    elif defect == "zero_scale":
        corrupt["scale"][0] = 0
    elif defect == "tampered":
        corrupt["coefficients"][0] += 1
    elif defect == "bad_version":
        corrupt["version"] = "unknown"
    assert predict_score(corrupt, features) is None


def test_oversized_integers_are_not_finite_machine_measurements():
    from klipperlearn.adaptive_policy import number

    assert not finite(10**1000)
    assert not number(10**1000)


@pytest.mark.parametrize("version", ["2.2.0", "2.5.1", "2.9.1", "2.10.0rc1", "unknown", ""])
def test_vulnerable_or_unidentified_torch_versions_are_blocked(version):
    from klipperlearn.inference import CheckpointValidationError, require_supported_torch_version

    with pytest.raises(CheckpointValidationError):
        require_supported_torch_version(version)


@pytest.mark.parametrize("version", ["2.10.0", "2.10.0+cpu", "2.14.0+cpu", "3.0.0"])
def test_stable_patched_torch_version_is_accepted(version):
    from klipperlearn.inference import require_supported_torch_version

    require_supported_torch_version(version)


def test_readonly_http_rejects_unsafe_url_before_opening():
    from klipperlearn.http_readonly import read_http_bytes

    with patch("klipperlearn.http_readonly.build_opener") as opener:
        for url in [
            "file:///private",
            "http://user:password@printer.test",
            "http://printer.test:bad",
        ]:
            with pytest.raises(ValueError):
                read_http_bytes(url, limit=100)
        opener.assert_not_called()


def test_readonly_http_response_is_bounded():
    from unittest.mock import MagicMock
    from klipperlearn.http_readonly import read_http_bytes

    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b"123456"
    with patch("klipperlearn.http_readonly.build_opener") as factory:
        factory.return_value.open.return_value = response
        with pytest.raises(ValueError, match="exceeds"):
            read_http_bytes("http://printer.test", limit=5)
    response.read.assert_called_once_with(6)


def test_token_file_creation_is_private_and_never_overwrites(tmp_path, capsys):
    from klipperlearn.__main__ import main

    destination = tmp_path / "private" / "token.txt"
    main(["lan-token", "--output", str(destination)])
    original = destination.read_text(encoding="ascii")
    assert 24 <= len(original.strip()) <= 128
    assert original.strip() not in capsys.readouterr().out
    with pytest.raises(SystemExit, match="left unchanged"):
        main(["lan-token", "--output", str(destination)])
    assert destination.read_text(encoding="ascii") == original
