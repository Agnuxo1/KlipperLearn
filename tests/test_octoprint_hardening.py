"""Security regression tests for the independent plugin, not upstream OctoPrint."""

import importlib.util
import json
from pathlib import Path
import threading

import pytest

SPEC = importlib.util.spec_from_file_location(
    "octoprint_test_support", Path(__file__).with_name("test_octoprint_integration.py")
)
helpers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helpers)


def load(monkeypatch):
    helpers._install_octoprint_stubs(monkeypatch)
    import octoprint_klipperlearn_evidence.core as core

    return core


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -1, 10**400, "40"])
def test_invalid_event_metrics_are_omitted(monkeypatch, value):
    core = load(monkeypatch)
    result = core.build_print_manifest("PrintDone", {"time": value, "progress": value})
    assert result["print"] == {"state": "PrintDone"}
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "path",
    [
        "/private/file",
        "C:\\Users\\owner\\secret.gcode",
        "../secret",
        "https://printer.local/token",
        "line\nname",
    ],
)
def test_absolute_traversing_and_injected_names_are_not_serialized(monkeypatch, path):
    result = load(monkeypatch).build_print_manifest(
        "PrintFailed", {"path": path, "reason": "private-token error"}
    )
    assert result["file"]["path"] is None
    assert "private-token" not in json.dumps(result)


def test_hashing_is_bounded_and_cancellable(monkeypatch, tmp_path):
    core = load(monkeypatch)
    source = tmp_path / "file.gcode"
    source.write_bytes(b"G1 X0\n")
    signal = threading.Event()
    signal.set()
    with pytest.raises(core.CaptureCancelled):
        core.hash_regular_file(source, signal)
    monkeypatch.setattr(core, "MAX_FILE_BYTES", 2)
    with pytest.raises(ValueError):
        core.hash_regular_file(source)


def test_nonfinite_manifest_never_creates_an_output(monkeypatch, tmp_path):
    core = load(monkeypatch)
    with pytest.raises(ValueError):
        core.store_manifest(tmp_path / "out", "test", {"value": float("nan")})
    assert not (tmp_path / "out").exists()


def test_shutdown_drops_later_events_and_restart_clears_stale_sentinel(monkeypatch):
    module, instance, events = helpers._load_plugin(monkeypatch)
    instance.on_shutdown()
    count = instance._tasks.qsize()
    instance.on_event(events.PRINT_DONE, {"origin": "local", "path": "example.gcode"})
    assert instance._tasks.qsize() == count
    instance.on_after_startup()
    assert instance._worker.is_alive()
    assert instance._tasks.empty()
    instance.on_shutdown()
    assert not instance._worker.is_alive()


def test_non_dictionary_event_is_ignored_without_logging_payload(monkeypatch):
    module, instance, events = helpers._load_plugin(monkeypatch)
    instance.on_event(events.PRINT_DONE, "private-token")
    assert instance._tasks.empty()
