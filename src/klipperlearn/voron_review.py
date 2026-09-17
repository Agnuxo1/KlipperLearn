"""Check a local Voron evidence packet for human review, not certification.

Physical-test and ownership declarations remain operator assertions. Matching
photo bytes prove integrity only, not that photos are original or representative.
SPDX-License-Identifier: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys

from .ecosystem_evidence import EvidenceError, finite_number, load_document, write_new

_HASH = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z", re.ASCII)
DECLARATIONS = (
    "physical_printer_tested",
    "operator_reviewed",
    "license_reviewed",
    "mount_clearance_checked",
    "thermal_limits_checked",
)


def verify_packet(packet: dict, assets_root: Path) -> dict:
    """Require consistent sessions and bounded in-root evidence; reveal no local paths."""
    required = {
        "schema",
        "printer_id",
        "voron_model",
        "configuration_sha256",
        "benchmark_sha256",
        "declarations",
        "trials",
    }
    if (
        not isinstance(packet, dict)
        or set(packet) != required
        or packet["schema"] != "klipperlearn.voron-evidence/v1"
    ):
        raise EvidenceError("Unsupported Voron evidence packet")
    if (
        not isinstance(packet["printer_id"], str)
        or not _ID.fullmatch(packet["printer_id"])
        or packet["voron_model"] not in ("V0", "Trident", "V2.4", "Switchwire", "Legacy")
    ):
        raise EvidenceError("Select one explicitly identified Voron printer")
    for field in ("configuration_sha256", "benchmark_sha256"):
        if not isinstance(packet[field], str) or not _HASH.fullmatch(packet[field]):
            raise EvidenceError("Configuration and geometry must have SHA-256 identities")
    declarations = packet["declarations"]
    if (
        not isinstance(declarations, dict)
        or set(declarations) != set(DECLARATIONS)
        or any(type(v) is not bool for v in declarations.values())
    ):
        raise EvidenceError("Explicit boolean declarations are required")
    trials = packet["trials"]
    if not isinstance(trials, list) or not 1 <= len(trials) <= 100:
        raise EvidenceError("Provide between one and 100 physical trial records")
    if (
        assets_root.is_symlink()
        or getattr(assets_root, "is_junction", lambda: False)()
        or not assets_root.is_dir()
    ):
        raise EvidenceError("Evidence root must be an existing real directory")
    root = assets_root.resolve()
    ids, sessions, identities, photo_hashes = set(), set(), set(), set()
    blockers = [name for name, value in declarations.items() if not value]
    verified = 0
    for trial in trials:
        fields = {
            "trial_id",
            "session_id",
            "benchmark_sha256",
            "configuration_sha256",
            "completed",
            "layer_height_mm",
            "layer_count",
            "photo",
            "photo_sha256",
        }
        if not isinstance(trial, dict) or set(trial) != fields:
            raise EvidenceError("Invalid trial contract")
        for key, observed in (("trial_id", ids), ("session_id", sessions)):
            value = trial[key]
            if not isinstance(value, str) or not _ID.fullmatch(value) or value in observed:
                raise EvidenceError("Independent trials require unique short identifiers")
            observed.add(value)
        if (
            trial["benchmark_sha256"] != packet["benchmark_sha256"]
            or trial["configuration_sha256"] != packet["configuration_sha256"]
        ):
            raise EvidenceError("Do not mix geometry or configurations in a repeatability packet")
        height = finite_number(trial["layer_height_mm"], 0.001, 5)
        layers = trial["layer_count"]
        if height is None or type(layers) is not int or not 1 <= layers <= 1_000_000:
            raise EvidenceError("Finite layer height and an integer layer count are required")
        identities.add((height, layers))
        if type(trial["completed"]) is not bool:
            raise EvidenceError("Completion must be a boolean")
        if not trial["completed"]:
            blockers.append("unfinished_trial")
        raw = trial["photo"]
        relative = PurePosixPath(raw) if isinstance(raw, str) else PurePosixPath("/")
        if (
            not isinstance(raw, str)
            or not raw
            or len(raw) > 255
            or "\\" in raw
            or ":" in raw
            or any(ord(c) < 32 or ord(c) == 127 for c in raw)
            or relative.is_absolute()
            or any(p in ("", ".", "..") for p in raw.split("/"))
        ):
            raise EvidenceError("Photo must be a safe relative local path")
        path = root.joinpath(*relative.parts)
        for parent in [path, *path.parents]:
            if parent == root:
                break
            if parent.is_symlink() or getattr(parent, "is_junction", lambda: False)():
                raise EvidenceError("Evidence links are not accepted")
        if not path.resolve().is_relative_to(root):
            raise EvidenceError("Photo escapes the supplied evidence directory")
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= 25 * 1024 * 1024:
            raise EvidenceError("Photo must be a regular file no larger than 25 MiB")
        digest = hashlib.sha256()
        size, signature = 0, b""
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
                raise EvidenceError("Photo changed before reading")
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                if not signature:
                    signature = chunk[:8]
                size += len(chunk)
                if size > 25 * 1024 * 1024:
                    raise EvidenceError("Photo grew beyond its size limit")
                digest.update(chunk)
            after = os.fstat(handle.fileno())
        current = path.lstat()
        stamp = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_mode)
        if stamp(info) != stamp(after) or stamp(after) != stamp(current) or size != info.st_size:
            raise EvidenceError("Photo changed during verification")
        if not (signature.startswith(b"\xff\xd8") or signature == b"\x89PNG\r\n\x1a\n"):
            raise EvidenceError("A JPEG or PNG signature is required")
        result = digest.hexdigest()
        if result != trial["photo_sha256"] or result in photo_hashes:
            raise EvidenceError("Photos must match their hashes and differ between sessions")
        photo_hashes.add(result)
        verified += 1
    if len(identities) != 1:
        blockers.append("inconsistent_layers")
    if len(sessions) < 2:
        blockers.append("independent_repeat_missing")
    return {
        "schema": "klipperlearn.voron-review/v1",
        "printer_id": packet["printer_id"],
        "voron_model": packet["voron_model"],
        "photo_files_hash_verified": verified,
        "independent_session_ids": len(sessions),
        "blockers": sorted(set(blockers)),
        "ready_for_human_review": not blockers,
        "declarations_independently_verified": False,
        "image_content_quality_verified": False,
        "voron_compatibility_certified": False,
        "voronusers_submission_approved": False,
        "commands_allowed": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--assets-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_packet(load_document(args.packet), args.assets_root)
        encoded = (json.dumps(result, indent=2) + "\n").encode()
        if args.output:
            write_new(args.output, encoded)
            print("Review packet checked; no hardware test or upstream submission performed.")
        else:
            print(encoded.decode(), end="")
        return 0 if result["ready_for_human_review"] else 1
    except (OSError, ValueError, TypeError):
        print("Evidence packet rejected; originals were not changed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
