"""Public distribution artifacts, source parity, licensing and safety boundaries."""

import importlib.util
import io
import json
from pathlib import Path
import struct
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "channel_builder", ROOT / "tools/build_distribution.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture(scope="module")
def bundles():
    return module.build(ROOT)


def test_bundles_reproduce_exactly(bundles):
    for path, value in bundles.items():
        assert (ROOT / path).read_bytes() == value, path


@pytest.mark.parametrize("family", ["Firefox", "Chromium"])
def test_extension_permissions_and_source(bundles, family):
    with zipfile.ZipFile(
        io.BytesIO(
            bundles[f"distribution/packages/KlipperLearn-Calibration-Review-{family}-1.0.0.zip"]
        )
    ) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["permissions"] == []
        assert "host_permissions" not in manifest
        assert "content_scripts" not in manifest
        assert "connect-src 'none'" in manifest["content_security_policy"]["extension_pages"]
        assert (
            archive.read("core.js")
            == (ROOT / "reference/core.js").read_text(encoding="utf-8").encode()
        )
        assert "MIT" in archive.read("LICENSE.txt").decode()
        assert b"fetch(" not in archive.read("review.js")
        assert b"eval(" not in archive.read("review.js")
        assert b"innerHTML" not in archive.read("review.js")
        assert b"serviceWorker.register" not in archive.read("background.js")
        assert not any(name.endswith(".exe") or name.endswith(".py") for name in archive.namelist())
        if family == "Firefox":
            assert manifest["browser_specific_settings"]["gecko"][
                "data_collection_permissions"
            ] == {"required": ["none"]}
            assert manifest["background"] == {"scripts": ["background.js"]}
        else:
            assert manifest["background"] == {"service_worker": "background.js"}


def test_pwa_manifest_and_cache_are_scope_bound(bundles):
    prefix = "docs/review/"
    manifest = json.loads(bundles[prefix + "manifest.webmanifest"])
    assert manifest["scope"] == "./" and manifest["start_url"] == "./index.html"
    sw = bundles[prefix + "service-worker.js"].decode()
    assert "event.request.method !== 'GET'" in sw
    assert "if (!allowed.has(url.href)) return;" in sw
    assert "addAll([...allowed])" in sw
    assert "session.json" not in sw and "postMessage" not in sw
    assert "localStorage" not in bundles[prefix + "review.js"].decode()
    for size in [192, 512]:
        raw = bundles[prefix + f"icons/icon{size}.png"]
        assert struct.unpack(">II", raw[16:24]) == (size, size)


def test_model_bytes_and_validation_disclosure(bundles):
    raw = bundles["distribution/packages/KlipperLearn-Calibration-Card-Community-Kit.zip"]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        asset = json.loads(archive.read("asset.json"))
        mesh = archive.read("adjustment-card.stl")
        assert mesh == (ROOT / "src/klipperlearn/mobile_app/adjustment-card.stl").read_bytes()
        (triangles,) = struct.unpack("<I", mesh[80:84])
        assert triangles == 7756 and len(mesh) == 84 + 50 * triangles
        assert asset["license"] == "GPL-3.0-or-later"
        assert not asset["matching_photograph_included"]
        assert not asset["physical_print_verified_for_this_exact_asset"]
        assert not asset["exclusive_distribution"]
        assert not any(p.endswith((".gcode", ".jpg", ".png")) for p in archive.namelist())
        assert len(archive.read("trial-worksheet.csv").decode().splitlines()) == 1


def test_no_store_approval_inferred_from_artifacts(bundles):
    manifest = json.loads(bundles["distribution/packages/manifest.json"])
    assert not manifest["store_signed"] and not manifest["store_published"]
    assert len(manifest["packages"]) == 4
    channels = json.loads((ROOT / "distribution/channels.json").read_text())
    assert channels["paid_actions_authorized"] is False
    by_id = {c["id"]: c for c in channels["channels"]}
    assert by_id["google-play"]["registration_payment_required"] is True
    assert by_id["chrome-web-store"]["registration_payment_required"] is True
    assert by_id["edge-addons"]["registration_payment_required"] is False
    assert all(
        not c["submitted"] and not c["accepted"]
        for c in channels["channels"]
        if c["id"] != "web-app"
    )
