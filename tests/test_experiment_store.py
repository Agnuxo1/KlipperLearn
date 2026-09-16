from __future__ import annotations

import json
from contextlib import closing
import math
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest

from klipperlearn.experiment_store import DB_FILENAME, ExperimentStore, WEIGHTS_VERSION


class ExperimentStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name) / "store"
        self.context = {
            "printer_id": "anycubic-4max-pro",
            "model_sha256": "a" * 64,
            "material": "PLA",
            "nozzle_mm": 0.4,
            "session_id": "session-20260908-1",
        }
        self.parameters = {
            "temperature": {"hotend": 205, "bed": 60},
            "speed_mm_s": 45.0,
            "source": "gcode-and-klipper-config",
        }

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_persists_across_restart_and_keeps_provenance(self) -> None:
        store = ExperimentStore(self.root)
        trial = store.create_trial(self.context, self.parameters, objective_score=20.0)

        self.assertRegex(trial["id"], re.compile(r"^[0-9a-f]{32}$"))
        restarted = ExperimentStore(self.root)
        loaded = restarted.get_trial(trial["id"])
        self.assertEqual(loaded["context"], self.context)
        self.assertEqual(loaded["parameters"], self.parameters)
        self.assertEqual(loaded["status"], "pending")
        self.assertEqual(loaded["weights_version"], WEIGHTS_VERSION)

    def test_five_star_rating_with_objective_twenty_scores_sixty_eight(self) -> None:
        store = ExperimentStore(self.root)
        trial = store.create_trial(self.context, self.parameters, objective_score=20)
        rated = store.rate_trial(
            trial["id"],
            {"speed": 5, "surface": 5, "geometry": 5},
            "revisión humana",
        )

        self.assertEqual(rated["human_score"], 100.0)
        self.assertEqual(rated["score"], 68.0)
        self.assertEqual(rated["raw_scores"], {"objective": 20.0, "human": 100.0, "score": 68.0})
        self.assertEqual(
            rated["weights"], {"objective": 0.4, "human": 0.6, "version": WEIGHTS_VERSION}
        )

    def test_zero_is_a_real_score_but_missing_input_is_pending(self) -> None:
        store = ExperimentStore(self.root)
        no_rating = store.create_trial(self.context, self.parameters, objective_score=0)
        self.assertIsNone(no_rating["score"])
        self.assertEqual(no_rating["status"], "pending")

        zero = store.rate_trial(no_rating["id"], {"speed": 0, "surface": 0, "geometry": 0})
        self.assertEqual(zero["human_score"], 0.0)
        self.assertEqual(zero["score"], 0.0)
        self.assertEqual(zero["status"], "scored")

        objective_missing = store.create_trial(self.context, self.parameters)
        rated_without_objective = store.rate_trial(
            objective_missing["id"], {"speed": 5, "surface": 5, "geometry": 5}
        )
        self.assertEqual(rated_without_objective["human_score"], 100.0)
        self.assertIsNone(rated_without_objective["score"])
        self.assertEqual(rated_without_objective["status"], "pending")

    def test_rating_revisions_are_append_only_and_exported(self) -> None:
        store = ExperimentStore(self.root)
        trial = store.create_trial(self.context, self.parameters, objective_score=20)
        first = {"speed": 1, "surface": 2, "geometry": 3}
        second = {"speed": 5, "surface": 4, "geometry": 3}
        store.rate_trial(trial["id"], first, "primera revisión")
        store.rate_trial(trial["id"], second, "segunda revisión")

        loaded = store.get_trial(trial["id"])
        self.assertEqual(len(loaded["revisions"]), 2)
        self.assertEqual(loaded["revisions"][0]["ratings"], first)
        self.assertEqual(loaded["revisions"][0]["comment"], "primera revisión")
        self.assertEqual(loaded["revisions"][1]["ratings"], second)
        self.assertEqual(loaded["rating_revision"], 2)

        records = [json.loads(line) for line in store.export_jsonl().splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(len(records[0]["revisions"]), 2)
        self.assertEqual(records[0]["revisions"][0]["raw_scores"]["human"], 40.0)
        self.assertEqual(records[0]["revisions"][1]["raw_scores"]["human"], 80.0)

    def test_invalid_nan_huge_and_boolean_numeric_inputs_raise_value_error(self) -> None:
        invalid_objectives = (math.nan, math.inf, -math.inf, 10**100, True, -1, 101)
        for objective in invalid_objectives:
            with self.subTest(objective=objective):
                with self.assertRaises(ValueError):
                    ExperimentStore(self.root).create_trial(
                        self.context, self.parameters, objective_score=objective
                    )

        for nozzle in (math.nan, math.inf, 10**100, True):
            bad_context = dict(self.context, nozzle_mm=nozzle)
            with self.subTest(nozzle=nozzle):
                with self.assertRaises(ValueError):
                    ExperimentStore(self.root).create_trial(bad_context, self.parameters)

        bad_ratings = (
            {"speed": True, "surface": 0, "geometry": 0},
            {"speed": 6, "surface": 0, "geometry": 0},
            {"speed": 0, "surface": 0, "geometry": 0.0},
            {"speed": 0, "surface": 0},
            {"speed": 0, "surface": 0, "geometry": 0, "extra": 1},
        )
        store = ExperimentStore(self.root)
        trial = store.create_trial(self.context, self.parameters, objective_score=20)
        for ratings in bad_ratings:
            with self.subTest(ratings=ratings):
                with self.assertRaises(ValueError):
                    store.rate_trial(trial["id"], ratings)

        for evidence in ({"value": math.nan}, {"value": 10**100}, {"text": "x" * (256 * 1024)}):
            with self.subTest(evidence=evidence):
                with self.assertRaises(ValueError):
                    store.create_trial(self.context, self.parameters, evidence=evidence)

    def test_missing_trial_is_key_error_and_pagination_is_deterministic(self) -> None:
        store = ExperimentStore(self.root)
        first = store.create_trial(self.context, self.parameters)
        second = store.create_trial(self.context, self.parameters)
        with self.assertRaises(KeyError):
            store.get_trial("0" * 32)
        with self.assertRaises(KeyError):
            store.rate_trial("0" * 32, {"speed": 0, "surface": 0, "geometry": 0})
        self.assertEqual([item["id"] for item in store.list_trials(1)], [first["id"]])
        self.assertEqual([item["id"] for item in store.list_trials(1, 1)], [second["id"]])

    def test_manual_jpeg_is_persisted_hashed_and_exported(self) -> None:
        store = ExperimentStore(self.root)
        trial = store.create_trial(self.context, self.parameters)
        jpeg = b"\xff\xd8manual-result\xff\xd9"

        saved = store.add_photo(trial["id"], jpeg, "resultado.jpg")

        self.assertEqual(len(saved["photos"]), 1)
        photo = saved["photos"][0]
        self.assertEqual(photo["original_name"], "resultado.jpg")
        self.assertEqual(photo["byte_count"], len(jpeg))
        self.assertEqual((self.root / photo["relative_path"]).read_bytes(), jpeg)
        exported = json.loads(store.export_jsonl().splitlines()[0])
        self.assertEqual(exported["photos"], saved["photos"])

    def test_manual_photo_rejects_missing_trial_and_invalid_image(self) -> None:
        store = ExperimentStore(self.root)
        trial = store.create_trial(self.context, self.parameters)
        with self.assertRaises(ValueError):
            store.add_photo(trial["id"], b"not-a-jpeg")
        with self.assertRaises(KeyError):
            store.add_photo("0" * 32, b"\xff\xd8ok\xff\xd9")
        self.assertEqual(
            list((self.root / "assets").rglob("*.jpg")) if (self.root / "assets").exists() else [],
            [],
        )

    def test_backup_is_restorable_and_hashes_only_database_and_assets(self) -> None:
        store = ExperimentStore(self.root)
        trial = store.create_trial(
            self.context,
            self.parameters,
            objective_score=20,
            evidence={"path": "../../outside-secret.txt", "note": "metadata only"},
        )
        store.rate_trial(trial["id"], {"speed": 5, "surface": 5, "geometry": 5})
        assets = self.root / "assets" / "photos"
        assets.mkdir(parents=True)
        (assets / "sample.txt").write_text("local asset", encoding="utf-8")

        backup = store.backup(self.root.parent / "experiment-backup")
        self.assertEqual(backup.name, "experiment-backup")
        manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn(DB_FILENAME, manifest["files"])
        self.assertIn("assets/photos/sample.txt", manifest["files"])
        self.assertEqual(
            (backup / "assets" / "photos" / "sample.txt").read_text(encoding="utf-8"),
            "local asset",
        )

        with closing(sqlite3.connect(backup / DB_FILENAME)) as connection:
            row = connection.execute("SELECT COUNT(*) FROM trials").fetchone()
            self.assertEqual(row[0], 1)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM rating_revisions").fetchone()[0], 1
            )

    def test_backup_rejects_symlink_assets_when_platform_allows_them(self) -> None:
        assets = self.root / "assets"
        assets.mkdir(parents=True)
        target = self.root / "outside.txt"
        target.write_text("outside", encoding="utf-8")
        try:
            (assets / "link.txt").symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are unavailable on this platform")
        with self.assertRaises(ValueError):
            ExperimentStore(self.root).backup(self.root.parent / "symlink-backup")


if __name__ == "__main__":
    unittest.main()
