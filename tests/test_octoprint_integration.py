from __future__ import annotations

import importlib
import json
import logging
import queue
import sys
import types
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "integrations" / "octoprint" / "plugin"


def _install_octoprint_stubs(monkeypatch):
    octoprint = types.ModuleType("octoprint")
    plugin = types.ModuleType("octoprint.plugin")
    events = types.ModuleType("octoprint.events")

    class StartupPlugin:
        pass

    class ShutdownPlugin:
        pass

    class EventHandlerPlugin:
        pass

    class Events:
        FILE_ADDED = "FileAdded"
        PRINT_STARTED = "PrintStarted"
        PRINT_DONE = "PrintDone"
        PRINT_FAILED = "PrintFailed"
        PRINT_CANCELLED = "PrintCancelled"

    plugin.StartupPlugin = StartupPlugin
    plugin.ShutdownPlugin = ShutdownPlugin
    plugin.EventHandlerPlugin = EventHandlerPlugin
    events.Events = Events
    octoprint.plugin = plugin
    octoprint.events = events
    monkeypatch.setitem(sys.modules, "octoprint", octoprint)
    monkeypatch.setitem(sys.modules, "octoprint.plugin", plugin)
    monkeypatch.setitem(sys.modules, "octoprint.events", events)
    monkeypatch.syspath_prepend(str(PLUGIN_ROOT))
    sys.modules.pop("octoprint_klipperlearn_evidence", None)
    sys.modules.pop("octoprint_klipperlearn_evidence.core", None)
    return Events


def _load_plugin(monkeypatch):
    events = _install_octoprint_stubs(monkeypatch)
    module = importlib.import_module("octoprint_klipperlearn_evidence")
    module.__plugin_load__()
    instance = module.__plugin_implementation__
    instance._logger = logging.getLogger("test.octoprint.klipperlearn")
    return module, instance, events


def test_file_manifest_hashes_without_leaking_host_path(tmp_path, monkeypatch):
    _install_octoprint_stubs(monkeypatch)
    core = importlib.import_module("octoprint_klipperlearn_evidence.core")
    source = tmp_path / "secret-host-directory" / "cube.gcode"
    source.parent.mkdir()
    source.write_bytes(b"G28\nG1 X1 Y2\n")

    manifest = core.build_file_manifest(
        "local", "calibration/cube.gcode", source, captured_at="2026-09-17T00:00:00Z"
    )
    serialized = json.dumps(manifest, sort_keys=True)

    assert (
        manifest["file"]["sha256"]
        == "36ffb330a51b8dfbf17e387c190560626306714899633fb333dd6c85ef67858c"
    )
    assert manifest["file"]["size_bytes"] == len(source.read_bytes())
    assert manifest["file"]["path"] == "calibration/cube.gcode"
    assert str(source) not in serialized
    assert "G28" not in serialized
    assert manifest["privacy"]["absolute_host_path_included"] is False


def test_print_manifest_keeps_timing_but_filters_user_connector_and_position(monkeypatch):
    _install_octoprint_stubs(monkeypatch)
    core = importlib.import_module("octoprint_klipperlearn_evidence.core")
    payload = {
        "name": "cube.gcode",
        "path": "tests/cube.gcode",
        "origin": "local",
        "size": 1234,
        "time": 91.25,
        "reason": "error",
        "progress": 47.5,
        "owner": "private-user",
        "user": "private-user",
        "connector": "private-connector",
        "position": {"x": 1, "y": 2, "z": 3},
    }
    manifest = core.build_print_manifest("PrintFailed", payload, captured_at="2026-09-17T00:00:00Z")
    serialized = json.dumps(manifest, sort_keys=True)

    assert manifest["print"] == {
        "state": "PrintFailed",
        "elapsed_seconds": 91.25,
        "reason": "error",
        "progress_percent": 47.5,
    }
    assert "private-user" not in serialized
    assert "private-connector" not in serialized
    assert "position" not in serialized


def test_store_manifest_is_immutable(tmp_path, monkeypatch):
    _install_octoprint_stubs(monkeypatch)
    core = importlib.import_module("octoprint_klipperlearn_evidence.core")
    payload = {"schema": core.SCHEMA, "captured_at": "fixed", "value": 1}
    first = core.store_manifest(tmp_path, "Print Done", payload)
    with pytest.raises(FileExistsError):
        core.store_manifest(tmp_path, "Print Done", payload)
    assert json.loads(first.read_text(encoding="utf-8"))["value"] == 1


def test_file_added_runs_in_worker_and_never_mutates_gcode(tmp_path, monkeypatch):
    module, plugin, events = _load_plugin(monkeypatch)
    source = tmp_path / "uploads" / "cube.gcode"
    source.parent.mkdir()
    original = b"M104 S200\nG28\n"
    source.write_bytes(original)

    class FileManager:
        def path_on_disk(self, storage, path):
            assert (storage, path) == ("local", "cube.gcode")
            return str(source)

    plugin._file_manager = FileManager()
    plugin.get_plugin_data_folder = lambda: str(tmp_path / "plugin-data")
    plugin.on_after_startup()
    plugin.on_event(events.FILE_ADDED, {"storage": "local", "path": "cube.gcode"})
    plugin._tasks.join()
    plugin.on_shutdown()

    manifests = list((tmp_path / "plugin-data" / "manifests").glob("file-added-*.json"))
    assert len(manifests) == 1
    assert source.read_bytes() == original
    assert json.loads(manifests[0].read_text(encoding="utf-8"))["file"]["name"] == "cube.gcode"


def test_nonlocal_file_added_is_ignored(tmp_path, monkeypatch):
    module, plugin, events = _load_plugin(monkeypatch)
    plugin.get_plugin_data_folder = lambda: str(tmp_path / "plugin-data")
    plugin._file_manager = types.SimpleNamespace(
        path_on_disk=lambda *_: (_ for _ in ()).throw(AssertionError("must not resolve"))
    )
    plugin.on_after_startup()
    plugin.on_event(events.FILE_ADDED, {"storage": "sdcard", "path": "remote.gcode"})
    plugin._tasks.join()
    plugin.on_shutdown()
    assert not (tmp_path / "plugin-data" / "manifests").exists()


def test_print_done_manifest_is_background_only_and_privacy_filtered(tmp_path, monkeypatch):
    module, plugin, events = _load_plugin(monkeypatch)
    plugin.get_plugin_data_folder = lambda: str(tmp_path / "plugin-data")
    plugin.on_after_startup()
    payload = {
        "origin": "local",
        "path": "cube.gcode",
        "time": 42.0,
        "owner": "alice",
        "connector": "serial-private",
    }
    plugin.on_event(events.PRINT_DONE, payload)
    plugin._tasks.join()
    plugin.on_shutdown()
    manifest_path = next((tmp_path / "plugin-data" / "manifests").glob("print-printdone-*.json"))
    text = manifest_path.read_text(encoding="utf-8")
    assert "alice" not in text and "serial-private" not in text
    assert json.loads(text)["print"]["elapsed_seconds"] == 42.0


def test_queue_full_drops_event_without_blocking(monkeypatch):
    module, plugin, events = _load_plugin(monkeypatch)
    plugin._tasks = queue.Queue(maxsize=1)
    plugin._tasks.put_nowait(("occupied", {}))
    plugin.on_event(events.PRINT_STARTED, {"origin": "local", "path": "cube.gcode"})
    assert plugin._tasks.qsize() == 1
