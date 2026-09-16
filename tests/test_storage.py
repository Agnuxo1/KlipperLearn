from pathlib import Path
import tempfile
import unittest

from klipperlearn.domain import Finding
from klipperlearn.storage import SessionStore, read_findings, session_summary


class StorageTests(unittest.TestCase):
    def test_round_trip_finding_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = Path(directory)
            store = SessionStore(session / "telemetry.sqlite3")
            with store.open() as database:
                store.sample(
                    database, "2026-01-01T00:00:00+00:00", "printing", "test.gcode", {"a": 1}
                )
                store.finding(database, Finding("stringing", 0.5, 0.9, "human", "visible"))
            self.assertEqual(len(read_findings(session)), 1)
            self.assertEqual(session_summary(session)["counts"]["samples"], 1)
