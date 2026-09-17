"""Test distributable layouts and reproducibility without installation or networking."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "ecosystem_package_builder", ROOT / "tools/build_ecosystem_packages.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_packages_match_sources_reproducibly():
    first = builder.build_artifacts(ROOT)
    assert first == builder.build_artifacts(ROOT)
    assert len(first) == 6
    manifest = json.loads(first["manifest.json"])
    assert manifest["upstream_registration"] is False
    for row in manifest["archives"]:
        data = first[row["file"]]
        assert hashlib.sha256(data).hexdigest() == row["sha256"]
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            assert set(archive.namelist()) == {e["path"] for e in row["entries"]}
            assert not any(n.startswith(("data/", "work/", ".git/")) for n in archive.namelist())
            for e in row["entries"]:
                assert hashlib.sha256(archive.read(e["path"])).hexdigest() == e["sha256"]


def test_octoprint_has_installable_root_and_single_plugin():
    data = builder.build_artifacts(ROOT)["OctoPrint-KlipperLearnEvidence-0.1.1.zip"]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        text = z.read("pyproject.toml").decode()
        assert 'version = "0.1.1"' in text
        assert '[project.entry-points."octoprint.plugin"]' in text
        assert "COPYING" in z.namelist()
        assert "octoprint_klipperlearn_evidence/__init__.py" in z.namelist()


def test_toolkit_omits_live_controller_and_network_clients():
    data = builder.build_artifacts(ROOT)["KlipperLearn-Ecosystem-Toolkit.zip"]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for forbidden in (
            "companion.py",
            "automatic_print.py",
            "printer_discovery.py",
            "optimizer_mcp.py",
        ):
            assert not any(n.endswith(forbidden) for n in z.namelist())
        assert "klipperlearn/slicer_optimizer.py" in z.namelist()


def test_outputs_are_never_overwritten(tmp_path):
    result = {"test.zip": b"independent output"}
    target = tmp_path / "packages"
    builder.publish_local(target, result)
    with pytest.raises(FileExistsError):
        builder.publish_local(target, result)
    assert (target / "test.zip").read_bytes() == b"independent output"


@pytest.mark.parametrize("name", ["missing.py", "../outside.py"])
def test_missing_or_escaping_source_is_rejected(tmp_path, name):
    with pytest.raises((OSError, ValueError)):
        builder.read_source(tmp_path, name)
