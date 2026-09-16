# KlipperLearn Cura post-processing evidence collector
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Francisco Angulo de Lafuente
"""Record a content-addressed manifest without changing Cura's G-code data.

Copy this file into Cura's PostProcessingPlugin/scripts directory. The script
hashes the exact UTF-8 representation received by Cura's post-processing API,
not the final bytes written later by Cura's output stack.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from ..Script import Script
from UM.Logger import Logger

SCHEMA = "klipperlearn.cura-postprocess-evidence.v1"
MAX_BYTES = 512 * 1024 * 1024
DEFAULT_DIRECTORY = Path.home() / "KlipperLearn" / "cura-slice-manifests"


def build_evidence(data: List[str]) -> Dict[str, Any]:
    """Return non-identifying evidence for Cura's current in-memory G-code."""
    if not isinstance(data, list) or not data or not all(isinstance(part, str) for part in data):
        raise ValueError("Cura post-processing data must be a non-empty list of strings.")
    digest = hashlib.sha256()
    byte_count = 0
    layer_markers = 0
    for part in data:
        encoded = part.encode("utf-8")
        byte_count += len(encoded)
        if byte_count > MAX_BYTES:
            raise ValueError("Cura post-processing data exceeds the 512 MiB evidence limit.")
        digest.update(encoded)
        layer_markers += part.count(";LAYER:")
    if byte_count == 0:
        raise ValueError("Cura post-processing data is empty.")
    return {
        "schema": SCHEMA,
        "scope": "cura_postprocessing_input_utf8",
        "sha256_utf8": digest.hexdigest(),
        "byte_count_utf8": byte_count,
        "segment_count": len(data),
        "layer_marker_count": layer_markers,
        "source_modified": False,
        "final_saved_file_verified": False,
        "geometry_verified": False,
        "quality_assessed": False,
        "parameters_inferred": False,
    }


def _safe_output_directory(raw_value: Any) -> Path:
    """Resolve the user-selected directory without accepting an existing file."""
    if raw_value is None or not str(raw_value).strip():
        return DEFAULT_DIRECTORY
    candidate = Path(str(raw_value)).expanduser()
    if candidate.exists() and not candidate.is_dir():
        raise ValueError("The evidence output location must be a directory.")
    return candidate


def write_evidence(data: List[str], output_directory: Path) -> Path:
    """Write a content-addressed manifest without overwriting conflicting data."""
    record = build_evidence(data)
    output_directory.mkdir(parents=True, exist_ok=True)
    target = output_directory / (record["sha256_utf8"] + ".json")
    payload = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if target.exists():
        if target.is_symlink() or target.read_bytes() != payload:
            raise ValueError("A conflicting Cura evidence manifest already exists.")
        return target
    try:
        with target.open("xb") as stream:
            stream.write(payload)
            stream.flush()
    except FileExistsError:
        if target.is_symlink() or target.read_bytes() != payload:
            raise ValueError("A conflicting Cura evidence manifest appeared concurrently.")
    return target


class KlipperLearnEvidence(Script):
    """Cura PostProcessingPlugin script that leaves the supplied G-code unchanged."""

    def getSettingDataString(self) -> str:
        return """{
            "name": "KlipperLearn Evidence (No G-code Changes)",
            "key": "KlipperLearnEvidence",
            "metadata": {},
            "version": 2,
            "settings": {
                "output_directory": {
                    "label": "Evidence output directory",
                    "description": "Directory for content-addressed JSON manifests. Leave empty for ~/KlipperLearn/cura-slice-manifests.",
                    "type": "str",
                    "default_value": ""
                }
            }
        }"""

    def execute(self, data: List[str]) -> List[str]:
        """Record evidence and always return Cura's original list unchanged."""
        try:
            output_directory = _safe_output_directory(self.getSettingValueByKey("output_directory"))
            target = write_evidence(data, output_directory)
            Logger.log("i", "KlipperLearn evidence recorded: %s", target.name)
        except (OSError, ValueError, UnicodeError) as error:
            Logger.log(
                "e",
                "KlipperLearn evidence failed (%s); G-code was left unchanged.",
                type(error).__name__,
            )
        return data
