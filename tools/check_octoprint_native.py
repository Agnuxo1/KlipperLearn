#!/usr/bin/env python3
"""Exercise the installed OctoPrint plugin framework with synthetic local events.

Run in a disposable environment containing OctoPrint and our standalone plugin.
No HTTP server, serial port, real printer, user configuration or LAN is used.
This is native plugin-framework acceptance, not web-UI or physical validation.
"""

from __future__ import annotations
import hashlib
import importlib.metadata
import json
import logging
from pathlib import Path
import socket
import tempfile
import time
from types import SimpleNamespace


def main() -> None:
    """Load through the actual plugin manager, emit events and verify local output."""

    def deny(*args, **kwargs):
        raise RuntimeError("Network access is disabled in the native plugin test")

    socket.create_connection = deny
    socket.socket.connect = deny
    import octoprint.plugin
    from octoprint.settings import settings
    from octoprint.events import EventManager, Events

    logging.basicConfig(level=logging.ERROR)
    with tempfile.TemporaryDirectory(prefix="klipperlearn-native-") as temporary:
        root = Path(temporary)
        source = root / "synthetic.gcode"
        raw = b"; synthetic test fixture, never sent to a printer\nG1 X1 Y1\n"
        source.write_bytes(raw)
        settings(init=True, basedir=str(root / "octoprint-home"))
        manager = octoprint.plugin.plugin_manager(
            init=True,
            plugin_folders=[],
            plugin_bases=[octoprint.plugin.OctoPrintPlugin],
            plugin_entry_points=["octoprint.plugin"],
        )
        found = manager.find_plugins()
        if isinstance(found, tuple):
            found = found[0]
        matching = [(name, info) for name, info in found.items() if "klipperlearn" in name]
        if len(matching) != 1:
            raise RuntimeError("Expected exactly one installed KlipperLearn entry point")
        name, info = matching[0]

        def disk_path(storage, relative):
            if storage != "local" or relative != "synthetic.gcode":
                raise ValueError("Only the synthetic storage fixture is accessible")
            return str(source)

        manager.implementation_injects = {
            "data_folder": str(root / "plugin-data"),
            "file_manager": SimpleNamespace(path_on_disk=disk_path),
        }
        manager.plugin_disabled_list = [key for key in found if key != name]
        manager.reload_plugins(initialize_implementations=True)
        implementation = manager.get_plugin_info(name).implementation
        if not isinstance(implementation, octoprint.plugin.EventHandlerPlugin):
            raise RuntimeError("The real framework did not initialize the event handler")
        bus = EventManager()
        implementation.on_after_startup()
        try:
            bus.fire(Events.STARTUP)
            bus.fire(Events.FILE_ADDED, {"storage": "local", "path": "synthetic.gcode"})
            bus.fire(
                Events.PRINT_DONE, {"origin": "local", "path": "synthetic.gcode", "time": 120.0}
            )
            deadline = time.monotonic() + 8
            directory = root / "plugin-data" / "manifests"
            while len(list(directory.glob("*.json"))) < 2 and time.monotonic() < deadline:
                time.sleep(0.05)
            records = [json.loads(p.read_text()) for p in directory.glob("*.json")]
            encoded = json.dumps(records)
            if len(records) != 2 or hashlib.sha256(raw).hexdigest() not in encoded:
                raise RuntimeError("Expected file hash and print event manifests were not written")
            if source.read_bytes() != raw or str(root) in encoded or "G1 X1 Y1" in encoded:
                raise RuntimeError("Source changed or private content leaked into a manifest")
        finally:
            implementation.on_shutdown()
            bus.fire(Events.SHUTDOWN)
            bus._worker.join(timeout=3)
        if implementation._worker.is_alive() or bus._worker.is_alive():
            raise RuntimeError("Native test workers did not terminate")
        print(
            json.dumps(
                {
                    "status": "passed",
                    "octoprint_version": importlib.metadata.version("OctoPrint"),
                    "plugin_version": importlib.metadata.version("OctoPrint-KlipperLearnEvidence"),
                    "entry_point": name,
                    "native_plugin_manager": True,
                    "native_event_manager": True,
                    "manifests": len(records),
                    "synthetic_events": True,
                    "storage_adapter": "temporary fixture",
                    "printer_connected": False,
                    "http_server_started": False,
                    "network_blocked": True,
                }
            )
        )


if __name__ == "__main__":
    main()
