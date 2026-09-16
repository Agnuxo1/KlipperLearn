"""Dataset provenance, integrity checks, and session-level split manifests."""

from __future__ import annotations

from collections import defaultdict
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from .domain import DEFECT_KEYS
from .quality import aggregate_findings, reviewed_metrics
from .storage import read_findings, session_summary

MANIFEST_SCHEMA_VERSION = 2
ALLOWED_SPLITS = {"train", "validation"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _registered_frames(session: Path) -> list[dict[str, Any]]:
    database = session / "telemetry.sqlite3"
    if not database.exists():
        return []
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                "SELECT relative_path, sha256, byte_count FROM frames ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [dict(row) for row in rows]


def audit_session(session_dir: str | Path) -> dict[str, Any]:
    """Inspect one local session without modifying it."""
    session = Path(session_dir)
    issues: list[str] = []
    registered = _registered_frames(session)
    registered_paths = {item["relative_path"] for item in registered}
    disk_paths = {
        path.relative_to(session).as_posix()
        for path in (session / "frames").glob("*.jpg")
        if path.is_file()
    }

    for item in registered:
        candidate = (session / item["relative_path"]).resolve()
        try:
            candidate.relative_to(session.resolve())
        except ValueError:
            issues.append(f"frame_path_outside_session:{item['relative_path']}")
            continue
        if not candidate.is_file():
            issues.append(f"registered_frame_missing:{item['relative_path']}")
            continue
        if candidate.stat().st_size != item["byte_count"]:
            issues.append(f"frame_size_mismatch:{item['relative_path']}")
        if _sha256(candidate) != item["sha256"]:
            issues.append(f"frame_hash_mismatch:{item['relative_path']}")

    for relative_path in sorted(disk_paths - registered_paths):
        issues.append(f"unregistered_frame:{relative_path}")

    findings = read_findings(session) if (session / "telemetry.sqlite3").exists() else []
    human_findings = [finding for finding in findings if finding.source == "human"]
    coverage = reviewed_metrics(human_findings)
    if not registered:
        issues.append("no_registered_frames")
    if not coverage:
        issues.append("no_human_labels")

    manifest_path = session / "manifest.json"
    provenance: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            provenance = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            issues.append(f"invalid_session_manifest:{exc}")
    else:
        issues.append("missing_session_manifest")

    if provenance:
        if provenance.get("schema_version") != 2:
            issues.append("unsupported_session_manifest_schema")
        for key in ("machine", "material", "camera", "config_sha256"):
            if not provenance.get(key):
                issues.append(f"missing_provenance:{key}")

    return {
        "path": str(session),
        "summary": session_summary(session) if (session / "telemetry.sqlite3").exists() else None,
        "registered_frame_count": len(registered),
        "frame_count_on_disk": len(disk_paths),
        "human_label_coverage": sorted(coverage),
        "missing_human_labels": [metric for metric in DEFECT_KEYS if metric not in coverage],
        "provenance": {
            "manifest_schema_version": provenance.get("schema_version"),
            "machine": provenance.get("machine", {}),
            "material": provenance.get("material", {}),
            "camera": provenance.get("camera", {}),
            "config_sha256": provenance.get("config_sha256"),
        },
        "issues": issues,
        "eligible_for_training": bool(registered and coverage) and not issues,
    }


def build_training_manifest(
    training_sessions: Iterable[str | Path],
    validation_sessions: Iterable[str | Path] = (),
) -> dict[str, Any]:
    """Build an auditable manifest with explicit, non-overlapping session splits."""
    split_paths = {
        "train": [Path(item).resolve() for item in training_sessions],
        "validation": [Path(item).resolve() for item in validation_sessions],
    }
    duplicates = set(split_paths["train"]) & set(split_paths["validation"])
    if duplicates:
        raise ValueError(
            "Sessions cannot appear in both train and validation: "
            + ", ".join(str(path) for path in sorted(duplicates))
        )

    sessions = []
    for split, paths in split_paths.items():
        for path in paths:
            sessions.append({"split": split, **audit_session(path)})

    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "purpose": "Local transfer-learning dataset with explicit session-level splits.",
        "automatic_downloads": False,
        "sessions": sessions,
        "labels": list(DEFECT_KEYS),
        "label_semantics": (
            "Only explicit human findings are targets. Missing labels are masked and are never "
            "treated as defect-free examples."
        ),
        "split_policy": (
            "A print/session belongs to exactly one split; frames from one print never cross splits."
        ),
        "privacy": (
            "Raw webcam frames stay local unless explicit dataset consent, license, and provenance "
            "are recorded."
        ),
    }


def write_training_manifest(
    output_path: str | Path,
    training_sessions: Iterable[str | Path],
    validation_sessions: Iterable[str | Path] = (),
) -> dict[str, Any]:
    manifest = build_training_manifest(training_sessions, validation_sessions)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def load_training_rows(manifest_path: str | Path) -> list[dict[str, Any]]:
    """Load verified frames and masked human labels from a schema-v2 manifest."""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("Unsupported training manifest. Regenerate it with 'train-plan'.")
    if manifest.get("labels") != list(DEFECT_KEYS):
        raise ValueError("Training manifest label order does not match this KlipperLearn version.")

    rows: list[dict[str, Any]] = []
    sessions_by_split: dict[str, set[Path]] = defaultdict(set)
    for item in manifest.get("sessions", []):
        split = item.get("split")
        if split not in ALLOWED_SPLITS:
            raise ValueError(f"Invalid or missing session split: {split!r}")
        session = Path(item["path"]).resolve()
        sessions_by_split[split].add(session)
        live_audit = audit_session(session)
        if not live_audit["eligible_for_training"]:
            raise ValueError(
                f"Session is not eligible for training: {session}; issues: "
                + ", ".join(live_audit["issues"])
            )
        findings = [finding for finding in read_findings(session) if finding.source == "human"]
        coverage = reviewed_metrics(findings)
        if not coverage:
            continue
        aggregate = aggregate_findings(findings)
        labels = [float(aggregate.get(metric, 0.0)) for metric in DEFECT_KEYS]
        label_mask = [metric in coverage for metric in DEFECT_KEYS]
        for frame in _registered_frames(session):
            candidate = (session / frame["relative_path"]).resolve()
            try:
                candidate.relative_to(session)
            except ValueError as exc:
                raise ValueError(f"Frame path escapes its session: {candidate}") from exc
            if not candidate.is_file():
                raise ValueError(f"Registered frame is missing: {candidate}")
            if (
                candidate.stat().st_size != frame["byte_count"]
                or _sha256(candidate) != frame["sha256"]
            ):
                raise ValueError(f"Registered frame failed integrity verification: {candidate}")
            rows.append(
                {
                    "frame": str(candidate),
                    "labels": labels,
                    "label_mask": label_mask,
                    "session": str(session),
                    "split": split,
                }
            )

    overlap = sessions_by_split["train"] & sessions_by_split["validation"]
    if overlap:
        raise ValueError("A session appears in both train and validation splits.")
    if not any(row["split"] == "train" for row in rows):
        raise ValueError("No eligible training rows found.")
    if not any(row["split"] == "validation" for row in rows):
        raise ValueError(
            "No eligible validation rows found; provide an independent reviewed session."
        )
    return rows
