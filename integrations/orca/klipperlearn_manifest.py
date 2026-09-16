#!/usr/bin/env python3
"""Record the exact sliced-file fingerprint without modifying or sending G-code.

SPDX-License-Identifier: MIT
Copyright (c) 2026 Francisco Angulo de Lafuente
Python 3.8+, standard library only. Suitable as an OrcaSlicer post-processing
command or as a standalone CLI. This is not a native Orca Python plugin.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Dict, Optional, List

MAX_BYTES = 512 * 1024 * 1024


def fingerprint(source: Path) -> Dict[str, Any]:
    """Stream a regular file and detect modifications during the read.

    SHA-256 identifies the exact byte stream, not geometric equivalence, print
    quality, safe temperatures, or whether a file was actually printed.
    Filenames and absolute paths are deliberately omitted from the manifest.
    """
    before = source.lstat()
    if not stat.S_ISREG(before.st_mode) or getattr(before, "st_file_attributes", 0) & 0x400:
        raise ValueError("The input must be a regular file, not a link or device.")
    if not 0 < before.st_size <= MAX_BYTES:
        raise ValueError("The sliced file is empty or exceeds 512 MiB.")
    digest = hashlib.sha256()
    count = 0
    with source.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("The input changed before reading.")
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            count += len(chunk)
            if count > MAX_BYTES:
                raise ValueError("The input grew beyond the size limit.")
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    current = source.stat()
    snapshot = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    if snapshot(before) != snapshot(after) or snapshot(after) != snapshot(current) or count != before.st_size:
        raise ValueError("The input changed during reading; no manifest was published.")
    return {"schema": "klipperlearn.slice-manifest.v1", "sha256": digest.hexdigest(),
            "byte_count": count, "source_modified": False, "geometry_verified": False,
            "quality_assessed": False, "parameters_inferred": False}


def write_manifest(source: Path, output_dir: Path) -> Path:
    """Write a new content-addressed JSON manifest; never overwrite prior files."""
    record = fingerprint(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / (record["sha256"] + ".json")
    payload = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if target.exists():
        if target.is_symlink() or target.read_bytes() != payload:
            raise ValueError("The existing manifest differs; refusing to replace it.")
        return target
    # Exclusive final creation avoids overwriting any concurrently created file.
    try:
        with target.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        if target.is_symlink() or target.read_bytes() != payload:
            raise ValueError("A conflicting manifest appeared concurrently.")
    return target


def main(argv: Optional[List[str]] = None) -> int:
    """Accept the slicer's appended file argument; print no private source path."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=Path.home() / "KlipperLearn" / "slice-manifests")
    parser.add_argument("source", type=Path)
    args = parser.parse_args(argv)
    try:
        target = write_manifest(args.source, args.output_dir)
        print("KlipperLearn: slice manifest recorded; G-code unchanged (" + target.name + ").")
        return 0
    except (OSError, ValueError) as error:
        print("KlipperLearn manifest failed: " + type(error).__name__ +
              ". Check the selected file and output directory.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
