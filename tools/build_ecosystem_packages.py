#!/usr/bin/env python3
"""Build four small, auditable ecosystem distributions from explicit source lists.

No dependency, model, private runtime or Git history is bundled. ZIP files are
reproducible and independently hashed. --check compares existing artifacts without
rewriting them. No network, installation or printer access occurs.
SPDX-License-Identifier: GPL-3.0-or-later
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2026.09.17"
MAX_SOURCE = 2 * 1024 * 1024
MODULES = (
    "ecosystem_evidence",
    "camera_proxy",
    "host_preflight",
    "voron_review",
    "orca_bundle_audit",
    "slicer_optimizer",
)


def specifications() -> dict[str, dict[str, str]]:
    """Map archive names to explicit destination/source paths; never crawl a workspace."""
    toolkit = {f"klipperlearn/{name}.py": f"src/klipperlearn/{name}.py" for name in MODULES}
    toolkit.update(
        {
            "klipperlearn/__init__.py": "src/klipperlearn/__init__.py",
            "README.md": "integrations/ecosystem/TOOLKIT.md",
            "LICENSE": "LICENSE",
            "COPYING": "COPYING",
        }
    )
    for name in (
        "ecosystem-history.json",
        "ecosystem-status.json",
        "camera-proxy-spec.json",
        "host-preflight.json",
        "voron-packet.template.json",
        "synthetic-slicer-session.json",
    ):
        toolkit[f"examples/{name}"] = f"examples/{name}"
    return {
        "KlipperLearn-Cura-Evidence.zip": {
            "KlipperLearnEvidence.py": "integrations/cura/KlipperLearnEvidence.py",
            "README.md": "integrations/cura/README.md",
            "LICENSE": "LICENSE",
            "COPYING": "COPYING",
        },
        "OctoPrint-KlipperLearnEvidence-0.1.1.zip": {
            **{
                name: "integrations/octoprint/plugin/" + name
                for name in (
                    "pyproject.toml",
                    "README.md",
                    "LICENSE",
                    "COPYING",
                    "octoprint_klipperlearn_evidence/__init__.py",
                    "octoprint_klipperlearn_evidence/core.py",
                )
            }
        },
        "KlipperLearn-Slicer-Evidence.zip": {
            "klipperlearn_manifest.py": "integrations/orca/klipperlearn_manifest.py",
            "README.md": "integrations/ecosystem/SLICER_PACKAGE.md",
            "LICENSE": "LICENSES/MIT-reference.txt",
        },
        "KlipperLearn-Ecosystem-Toolkit.zip": toolkit,
    }


def read_source(root: Path, relative: str) -> bytes:
    """Reject linked, missing, out-of-tree and unexpectedly large package inputs."""
    source = root / relative
    if not source.resolve().is_relative_to(root.resolve()):
        raise ValueError("Source escapes repository")
    for item in (source, *source.parents):
        if item == root:
            break
        if item.is_symlink() or getattr(item, "is_junction", lambda: False)():
            raise ValueError("Linked package source is not allowed")
    info = source.lstat()
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_SOURCE:
        raise ValueError("Source must be a bounded regular file")
    with source.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        data = handle.read(MAX_SOURCE + 1)
        after = os.fstat(handle.fileno())
    stamp = lambda x: (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_mode)
    if (
        stamp(info) != stamp(opened)
        or stamp(opened) != stamp(after)
        or stamp(after) != stamp(source.lstat())
        or len(data) != info.st_size
    ):
        raise ValueError("Source changed during package creation")
    return data


def build_artifacts(root: Path) -> dict[str, bytes]:
    """Create deterministic archive bytes and a manifest; do not write or publish."""
    result, records = {}, []
    for filename, sources in sorted(specifications().items()):
        output, entries = io.BytesIO(), []
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for dest, source in sorted(sources.items()):
                raw = read_source(root, source)
                # Git checkout line endings differ across platforms. Normalize text only.
                raw = raw.decode("utf-8").replace("\r\n", "\n").encode("utf-8")
                item = zipfile.ZipInfo(dest, date_time=(2026, 9, 17, 0, 0, 0))
                item.create_system = 3
                item.external_attr = (stat.S_IFREG | 0o644) << 16
                item.compress_type = zipfile.ZIP_STORED
                archive.writestr(item, raw)
                entries.append(
                    {
                        "path": dest,
                        "source": source,
                        "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                    }
                )
        value = output.getvalue()
        result[filename] = value
        records.append(
            {
                "file": filename,
                "bytes": len(value),
                "sha256": hashlib.sha256(value).hexdigest(),
                "entries": entries,
            }
        )
    manifest = {
        "schema": "klipperlearn.ecosystem-packages/v1",
        "bundle_revision": VERSION,
        "archives": records,
        "native_acceptance_verified": False,
        "upstream_registration": False,
        "private_data_included": False,
    }
    result["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    result["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(result[name]).hexdigest()}  {name}\n" for name in sorted(result)
    ).encode("ascii")
    return result


def publish_local(output: Path, artifacts: dict[str, bytes]) -> None:
    """Create a new local package directory, refusing to overwrite existing outputs."""
    output.mkdir(parents=False, exist_ok=False)
    for name, data in artifacts.items():
        with (output / name).open("xb") as handle:
            handle.write(data)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "integrations/packages")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        artifacts = build_artifacts(ROOT)
        if args.check:
            for name, data in artifacts.items():
                path = args.output_dir / name
                if path.is_symlink() or path.read_bytes() != data:
                    raise ValueError("A package differs from canonical source")
            print("All four packages match their canonical source and recorded hashes.")
        else:
            publish_local(args.output_dir, artifacts)
            print("Four source packages created; nothing installed, submitted or deployed.")
        return 0
    except (OSError, ValueError, UnicodeError):
        print(
            "Package build/check rejected; use a new output directory and verified source.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
