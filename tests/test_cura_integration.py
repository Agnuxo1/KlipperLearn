"""Contract tests for the Cura post-processing evidence collector."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

SCRIPT = Path(__file__).parents[1] / "integrations" / "cura" / "KlipperLearnEvidence.py"


def load_script():
    """Load the Cura script with minimal API stubs; no Cura install is required."""
    package = "klipperlearn_cura_stub"
    root = types.ModuleType(package)
    root.__path__ = []
    scripts = types.ModuleType(package + ".scripts")
    scripts.__path__ = []
    base = types.ModuleType(package + ".Script")

    class Script:
        output_directory = ""

        def getSettingValueByKey(self, key):
            assert key == "output_directory"
            return self.output_directory

    base.Script = Script
    um = types.ModuleType("UM")
    logger_module = types.ModuleType("UM.Logger")

    class Logger:
        records = []

        @classmethod
        def log(cls, *args):
            cls.records.append(args)

    logger_module.Logger = Logger
    previous = {name: sys.modules.get(name) for name in [package, package + ".scripts", package + ".Script", "UM", "UM.Logger"]}
    try:
        sys.modules[package] = root
        sys.modules[package + ".scripts"] = scripts
        sys.modules[package + ".Script"] = base
        sys.modules["UM"] = um
        sys.modules["UM.Logger"] = logger_module
        spec = importlib.util.spec_from_file_location(package + ".scripts.KlipperLearnEvidence", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module, Logger
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def test_evidence_hash_matches_exact_utf8_stream():
    module, _ = load_script()
    data = [";HEADER\nG28\n", ";LAYER:0\nG1 X1\n", ";LAYER:1\nG1 X2\n"]
    record = module.build_evidence(data)
    import hashlib

    expected = hashlib.sha256("".join(data).encode("utf-8")).hexdigest()
    assert record["sha256_utf8"] == expected
    assert record["byte_count_utf8"] == len("".join(data).encode("utf-8"))
    assert record["segment_count"] == 3
    assert record["layer_marker_count"] == 2
    assert record["final_saved_file_verified"] is False


def test_manifest_contains_no_gcode_or_source_path(tmp_path):
    module, _ = load_script()
    data = [";SECRET_MODEL_NAME\nG1 X10 Y20\n"]
    target = module.write_evidence(data, tmp_path)
    payload = target.read_text(encoding="utf-8")
    parsed = json.loads(payload)
    assert "SECRET_MODEL_NAME" not in payload
    assert str(tmp_path) not in payload
    assert parsed["source_modified"] is False


def test_execute_preserves_list_identity_and_contents(tmp_path):
    module, Logger = load_script()
    script = module.KlipperLearnEvidence()
    script.output_directory = str(tmp_path)
    data = ["G28\n", ";LAYER:0\nG1 X5\n"]
    before = list(data)
    result = script.execute(data)
    assert result is data
    assert data == before
    manifests = list(tmp_path.glob("*.json"))
    assert len(manifests) == 1
    assert any(record[0] == "i" for record in Logger.records)


def test_execute_failure_still_returns_original_data(tmp_path):
    module, Logger = load_script()
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("occupied", encoding="utf-8")
    script = module.KlipperLearnEvidence()
    script.output_directory = str(blocked)
    data = ["G28\n"]
    result = script.execute(data)
    assert result is data
    assert data == ["G28\n"]
    assert any(record[0] == "e" for record in Logger.records)


def test_existing_conflict_is_never_overwritten(tmp_path):
    module, _ = load_script()
    data = ["G28\n"]
    record = module.build_evidence(data)
    target = tmp_path / (record["sha256_utf8"] + ".json")
    target.write_text("conflict", encoding="utf-8")
    with pytest.raises(ValueError, match="conflicting"):
        module.write_evidence(data, tmp_path)
    assert target.read_text(encoding="utf-8") == "conflict"


def test_setting_contract_is_valid_json():
    module, _ = load_script()
    script = module.KlipperLearnEvidence()
    definition = json.loads(script.getSettingDataString())
    assert definition["key"] == "KlipperLearnEvidence"
    assert definition["settings"]["output_directory"]["type"] == "str"
