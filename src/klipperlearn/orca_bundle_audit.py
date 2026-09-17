"""Verify an Orca-mode ZIP against its exact reviewed session without importing it.

No archive member is extracted and no slicer setting is installed. The audit
verifies reproducibility, not native Orca acceptance or physical print quality.
SPDX-License-Identifier: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

from .ecosystem_evidence import EvidenceError, load_document, write_new
from .slicer_optimizer import build_profiles, loads

MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
MAX_MEMBER_BYTES = 2 * 1024 * 1024


def audit_bundle(session: dict, archive_path: str | Path) -> dict:
    """Reject extra members, changed scripts/geometry, mixed profiles and zip bombs."""
    expected = build_profiles(session)
    members = dict(expected["files"])
    members["review.json"] = {k: v for k, v in expected.items() if k != "files"}
    path = Path(archive_path)
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & 0x400
        or not 0 < info.st_size <= MAX_ARCHIVE_BYTES
    ):
        raise EvidenceError("Bundle must be a regular archive no larger than 16 MiB")
    # The exact bytes audited are also the bytes fingerprinted, avoiding a re-read race.
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino):
            raise EvidenceError("Bundle changed before reading")
        raw = stream.read(MAX_ARCHIVE_BYTES + 1)
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise EvidenceError("Bundle grew beyond its size limit")
    import io

    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != 7 or len(set(names)) != 7 or set(names) != set(members):
            raise EvidenceError("Bundle must contain exactly six mode files and review.json")
        for item in infos:
            if (
                item.is_dir()
                or item.flag_bits & 1
                or item.file_size > MAX_MEMBER_BYTES
                or stat.S_ISLNK(item.external_attr >> 16)
            ):
                raise EvidenceError("Invalid, encrypted, linked or oversized bundle member")
            with archive.open(item) as handle:
                content = handle.read(MAX_MEMBER_BYTES + 1)
            if len(content) != item.file_size or len(content) > MAX_MEMBER_BYTES:
                raise EvidenceError("Archive member size is invalid")
            if loads(content) != members[item.filename]:
                raise EvidenceError("Bundle content differs from the reviewed session")
    return {
        "schema": "klipperlearn.orca-bundle-audit/v1",
        "matches_reviewed_session": True,
        "bundle_sha256": hashlib.sha256(raw).hexdigest(),
        "byte_count": len(raw),
        "session_sha256": expected["review"]["session_sha256"],
        "mode_count": 3,
        "profile_count": 6,
        "synthetic": session["synthetic"],
        "files_extracted": False,
        "native_slicer_import_verified": False,
        "printer_commands": False,
        "configuration_installed": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = audit_bundle(load_document(args.session), args.bundle)
        encoded = (json.dumps(result, indent=2) + "\n").encode()
        if args.output:
            write_new(args.output, encoded)
            print("Bundle verified against its session; no slicer import or printer operation.")
        else:
            print(encoded.decode(), end="")
        return 0
    except (OSError, ValueError, TypeError, zipfile.BadZipFile, RuntimeError):
        print(
            "Bundle verification failed; no files were extracted or settings installed.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
