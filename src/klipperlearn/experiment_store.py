"Self-contained local storage for calibration trials.\n\nThis module is independent of klipperlearn.storage. It stores validated JSON\nand does not interpret paths inside metadata or evidence. Backups copy only\nthe controlled root/assets tree.\n"

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any, Iterator
import unicodedata
import uuid


SCHEMA_VERSION = 2
WEIGHTS_VERSION = "40-60-v1"
OBJECTIVE_WEIGHT = 0.4
HUMAN_WEIGHT = 0.6
DB_FILENAME = "experiment_store.sqlite3"

MAX_JSON_BYTES = 256 * 1024
MAX_JSON_DEPTH = 8
MAX_JSON_NODES = 4096
MAX_STRING_LENGTH = 16 * 1024
MAX_NUMBER_ABS = 1e12
MAX_COMMENT_LENGTH = 16 * 1024

_TRIAL_ID = re.compile(r"^[0-9a-f]{32}$")
_SHA256_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_REQUIRED_CONTEXT = frozenset({"printer_id", "model_sha256", "material", "nozzle_mm", "session_id"})
_RATING_KEYS = frozenset({"speed", "surface", "geometry"})
_WEIGHT_PRESETS = {WEIGHTS_VERSION: (OBJECTIVE_WEIGHT, HUMAN_WEIGHT)}


def _invalid(message: str) -> ValueError:
    return ValueError(message)


def _validate_json_value(
    value: Any, field: str, *, depth: int = 0, state: list[int] | None = None
) -> None:
    """Validate the strict, finite, bounded JSON subset used by the store."""

    if state is None:
        state = [0]
    state[0] += 1
    if state[0] > MAX_JSON_NODES:
        raise _invalid(f"{field} exceeds the JSON node limit")
    if depth > MAX_JSON_DEPTH:
        raise _invalid(f"{field} exceeds the JSON nesting limit")

    if value is None or isinstance(value, bool):
        return
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise _invalid(f"{field} contains text that is too long")
        return
    if type(value) is int:
        if abs(value) > MAX_NUMBER_ABS:
            raise _invalid(f"{field} contains a number that is too large")
        return
    if type(value) is float:
        if not math.isfinite(value) or abs(value) > MAX_NUMBER_ABS:
            raise _invalid(f"{field} contains a non-finite or too-large number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{field}[{index}]", depth=depth + 1, state=state)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _invalid(f"{field} has a non-text JSON key")
            if len(key) > MAX_STRING_LENGTH:
                raise _invalid(f"{field} has a key that is too long")
            _validate_json_value(item, f"{field}.{key}", depth=depth + 1, state=state)
        return
    raise _invalid(f"{field} is not JSON-compatible")


def _encode_json(value: Any, field: str) -> str:
    _validate_json_value(value, field)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise _invalid(f"{field} cannot be encoded as JSON") from exc
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise _invalid(f"{field} exceeds the JSON size limit")
    return encoded


def _non_empty_text(value: Any, field: str) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > MAX_STRING_LENGTH
        or any(unicodedata.category(character) == "Cc" for character in value)
    ):
        raise _invalid(f"{field} must be non-empty text")
    return value


def _finite_number(value: Any, field: str) -> float:
    if type(value) not in (int, float):
        raise _invalid(f"{field} must be a finite number")
    try:
        numeric = float(value)
    except (OverflowError, ValueError) as exc:
        raise _invalid(f"{field} must be a finite, bounded number") from exc
    if not math.isfinite(numeric) or abs(numeric) > MAX_NUMBER_ABS:
        raise _invalid(f"{field} must be a finite, bounded number")
    return numeric


def _validate_context(context: Any) -> dict[str, Any]:
    if type(context) is not dict:
        raise _invalid("context must be a dict")
    missing = _REQUIRED_CONTEXT - set(context)
    if missing:
        raise _invalid("context is missing: " + ", ".join(sorted(missing)))
    _non_empty_text(context["printer_id"], "context.printer_id")
    model_sha256 = _non_empty_text(context["model_sha256"], "context.model_sha256")
    if not _SHA256_HEX.fullmatch(model_sha256):
        raise _invalid("context.model_sha256 must be 64 hexadecimal characters")
    _non_empty_text(context["material"], "context.material")
    nozzle_mm = _finite_number(context["nozzle_mm"], "context.nozzle_mm")
    if nozzle_mm <= 0:
        raise _invalid("context.nozzle_mm must be greater than zero")
    _non_empty_text(context["session_id"], "context.session_id")
    _encode_json(context, "context")
    return context


def _validate_parameters(parameters: Any) -> dict[str, Any]:
    if type(parameters) is not dict:
        raise _invalid("parameters must be a dict")
    _encode_json(parameters, "parameters")
    return parameters


def _validate_evidence(evidence: Any) -> dict[str, Any] | None:
    if evidence is None:
        return None
    if type(evidence) is not dict:
        raise _invalid("evidence must be a dict or None")
        # Deliberately only validates JSON; no value is ever treated as a path.
    _encode_json(evidence, "evidence")
    return evidence


def _validate_objective(objective_score: Any) -> float | None:
    if objective_score is None:
        return None
    objective = _finite_number(objective_score, "objective_score")
    if not 0.0 <= objective <= 100.0:
        raise _invalid("objective_score must be between 0 and 100")
    return objective


def _validate_ratings(ratings: Any) -> dict[str, int]:
    if type(ratings) is not dict or set(ratings) != _RATING_KEYS:
        raise _invalid("ratings must contain exactly speed, surface and geometry")
    normalized: dict[str, int] = {}
    for key in ("speed", "surface", "geometry"):
        value = ratings[key]
        if type(value) is not int or not 0 <= value <= 5:
            raise _invalid(f"ratings.{key} must be an integer between 0 and 5")
        normalized[key] = value
    return normalized


def _validate_trial_id(trial_id: Any) -> str:
    if type(trial_id) is not str or not _TRIAL_ID.fullmatch(trial_id):
        raise _invalid("trial_id must be a lowercase uuidhex32")
    return trial_id


def _validate_page(value: Any, field: str) -> int:
    minimum, maximum = (1, 200) if field == "limit" else (0, 1_000_000)
    if type(value) is not int or not minimum <= value <= maximum:
        raise _invalid(f"{field} must be a non-negative integer")
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _human_score(ratings: dict[str, int]) -> float:
    return (sum(ratings.values()) / 3.0) * 20.0


def _weights_for_version(version: Any) -> tuple[float, float]:
    try:
        return _WEIGHT_PRESETS[version]
    except (KeyError, TypeError) as exc:
        raise _invalid(f"unknown weights version: {version!r}") from exc


def _combined_score(
    objective: float | None,
    human: float | None,
    weights_version: str = WEIGHTS_VERSION,
) -> float | None:
    if objective is None or human is None:
        return None
    objective_weight, human_weight = _weights_for_version(weights_version)
    return objective_weight * objective + human_weight * human


def _raw_scores(
    objective: float | None, human: float | None, score: float | None
) -> dict[str, float | None]:
    return {
        "objective": objective,
        "human": human,
        "score": score,
    }


def _decode_json(encoded: str | None) -> Any:
    return None if encoded is None else json.loads(encoded)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ExperimentStore:
    """A local SQLite store for immutable trial provenance and human reviews.

    Backups intentionally contain only this store's SQLite database and the
    store-owned ``root/assets`` tree.  They do not include ``data``,
    ``calibration`` or any path named inside metadata/evidence.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        if self.root.exists() and not self.root.is_dir():
            raise _invalid("root must be a directory")
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / DB_FILENAME
        self.path = self.db_path
        connection = self._connect()
        try:
            self.schema_version, self.weights_version = self._open_schema(connection)
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS store_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trials (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                id TEXT NOT NULL UNIQUE,
                timestamp_utc TEXT NOT NULL,
                context_json TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                objective_score REAL,
                evidence_json TEXT,
                weights_version TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rating_revisions (
                trial_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                timestamp_utc TEXT NOT NULL,
                ratings_json TEXT NOT NULL,
                human_score REAL NOT NULL,
                score REAL,
                comment TEXT NOT NULL,
                PRIMARY KEY (trial_id, revision),
                FOREIGN KEY (trial_id) REFERENCES trials(id) ON DELETE RESTRICT
            );

            CREATE INDEX IF NOT EXISTS rating_revisions_trial_idx
                ON rating_revisions(trial_id, revision);

            CREATE TABLE IF NOT EXISTS photo_evidence (
                trial_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                timestamp_utc TEXT NOT NULL,
                relative_path TEXT NOT NULL UNIQUE,
                sha256 TEXT NOT NULL,
                byte_count INTEGER NOT NULL,
                original_name TEXT NOT NULL,
                PRIMARY KEY (trial_id, sequence),
                FOREIGN KEY (trial_id) REFERENCES trials(id) ON DELETE RESTRICT
            );
            """
        )
        connection.execute(
            "INSERT INTO store_meta(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        connection.execute(
            "INSERT INTO store_meta(key, value) VALUES (?, ?)",
            ("weights_version", WEIGHTS_VERSION),
        )

    @classmethod
    def _open_schema(cls, connection: sqlite3.Connection) -> tuple[int, str]:
        """Validate compatibility before any schema or metadata mutation."""

        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if not tables:
            cls._create_schema(connection)
            return SCHEMA_VERSION, WEIGHTS_VERSION

        required_tables = {"store_meta", "trials", "rating_revisions"}
        if not required_tables.issubset(tables):
            raise _invalid("unsupported experiment store schema")
        metadata = dict(
            connection.execute(
                "SELECT key, value FROM store_meta WHERE key IN ('schema_version', 'weights_version')"
            ).fetchall()
        )
        if set(metadata) != {"schema_version", "weights_version"}:
            raise _invalid("experiment store metadata is incomplete")
        try:
            schema_version = int(metadata["schema_version"])
        except (TypeError, ValueError) as exc:
            raise _invalid("experiment store schema version is invalid") from exc
        if schema_version == 1:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS photo_evidence (
                    trial_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                    timestamp_utc TEXT NOT NULL, relative_path TEXT NOT NULL UNIQUE,
                    sha256 TEXT NOT NULL, byte_count INTEGER NOT NULL, original_name TEXT NOT NULL,
                    PRIMARY KEY (trial_id, sequence),
                    FOREIGN KEY (trial_id) REFERENCES trials(id) ON DELETE RESTRICT
                );
            """)
            connection.execute(
                "UPDATE store_meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),)
            )
            schema_version = SCHEMA_VERSION
        if schema_version != SCHEMA_VERSION:
            raise _invalid(f"unsupported experiment store schema version: {schema_version}")
        weights_version = metadata["weights_version"]
        _weights_for_version(weights_version)
        return schema_version, weights_version

    @contextmanager
    def _write_transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_trial(
        self,
        context: dict,
        parameters: dict,
        objective_score: float | None = None,
        evidence: dict | None = None,
    ) -> dict:
        """Create an immutable trial record and return its public representation."""

        normalized_context = _validate_context(context)
        normalized_parameters = _validate_parameters(parameters)
        normalized_objective = _validate_objective(objective_score)
        normalized_evidence = _validate_evidence(evidence)
        context_json = _encode_json(normalized_context, "context")
        parameters_json = _encode_json(normalized_parameters, "parameters")
        evidence_json = (
            None if normalized_evidence is None else _encode_json(normalized_evidence, "evidence")
        )
        timestamp = _utc_now()

        trial_id = uuid.uuid4().hex
        with self._write_transaction() as connection:
            connection.execute(
                """
                INSERT INTO trials(
                    id, timestamp_utc, context_json, parameters_json,
                    objective_score, evidence_json, weights_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trial_id,
                    timestamp,
                    context_json,
                    parameters_json,
                    normalized_objective,
                    evidence_json,
                    WEIGHTS_VERSION,
                ),
            )
        return self.get_trial(trial_id)

    def rate_trial(self, trial_id, ratings: dict, comment: str = "") -> dict:
        """Append one human-rating revision; previous revisions are never changed."""

        normalized_id = _validate_trial_id(trial_id)
        normalized_ratings = _validate_ratings(ratings)
        if type(comment) is not str or len(comment) > MAX_COMMENT_LENGTH:
            raise _invalid("comment must be text within the size limit")
        ratings_json = _encode_json(normalized_ratings, "ratings")

        timestamp = _utc_now()
        human = _human_score(normalized_ratings)
        with self._write_transaction() as connection:
            trial = connection.execute(
                "SELECT objective_score FROM trials WHERE id = ?", (normalized_id,)
            ).fetchone()
            if trial is None:
                raise KeyError(normalized_id)
            latest = connection.execute(
                "SELECT COALESCE(MAX(revision), 0) FROM rating_revisions WHERE trial_id = ?",
                (normalized_id,),
            ).fetchone()[0]
            revision = int(latest) + 1
            score = _combined_score(trial["objective_score"], human)
            connection.execute(
                """
                INSERT INTO rating_revisions(
                    trial_id, revision, timestamp_utc, ratings_json,
                    human_score, score, comment
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (normalized_id, revision, timestamp, ratings_json, human, score, comment),
            )
        return self.get_trial(normalized_id)

    def add_photo(self, trial_id: str, jpeg: bytes, original_name: str = "photo.jpg") -> dict:
        normalized_id = _validate_trial_id(trial_id)
        if not isinstance(jpeg, bytes) or not 4 <= len(jpeg) <= 8 * 1024 * 1024:
            raise _invalid("photo must be JPEG bytes up to 8 MiB")
        if not jpeg.startswith(b"\xff\xd8") or not jpeg.endswith(b"\xff\xd9"):
            raise _invalid("photo must be JPEG")
        name = _non_empty_text(original_name, "original_name")
        if len(name) > 255:
            raise _invalid("original_name is too long")
        digest = hashlib.sha256(jpeg).hexdigest()
        timestamp = _utc_now()
        target: Path | None = None
        temporary: Path | None = None
        try:
            with self._write_transaction() as connection:
                if (
                    connection.execute(
                        "SELECT 1 FROM trials WHERE id=?", (normalized_id,)
                    ).fetchone()
                    is None
                ):
                    raise KeyError(normalized_id)
                sequence = int(
                    connection.execute(
                        "SELECT COALESCE(MAX(sequence),0)+1 FROM photo_evidence WHERE trial_id=?",
                        (normalized_id,),
                    ).fetchone()[0]
                )
                relative = f"assets/photos/{normalized_id}/{sequence:04d}-{digest[:16]}.jpg"
                target = self.root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(".tmp")
                temporary.write_bytes(jpeg)
                temporary.replace(target)
                connection.execute(
                    "INSERT INTO photo_evidence(trial_id,sequence,timestamp_utc,relative_path,sha256,byte_count,original_name) VALUES(?,?,?,?,?,?,?)",
                    (normalized_id, sequence, timestamp, relative, digest, len(jpeg), name),
                )
        except BaseException:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if target is not None:
                target.unlink(missing_ok=True)
            raise
        return self.get_trial(normalized_id)

    def _trial_from_row(self, connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
        revisions: list[dict[str, Any]] = []
        revision_rows = connection.execute(
            """
            SELECT revision, timestamp_utc, ratings_json, human_score, score, comment
            FROM rating_revisions
            WHERE trial_id = ?
            ORDER BY revision ASC
            """,
            (row["id"],),
        ).fetchall()
        for revision_row in revision_rows:
            revision_ratings = _decode_json(revision_row["ratings_json"])
            revision_human = float(revision_row["human_score"])
            revision_score = None if revision_row["score"] is None else float(revision_row["score"])
            revisions.append(
                {
                    "revision": int(revision_row["revision"]),
                    "timestamp_utc": revision_row["timestamp_utc"],
                    "ratings": revision_ratings,
                    "human_score": revision_human,
                    "score": revision_score,
                    "raw_scores": _raw_scores(
                        float(row["objective_score"])
                        if row["objective_score"] is not None
                        else None,
                        revision_human,
                        revision_score,
                    ),
                    "weights": {
                        "objective": OBJECTIVE_WEIGHT,
                        "human": HUMAN_WEIGHT,
                        "version": WEIGHTS_VERSION,
                    },
                    "comment": revision_row["comment"],
                }
            )

        latest = revisions[-1] if revisions else None
        objective = None if row["objective_score"] is None else float(row["objective_score"])
        human = None if latest is None else latest["human_score"]
        score = None if latest is None else latest["score"]
        photo_rows = connection.execute(
            "SELECT sequence,timestamp_utc,relative_path,sha256,byte_count,original_name FROM photo_evidence WHERE trial_id=? ORDER BY sequence",
            (row["id"],),
        ).fetchall()
        photos = [dict(item) for item in photo_rows]
        result = {
            "schema_version": SCHEMA_VERSION,
            "id": row["id"],
            "timestamp_utc": row["timestamp_utc"],
            "created_at_utc": row["timestamp_utc"],
            "updated_at_utc": None if latest is None else latest["timestamp_utc"],
            "context": _decode_json(row["context_json"]),
            "parameters": _decode_json(row["parameters_json"]),
            "evidence": _decode_json(row["evidence_json"]),
            "objective_score": objective,
            "ratings": None if latest is None else latest["ratings"],
            "human_score": human,
            "score": score,
            "raw_scores": _raw_scores(objective, human, score),
            "weights": {
                "objective": OBJECTIVE_WEIGHT,
                "human": HUMAN_WEIGHT,
                "version": WEIGHTS_VERSION,
            },
            "weights_version": WEIGHTS_VERSION,
            "status": "pending" if score is None else "scored",
            "rating_revision": None if latest is None else latest["revision"],
            "revisions": revisions,
            "photos": photos,
        }
        try:
            learned = connection.execute(
                "SELECT payload FROM learning_assessments WHERE trial_id=? ORDER BY rowid DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
        except sqlite3.OperationalError:
            learned = None  # Learning is optional; old stores remain fully readable.
        if learned:
            assessment = _decode_json(learned["payload"])
            if assessment.get("rating_revision") == result["rating_revision"] and assessment.get(
                "features", {}
            ).get("photo_sha256") == sorted(photo["sha256"] for photo in photos):
                result["learning"] = assessment
                if (
                    assessment.get("model_validated") or assessment.get("measurement_validated")
                ) and assessment.get("combined_score") is not None:
                    result["data_score_estimate"] = assessment["data_score"]
                    result["score"] = assessment["combined_score"]
                    result["status"] = "scored"
                    result["score_source"] = (
                        "registered_geometry_40_human_60"
                        if assessment.get("measurement_validated")
                        else "cross_validated_multimodal_estimate_40_human_60"
                    )
        return result

    def get_trial(self, id) -> dict:
        normalized_id = _validate_trial_id(id)
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM trials WHERE id = ?", (normalized_id,)
            ).fetchone()
            if row is None:
                raise KeyError(normalized_id)
            return self._trial_from_row(connection, row)
        finally:
            connection.close()

    def list_trials(self, limit: int = 50, offset: int = 0) -> list:
        return self._list_trials(limit, offset, newest_first=False)

    def recent_trials(self, limit: int = 50, offset: int = 0) -> list:
        return self._list_trials(limit, offset, newest_first=True)

    def _list_trials(self, limit, offset, newest_first):
        normalized_limit = _validate_page(limit, "limit")
        normalized_offset = _validate_page(offset, "offset")
        connection = self._connect()
        try:
            rows = connection.execute(
                (
                    "SELECT * FROM trials ORDER BY sequence DESC LIMIT ? OFFSET ?"
                    if newest_first
                    else "SELECT * FROM trials ORDER BY sequence ASC LIMIT ? OFFSET ?"
                ),
                (normalized_limit, normalized_offset),
            ).fetchall()
            return [self._trial_from_row(connection, row) for row in rows]
        finally:
            connection.close()

    def export_jsonl(self) -> str:
        """Return one complete, self-contained JSON object per trial."""

        connection = self._connect()
        try:
            rows = connection.execute("SELECT * FROM trials ORDER BY sequence ASC").fetchall()
            records = [self._trial_from_row(connection, row) for row in rows]
        finally:
            connection.close()
        if not records:
            return ""
        return (
            "\n".join(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for record in records
            )
            + "\n"
        )

    def _asset_files(self) -> list[tuple[Path, str]]:
        assets_root = self.root / "assets"
        if not assets_root.exists():
            return []
        if (
            assets_root.is_symlink()
            or getattr(assets_root, "is_junction", lambda: False)()
            or not assets_root.is_dir()
        ):
            raise _invalid("root/assets must be a real directory")
        files: list[tuple[Path, str]] = []
        for candidate in sorted(assets_root.rglob("*"), key=lambda path: path.as_posix()):
            if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
                raise _invalid(f"symlink is not allowed in assets: {candidate}")
            if candidate.is_dir():
                continue
            if not candidate.is_file():
                raise _invalid(f"unsupported asset entry: {candidate}")
            relative = (Path("assets") / candidate.relative_to(assets_root)).as_posix()
            files.append((candidate, relative))
        return files

    def backup(self, destination) -> Path:
        """Create a new backup directory using SQLite's online backup API."""

        destination_path = Path(destination)
        resolved_destination = destination_path.resolve()
        assets = (self.root / "assets").resolve()
        if (
            resolved_destination == self.root.resolve()
            or resolved_destination == assets
            or assets in resolved_destination.parents
        ):
            raise ValueError("Backup destination must be outside the assets tree")
        if destination_path.exists():
            raise FileExistsError(destination_path)
        asset_files = self._asset_files()
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.mkdir()
        try:
            database_path = destination_path / self.db_path.name
            source = self._connect()
            target = sqlite3.connect(database_path)
            try:
                target.execute("PRAGMA foreign_keys = ON")
                source.backup(target)
                target.commit()
            finally:
                target.close()
                source.close()

            copied_assets: list[dict[str, Any]] = []
            for source_path, relative in asset_files:
                target_path = destination_path / Path(relative)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
                copied_assets.append(
                    {
                        "path": relative,
                        "sha256": _sha256_file(target_path),
                        "byte_count": target_path.stat().st_size,
                    }
                )

            database_entry = {
                "path": self.db_path.name,
                "sha256": _sha256_file(database_path),
                "byte_count": database_path.stat().st_size,
            }
            file_entries = {
                database_entry["path"]: database_entry,
                **{item["path"]: item for item in copied_assets},
            }
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "kind": "klipperlearn_experiment_backup",
                "database": database_entry,
                "assets": copied_assets,
                "files": file_entries,
                "hashes": {path: item["sha256"] for path, item in file_entries.items()},
            }
            (destination_path / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except BaseException:
            # A failed backup has no manifest and must not be used for restore.
            # Preserve partial files for diagnosis instead of deleting paths.
            raise
        return destination_path


__all__ = [
    "DB_FILENAME",
    "ExperimentStore",
    "HUMAN_WEIGHT",
    "OBJECTIVE_WEIGHT",
    "SCHEMA_VERSION",
    "WEIGHTS_VERSION",
]
