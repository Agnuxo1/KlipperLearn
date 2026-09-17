"""Pure configuration generation, injection rejection and safe host inspection."""

import copy
import json

import pytest

from klipperlearn.camera_proxy import (
    main as camera_main,
    private_viewer_header,
    render_proxy,
    webcam_settings,
)
from klipperlearn.ecosystem_evidence import EvidenceError
from klipperlearn.host_preflight import MINIMUMS, evaluate


def spec():
    return {
        "backend_ip": "192.168.50.10",
        "port": 8765,
        "allow_network": "192.168.50.0/24",
        "tls_name": "klipperlearn.internal",
        "ca_certificate": "/etc/klipperlearn/ca.pem",
        "viewer_header": "/etc/nginx/private/klipperlearn-viewer.conf",
    }


def test_proxy_has_only_exact_camera_routes_no_controls_and_no_weak_tls():
    settings = spec()
    original = copy.deepcopy(settings)
    text = render_proxy(settings)
    assert settings == original
    assert text.count("location = /klipperlearn-camera/") == 2
    assert text.count("proxy_pass https://") == 2
    assert "proxy_ssl_verify off" not in text
    assert "proxy_ssl_name klipperlearn.internal;" in text
    assert "proxy_pass_request_headers off;" in text
    assert "limit_except GET { deny all; }" in text
    assert "proxy_cache off;" in text and "no-store" in text
    assert "frame" not in text and "/printer/" not in text
    assert "return 400;" in text and "return 404;" in text


@pytest.mark.parametrize(
    "field,value",
    [
        ("backend_ip", "8.8.8.8"),
        ("backend_ip", "printer.local"),
        ("backend_ip", "169.254.1.1"),
        ("backend_ip", "127.0.0.2"),
        ("port", True),
        ("port", 0),
        ("port", 65536),
        ("allow_network", "0.0.0.0/0"),
        ("allow_network", "192.168.0.0/16"),
        ("allow_network", "192.168.50.2/24"),
        ("tls_name", "192.168.50.10"),
        ("tls_name", "evil;include /etc/passwd;"),
        ("tls_name", "bad\nname"),
        ("tls_name", "*.local"),
        ("ca_certificate", "relative/ca.pem"),
        ("ca_certificate", "/tmp/../../bad"),
        ("viewer_header", "/tmp/$host.conf"),
        ("viewer_header", "/tmp/a;return 200;"),
        ("viewer_header", "/tmp//a"),
    ],
)
def test_configuration_injection_public_upstreams_and_broad_grants_rejected(field, value):
    settings = spec()
    settings[field] = value
    with pytest.raises(EvidenceError):
        render_proxy(settings)


@pytest.mark.parametrize("frontend", ["mainsail", "fluidd"])
def test_frontend_settings_are_read_only_and_token_free(frontend):
    result = webcam_settings(frontend)
    assert result["snapshot_url"].endswith("/snapshot")
    assert result["service"] == "mjpegstreamer" and result["target_fps"] == 1
    assert not result["auto_register"] and not result["printer_control_exposed"]
    assert "token" not in json.dumps(result).lower()


def test_viewer_header_never_contains_control_token_or_overwrites(tmp_path, capsys):
    token = "test-control-token-for-local-unit-tests"
    header = private_viewer_header(token)
    assert token.encode() not in header and b"X-KlipperLearn-Viewer" in header
    path, output = tmp_path / "token.txt", tmp_path / "header.conf"
    path.write_text(token)
    args = ["viewer-header", "--token-file", str(path), "--output", str(output)]
    assert camera_main(args) == 0 and output.read_bytes() == header
    assert camera_main(args) == 2 and output.read_bytes() == header
    assert token not in capsys.readouterr().out


@pytest.mark.parametrize(
    "token", ["", "short", "x" * 129, "some-secret;G28", "x" * 20 + "\n", "é" * 20]
)
def test_invalid_viewer_credentials_rejected(token):
    with pytest.raises(EvidenceError):
        private_viewer_header(token)


def snapshot():
    return {
        "python": [3, 12, 1],
        "system": "Linux",
        "machine": "aarch64",
        "ssl_available": True,
        "disk_free_mib": 4096,
        "packages": {key: ".".join(map(str, value)) for key, value in MINIMUMS.items()},
    }


def test_host_preflight_is_not_hardware_or_installation_approval():
    result = evaluate(snapshot())
    assert result["status"] == "prerequisites_present" and result["linux_host_reported"]
    assert not result["services_inspected"] and not result["installation_performed"]
    assert not result["safe_to_deploy_certified"]


@pytest.mark.parametrize(
    "key,value,blocker",
    [
        ("python", [3, 9, 0], "python_3_11_or_later_required"),
        ("python", [4, 0, 0], "python_3_11_or_later_required"),
        ("ssl_available", False, "ssl_unavailable"),
        ("disk_free_mib", 20, "less_than_512_mib_free"),
    ],
)
def test_preflight_blockers_are_explicit(key, value, blocker):
    item = snapshot()
    item[key] = value
    result = evaluate(item)
    assert result["status"] == "blocked" and blocker in result["blockers"]


def test_missing_packages_do_not_trigger_installation():
    item = snapshot()
    item["packages"] = {"fastapi": "old-or-private-string"}
    result = evaluate(item)
    assert len(result["optional_learning_dependencies_missing"]) == 6
    assert result["status"] == "dependencies_needed"
    assert "private-string" not in json.dumps(result)


@pytest.mark.parametrize(
    "key,value",
    [
        ("python", [True, 12, 0]),
        ("disk_free_mib", True),
        ("disk_free_mib", float("inf")),
        ("ssl_available", "true"),
    ],
)
def test_malformed_preflight_inputs_fail_closed(key, value):
    item = snapshot()
    item[key] = value
    with pytest.raises(EvidenceError):
        evaluate(item)


def test_linux_snapshot_does_not_claim_kiauh_installation():
    data = {
        "python": [3, 11, 0],
        "system": "Linux",
        "machine": "aarch64",
        "ssl_available": True,
        "disk_free_mib": 4096,
        "packages": {},
    }
    report = evaluate(data)
    assert report["linux_host_reported"] is True
    assert report["kiauh_installation_verified"] is False
