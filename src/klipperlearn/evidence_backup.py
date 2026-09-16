"""Portable private evidence archive, including an online SQLite snapshot."""

import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import zipfile


def export_evidence(root, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination.is_relative_to(root):
        raise ValueError("Save the backup outside the evidence directory")
    if destination.exists():
        raise ValueError("Backup destination already exists")
    source_db = root / "experiment_store.sqlite3"
    if not source_db.is_file():
        raise ValueError("Evidence database not found")
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": "klipperlearn-evidence-backup-v1", "private": True, "files": []}
    with tempfile.TemporaryDirectory(
        prefix="klipperlearn-backup-", dir=destination.parent
    ) as temporary:
        snapshot = Path(temporary) / "experiment_store.sqlite3"
        with (
            closing(sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(snapshot)) as target,
        ):
            source.backup(target)
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            candidates = [(snapshot, "experiment_store.sqlite3")]
            assets = root / "assets"
            if assets.is_symlink() or not assets.resolve().is_relative_to(root):
                raise ValueError("Evidence assets must be inside the evidence directory")
            if assets.is_dir():
                for path in sorted(assets.rglob("*")):
                    if not path.is_file():
                        continue
                    if path.is_symlink() or not path.resolve().is_relative_to(assets.resolve()):
                        raise ValueError("Evidence links outside the archive are not allowed")
                    candidates.append((path, path.relative_to(root).as_posix()))
            for path, name in candidates:
                content = path.read_bytes()
                # An append-only event currently being written can end mid-line.
                # Keep complete events and explicitly record the snapshot policy.
                if name.endswith(".jsonl") and content and not content.endswith(b"\n"):
                    content = content.rsplit(b"\n", 1)[0] + b"\n" if b"\n" in content else b""
                archive.writestr(name, content)
                manifest["files"].append(
                    {
                        "path": name,
                        "bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
            manifest["consistency"] = (
                "SQLite online snapshot; assets read individually; complete JSONL events only"
            )
            archive.writestr(
                "backup-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
            )
    return {
        "path": str(destination),
        "files": len(manifest["files"]),
        "bytes": destination.stat().st_size,
    }
