import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from klipperlearn.dataset import audit_session, build_training_manifest, load_training_rows
from klipperlearn.domain import Finding
from klipperlearn.storage import SessionStore


class DatasetTests(unittest.TestCase):
    @staticmethod
    def _session(root: Path, name: str, metric: str) -> Path:
        session = root / name
        frames = session / "frames"
        frames.mkdir(parents=True)
        image = b"test-image-bytes"
        frame = frames / "000001.jpg"
        frame.write_bytes(image)
        (session / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "machine": {"name": "test-printer"},
                    "material": {"type": "PLA"},
                    "camera": {"view": "front"},
                    "config_sha256": "abc",
                }
            ),
            encoding="utf-8",
        )
        store = SessionStore(session / "telemetry.sqlite3")
        with store.open() as database:
            store.frame(
                database,
                "2026-01-01T00:00:00+00:00",
                "frames/000001.jpg",
                hashlib.sha256(image).hexdigest(),
                len(image),
            )
            store.finding(database, Finding(metric, 0.4, 1.0, "human"))
        return session

    def test_audit_and_manifest_preserve_missing_label_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            training = self._session(root, "train", "stringing")
            validation = self._session(root, "validation", "warping")
            database = training / "telemetry.sqlite3"
            database_hash = hashlib.sha256(database.read_bytes()).hexdigest()
            audit = audit_session(training)
            self.assertTrue(audit["eligible_for_training"])
            self.assertIn("warping", audit["missing_human_labels"])
            self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), database_hash)

            manifest = build_training_manifest([training], [validation])
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            rows = load_training_rows(manifest_path)

        training_row = next(row for row in rows if row["split"] == "train")
        self.assertEqual(sum(training_row["label_mask"]), 1)
        self.assertTrue(training_row["label_mask"][4])

    def test_split_overlap_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = self._session(Path(directory), "same", "stringing")
            with self.assertRaises(ValueError):
                build_training_manifest([session], [session])
