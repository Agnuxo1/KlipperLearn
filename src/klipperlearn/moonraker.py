from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote
from .config import _validate_http_url
from .http_readonly import read_http_bytes


class MoonrakerClient:
    """Read-only Moonraker client used by the observer."""

    def __init__(self, base_url: str, timeout_seconds: float = 10) -> None:
        self.base_url = _validate_http_url("moonraker.url", base_url)
        self.timeout_seconds = timeout_seconds

    def get_json(self, path: str) -> dict[str, Any]:
        if (
            not isinstance(path, str)
            or not path.startswith("/")
            or path.startswith("//")
            or "#" in path
        ):
            raise ValueError("Moonraker path must be relative and start with '/'.")
        content = read_http_bytes(
            f"{self.base_url}{path}", limit=4 * 1024 * 1024, timeout=self.timeout_seconds
        )
        result = json.loads(content.decode("utf-8"))
        if not isinstance(result, dict):
            raise ValueError("Moonraker must return a JSON object")
        return result

    def printer_status(self) -> dict[str, Any]:
        objects = "webhooks&print_stats&toolhead&extruder&heater_bed&fan&gcode_move"
        return self.get_json(f"/printer/objects/query?{objects}")["result"]["status"]

    def file_metadata(self, filename: str) -> dict[str, Any]:
        encoded = quote(filename, safe="")
        return self.get_json(f"/server/files/metadata?filename={encoded}")["result"]
