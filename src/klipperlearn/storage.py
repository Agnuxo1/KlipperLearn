"""SQLite persistence with a deliberately simple and inspectable schema."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterator

from .domain import Finding

SCHEMA_VERSION = 2


class SessionStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def open(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        self._create_schema(connection)
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    @contextmanager
    def read_only(self) -> Iterator[sqlite3.Connection]:
        """Open an existing session without schema creation or other writes."""
        uri = self.path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_info (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS samples (
              id INTEGER PRIMARY KEY,
              timestamp_utc TEXT NOT NULL,
              print_state TEXT NOT NULL,
              filename TEXT NOT NULL,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY,
              timestamp_utc TEXT NOT NULL,
              kind TEXT NOT NULL,
              payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS frames (
              id INTEGER PRIMARY KEY,
              timestamp_utc TEXT NOT NULL,
              relative_path TEXT NOT NULL UNIQUE,
              sha256 TEXT NOT NULL,
              byte_count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS findings (
              id INTEGER PRIMARY KEY,
              timestamp_utc TEXT NOT NULL,
              metric TEXT NOT NULL,
              severity REAL NOT NULL,
              confidence REAL NOT NULL,
              source TEXT NOT NULL,
              notes TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT OR REPLACE INTO schema_info(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def sample(
        self,
        connection: sqlite3.Connection,
        timestamp: str,
        state: str,
        filename: str,
        payload: Any,
    ) -> None:
        connection.execute(
            "INSERT INTO samples(timestamp_utc, print_state, filename, payload_json) VALUES (?, ?, ?, ?)",
            (timestamp, state, filename, json.dumps(payload, separators=(",", ":"))),
        )

    def event(
        self, connection: sqlite3.Connection, timestamp: str, kind: str, payload: Any
    ) -> None:
        connection.execute(
            "INSERT INTO events(timestamp_utc, kind, payload_json) VALUES (?, ?, ?)",
            (timestamp, kind, json.dumps(payload, separators=(",", ":"))),
        )

    def frame(
        self,
        connection: sqlite3.Connection,
        timestamp: str,
        relative_path: str,
        sha256: str,
        byte_count: int,
    ) -> None:
        connection.execute(
            "INSERT INTO frames(timestamp_utc, relative_path, sha256, byte_count) VALUES (?, ?, ?, ?)",
            (timestamp, relative_path, sha256, byte_count),
        )

    def finding(
        self, connection: sqlite3.Connection, finding: Finding, timestamp: str | None = None
    ) -> None:
        connection.execute(
            """INSERT INTO findings(timestamp_utc, metric, severity, confidence, source, notes)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                timestamp or self._now(),
                finding.metric,
                finding.severity,
                finding.confidence,
                finding.source,
                finding.notes,
            ),
        )


def read_findings(session_dir: str | Path) -> list[Finding]:
    store = SessionStore(Path(session_dir) / "telemetry.sqlite3")
    if not store.path.exists():
        raise FileNotFoundError(store.path)
    with store.read_only() as connection:
        table_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'findings'"
        ).fetchone()
        rows = (
            connection.execute(
                "SELECT metric, severity, confidence, source, notes FROM findings ORDER BY id"
            ).fetchall()
            if table_exists
            else []
        )
    return [Finding(**dict(row)) for row in rows]


def session_summary(session_dir: str | Path) -> dict[str, Any]:
    database = Path(session_dir) / "telemetry.sqlite3"
    if not database.exists():
        raise FileNotFoundError(database)
    store = SessionStore(database)
    with store.read_only() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        counts = {
            table: connection.execute(
                {
                    "samples": "SELECT COUNT(*) FROM samples",
                    "events": "SELECT COUNT(*) FROM events",
                    "frames": "SELECT COUNT(*) FROM frames",
                    "findings": "SELECT COUNT(*) FROM findings",
                }[table]
            ).fetchone()[0]
            if table in tables
            else 0
            for table in ("samples", "events", "frames", "findings")
        }
        # rowid keeps sessions created by the original 0.1 schema readable.
        last_sample = (
            connection.execute(
                "SELECT timestamp_utc, print_state, filename FROM samples ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if "samples" in tables
            else None
        )
        schema_row = (
            connection.execute(
                "SELECT value FROM schema_info WHERE key = 'schema_version'"
            ).fetchone()
            if "schema_info" in tables
            else None
        )
    schema_version = int(schema_row[0]) if schema_row else 1
    return {
        "schema_version": schema_version,
        "counts": counts,
        "last_sample": dict(last_sample) if last_sample else None,
    }
