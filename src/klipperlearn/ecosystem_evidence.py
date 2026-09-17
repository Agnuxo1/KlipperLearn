"""Offline evidence contracts for Moonraker history and Klipper status.

These functions never discover hosts, fetch URLs or issue printer commands.
Only explicitly allowlisted fields leave the input document. File names,
configuration bodies, macros, users and arbitrary error messages are excluded.
SPDX-License-Identifier: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any

MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_JOBS = 10_000
WORKFLOWS = ("operator_chatgpt", "klipperlearn", "manual", "unknown")
HISTORY_STATES = frozenset(
    (
        "in_progress",
        "completed",
        "cancelled",
        "error",
        "klippy_shutdown",
        "klippy_disconnect",
        "interrupted",
    )
)
WEBHOOK_STATES = frozenset(("ready", "startup", "shutdown", "error"))
PRINT_STATES = frozenset(("standby", "printing", "paused", "complete", "error", "cancelled"))
KINEMATICS = frozenset(
    (
        "cartesian",
        "corexy",
        "corexz",
        "hybrid_corexy",
        "hybrid_corexz",
        "delta",
        "deltesian",
        "polar",
        "rotary_delta",
        "winch",
        "none",
    )
)
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z", re.ASCII)


class EvidenceError(ValueError):
    """An input cannot be interpreted without inventing or exposing evidence."""


def finite_number(value: Any, minimum: float = 0, maximum: float = 1e12) -> float | None:
    """Accept finite real JSON numbers, but not booleans or numeric strings."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and minimum <= number <= maximum else None


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise EvidenceError("A short ASCII identifier is required")
    return value


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("Duplicate JSON keys are not accepted")
        result[key] = value
    return result


def _reject_constant(_value):
    raise EvidenceError("Non-finite JSON is not accepted")


def _validate_json(value: Any, depth: int = 0) -> None:
    if depth > 48:
        raise EvidenceError("JSON nesting is too deep")
    if isinstance(value, str):
        value.encode("utf-8", errors="strict")
    elif value is None or isinstance(value, bool):
        return
    elif isinstance(value, (int, float)):
        try:
            valid = math.isfinite(value)
        except (OverflowError, ValueError):
            valid = False
        if not valid:
            raise EvidenceError("Non-finite JSON is not accepted")
    elif isinstance(value, list):
        for entry in value:
            _validate_json(entry, depth + 1)
    elif isinstance(value, dict):
        for key, entry in value.items():
            if not isinstance(key, str):
                raise EvidenceError("JSON object keys must be strings")
            _validate_json(key, depth + 1)
            _validate_json(entry, depth + 1)
    else:
        raise EvidenceError("Unsupported JSON value")


def load_document(path: str | Path) -> dict:
    """Read bounded regular JSON; reject links, races, duplicate keys and NaN."""
    source = Path(path)
    before = source.lstat()
    if not stat.S_ISREG(before.st_mode) or getattr(before, "st_file_attributes", 0) & 0x400:
        raise EvidenceError("Input must be a regular file, not a link or device")
    if not 0 < before.st_size <= MAX_INPUT_BYTES:
        raise EvidenceError("Input is empty or exceeds 16 MiB")
    with source.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise EvidenceError("Input changed before it was read")
        raw = stream.read(MAX_INPUT_BYTES + 1)
        after = os.fstat(stream.fileno())
    current = source.lstat()
    stamp = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_mode)
    if (
        len(raw) > MAX_INPUT_BYTES
        or stamp(before) != stamp(after)
        or stamp(after) != stamp(current)
    ):
        raise EvidenceError("Input changed while reading")
    try:
        value = json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
        _validate_json(value)
    except (ValueError, UnicodeError, RecursionError, OverflowError):
        raise EvidenceError("Input is not a strict UTF-8 JSON document") from None
    if not isinstance(value, dict):
        raise EvidenceError("Input must be a JSON object")
    return value


def write_new(path: str | Path, content: bytes) -> None:
    """Create one private output exclusively; never overwrite an existing file."""
    target = Path(path)
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise


def _synthetic(document: dict) -> bool:
    """Preserve explicit synthetic provenance; never downgrade a demo to real evidence."""
    if not isinstance(document, dict) or type(document.get("synthetic", False)) is not bool:
        raise EvidenceError("Synthetic provenance must be a boolean")
    return document.get("synthetic", False)


def normalize_history(document: dict, *, printer_id: str, workflow: str) -> dict:
    """Normalize one explicitly identified printer/workflow without scoring quality.

    `count` is preserved as a reported number, not assumed to be the database
    total. Paged exports do not establish collection completeness. Duplicate IDs
    cannot qualify for timing comparison. Completion does not verify a full model.
    """
    synthetic = _synthetic(document)
    printer_id = _identifier(printer_id)
    if workflow not in WORKFLOWS:
        raise EvidenceError("Select a supported evidence workflow")
    body = _object(document.get("result", document))
    jobs = body.get("jobs")
    if not isinstance(jobs, list) or len(jobs) > MAX_JOBS:
        raise EvidenceError("History must contain at most 10000 jobs")
    rows, issues = [], []
    for index, job in enumerate(jobs):
        if not isinstance(job, dict):
            issues.append({"index": index, "reason": "not_an_object"})
            continue
        try:
            job_id = _identifier(job.get("job_id"))
        except EvidenceError:
            issues.append({"index": index, "reason": "invalid_job_id"})
            continue
        flags = []
        status = job.get("status")
        if not isinstance(status, str) or status not in HISTORY_STATES:
            status = "unknown"
            flags.append("unrecognized_status")
        print_time = finite_number(job.get("print_duration"))
        total_time = finite_number(job.get("total_duration"))
        if print_time is None or total_time is None:
            flags.append("invalid_duration")
        elif print_time > total_time:
            flags.append("print_duration_exceeds_total")
        start = finite_number(job.get("start_time"))
        end = finite_number(job.get("end_time"))
        if start is not None and end is not None and end < start:
            flags.append("end_precedes_start")
        if start is None or (end is None and status == "completed"):
            flags.append("missing_or_invalid_timestamps")
        metadata = _object(job.get("metadata"))
        layers = metadata.get("layer_count")
        layers = layers if type(layers) is int and 0 < layers <= 1_000_000 else None
        height = finite_number(metadata.get("layer_height"), 0.001, 10)
        if layers is None or height is None:
            flags.append("layer_metadata_incomplete")
        identity = job.get("exists")
        rows.append(
            {
                "job_id": job_id,
                "printer_id": printer_id,
                "workflow": workflow,
                "status": status,
                "completed": status == "completed",
                "synthetic": synthetic,
                "print_duration_seconds": print_time,
                "total_duration_seconds": total_time,
                "nonprinting_duration_seconds": total_time - print_time
                if print_time is not None and total_time is not None and total_time >= print_time
                else None,
                "filament_used_mm": finite_number(job.get("filament_used")),
                "start_time_unix": start,
                "end_time_unix": end,
                "layer_height_mm": height,
                "layer_count": layers,
                "source_file_exists_unmodified_reported": identity
                if type(identity) is bool
                else None,
                "source_file_identity_verified": False,
                "full_geometry_verified": False,
                "quality_assessed": False,
                "benchmark_eligible": False,
                "timing_eligible": False,
                "issues": flags,
            }
        )
    ids = Counter(row["job_id"] for row in rows)
    blockers = {
        "unrecognized_status",
        "invalid_duration",
        "print_duration_exceeds_total",
        "end_precedes_start",
        "missing_or_invalid_timestamps",
        "duplicate_job_id",
    }
    for row in rows:
        if ids[row["job_id"]] > 1:
            row["issues"].append("duplicate_job_id")
        row["timing_eligible"] = (
            row["completed"]
            and row["print_duration_seconds"] is not None
            and row["print_duration_seconds"] > 0
            and not blockers.intersection(row["issues"])
        )
    reported_count = body.get("count")
    return {
        "schema": "klipperlearn.moonraker-history-review/v1",
        "printer_id": printer_id,
        "workflow": workflow,
        "jobs": rows,
        "synthetic": synthetic,
        "input_job_count": len(jobs),
        "normalized_job_count": len(rows),
        "reported_count": reported_count
        if type(reported_count) is int and reported_count >= 0
        else None,
        "collection_completeness_verified": False,
        "counts_by_status": dict(Counter(row["status"] for row in rows)),
        "invalid_entries": issues,
        "commands_allowed": False,
        "automatic_changes": False,
        "privacy": {
            "filenames_included": False,
            "user_identity_included": False,
            "raw_metadata_included": False,
            "raw_error_messages_included": False,
        },
    }


def status_report(document: dict) -> dict:
    """Describe an already captured Klipper status, never grant actuation rights."""
    synthetic = _synthetic(document)
    body = _object(document.get("result", document))
    status = body.get("status")
    if not isinstance(status, dict):
        raise EvidenceError("Expected a Moonraker result.status object")
    webhooks = _object(status.get("webhooks"))
    raw = webhooks.get("state")
    klipper_state = raw if isinstance(raw, str) and raw in WEBHOOK_STATES else "unknown"
    stats = _object(status.get("print_stats"))
    raw = stats.get("state")
    print_state = raw if isinstance(raw, str) and raw in PRINT_STATES else "unknown"
    raw_message = webhooks.get("state_message")
    message = raw_message[:4096].lower() if isinstance(raw_message, str) else ""
    diagnostic = "ready" if klipper_state == "ready" else "klipper_not_ready"
    if klipper_state != "ready" and "mcu" in message and "unable to connect" in message:
        diagnostic = "mcu_connection_unavailable"
    if klipper_state == "unknown":
        diagnostic = "klipper_state_unknown"
    settings = _object(_object(status.get("configfile")).get("settings"))
    printer = _object(settings.get("printer"))
    raw = printer.get("kinematics")
    kinematics = raw if isinstance(raw, str) and raw in KINEMATICS else None
    toolhead = _object(status.get("toolhead"))
    axes = []
    for key in ("axis_minimum", "axis_maximum"):
        values = toolhead.get(key)
        parsed = (
            [finite_number(x, -10000, 10000) for x in values[:3]]
            if isinstance(values, list) and len(values) in (3, 4)
            else []
        )
        axes.append(parsed if len(parsed) == 3 and all(x is not None for x in parsed) else None)
    bounds_ok = all(x is not None for x in axes) and all(lo < hi for lo, hi in zip(*axes))
    return {
        "schema": "klipperlearn.klipper-status-review/v1",
        "synthetic": synthetic,
        "server_response_parsed": True,
        "freshness_verified": False,
        "klipper_state": klipper_state,
        "print_state": print_state,
        "diagnostic": diagnostic,
        "between_prints_reported": klipper_state == "ready"
        and print_state in ("standby", "complete", "cancelled"),
        "kinematics": kinematics,
        "axis_minimum_mm": axes[0] if bounds_ok else None,
        "axis_maximum_mm": axes[1] if bounds_ok else None,
        "configured_limits": {
            "max_velocity_mm_s": finite_number(printer.get("max_velocity"), 0.001, 100000),
            "max_accel_mm_s2": finite_number(printer.get("max_accel"), 0.001, 1e7),
            "nozzle_diameter_mm": finite_number(
                _object(settings.get("extruder")).get("nozzle_diameter"), 0.01, 10
            ),
        },
        "commands_allowed": False,
        "safe_to_print_certified": False,
        "physical_configuration_verified": False,
        "automatic_changes": False,
    }


def main(argv=None) -> int:
    """Generate a local JSON report; the CLI deliberately has no URL argument."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("history", "status"):
        command = commands.add_parser(name)
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--output", type=Path)
        if name == "history":
            command.add_argument("--printer-id", required=True)
            command.add_argument("--workflow", choices=WORKFLOWS, required=True)
    args = parser.parse_args(argv)
    try:
        data = load_document(args.input)
        result = (
            normalize_history(data, printer_id=args.printer_id, workflow=args.workflow)
            if args.command == "history"
            else status_report(data)
        )
        encoded = (json.dumps(result, indent=2, allow_nan=False) + "\n").encode("utf-8")
        if args.output:
            write_new(args.output, encoded)
            print("Evidence report written; no printer or network operation performed.")
        else:
            print(encoded.decode("utf-8"), end="")
        return 0
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        print(
            "Evidence input rejected or output unavailable; no source was modified.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
