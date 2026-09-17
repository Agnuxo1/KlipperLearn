"""OctoPrint plugin entry point for local KlipperLearn evidence manifests."""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any

import octoprint.plugin
from octoprint.events import Events

from .core import CaptureCancelled, build_file_manifest, build_print_manifest, store_manifest

_FILE_EVENT = Events.FILE_ADDED
_PRINT_EVENTS = {
    Events.PRINT_STARTED,
    Events.PRINT_DONE,
    Events.PRINT_FAILED,
    Events.PRINT_CANCELLED,
}
_STOP = object()


class KlipperLearnEvidencePlugin(
    octoprint.plugin.StartupPlugin,
    octoprint.plugin.ShutdownPlugin,
    octoprint.plugin.EventHandlerPlugin,
):
    """Capture local evidence in a bounded daemon worker without changing printer state."""

    def __init__(self) -> None:
        self._tasks: queue.Queue[object] = queue.Queue(maxsize=32)
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def on_after_startup(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="KlipperLearnEvidence",
            daemon=True,
        )
        self._worker.start()
        self._logger.info("KlipperLearn Evidence capture is active in read-only mode")

    def on_shutdown(self) -> None:
        self._stop.set()
        try:
            self._tasks.put_nowait(_STOP)
        except queue.Full:
            pass
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=2.0)

    def on_event(self, event: str, payload: dict[str, Any] | None) -> None:
        if event != _FILE_EVENT and event not in _PRINT_EVENTS:
            return
        task = (str(event), dict(payload or {}))
        try:
            self._tasks.put_nowait(task)
        except queue.Full:
            self._logger.warning("Evidence queue is full; dropping event %s", event)

    def _manifest_directory(self) -> Path:
        return Path(self.get_plugin_data_folder()) / "manifests"

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                task = self._tasks.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if task is _STOP:
                    return
                event, payload = task
                if event == _FILE_EVENT:
                    self._capture_file_added(payload)
                else:
                    self._capture_print_event(event, payload)
            except CaptureCancelled:
                return
            except Exception:
                self._logger.exception("Evidence capture failed")
            finally:
                self._tasks.task_done()

    def _capture_file_added(self, payload: dict[str, Any]) -> None:
        storage = str(payload.get("storage", ""))
        storage_path = payload.get("path")
        if storage != "local" or not isinstance(storage_path, str) or not storage_path:
            return
        disk_path = self._file_manager.path_on_disk(storage, storage_path)
        manifest = build_file_manifest(
            storage,
            storage_path,
            disk_path,
            cancel=self._stop,
        )
        try:
            store_manifest(self._manifest_directory(), "file-added", manifest)
        except FileExistsError:
            self._logger.debug("Evidence already exists for %s", storage_path)

    def _capture_print_event(self, event: str, payload: dict[str, Any]) -> None:
        manifest = build_print_manifest(event, payload)
        try:
            store_manifest(self._manifest_directory(), f"print-{event}", manifest)
        except FileExistsError:
            self._logger.debug("Duplicate print event evidence ignored: %s", event)


__plugin_name__ = "KlipperLearn Evidence"
__plugin_description__ = (
    "Creates local read-only evidence manifests without changing G-code or printer state."
)
__plugin_author__ = "Francisco Angulo de Lafuente and KlipperLearn contributors"
__plugin_url__ = "https://github.com/Agnuxo1/KlipperLearn"
__plugin_license__ = "GPL-3.0-or-later"
__plugin_pythoncompat__ = ">=3.9,<4"
__plugin_implementation__ = None


def __plugin_load__() -> None:
    """Instantiate the plugin only when OctoPrint loads it through its plugin framework."""
    global __plugin_implementation__
    __plugin_implementation__ = KlipperLearnEvidencePlugin()
