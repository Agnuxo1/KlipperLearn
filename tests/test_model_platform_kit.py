"""Offline regression tests for the distributable original coupon.

SPDX-License-Identifier: GPL-3.0-or-later
"""

import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "model_platform_kit", ROOT / "tools/build_publication_kit.py"
)
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


class ModelPlatformKitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = (ROOT / kit.COUPON).read_bytes()

    def test_original_hash_and_geometry(self):
        report = kit.audit_stl(self.data)
        self.assertEqual(
            report["sha256"], "aca62abefe6636652ebcb7f7821b8893b39e98c0e337bca5bdc004c3f7325630"
        )
        self.assertEqual(report["dimensions_mm"], [40, 30, 12])
        self.assertEqual(report["triangles"], 7756)
        self.assertEqual(report["geometric_volume_mm3"], 2620)
        self.assertEqual(report["connected_components"], 1)
        self.assertFalse(report["physically_tested"])
        self.assertFalse(report["native_slicer_acceptance_tested"])

    def test_truncated_input_is_rejected(self):
        for data in (b"", self.data[:83], self.data[:-1], self.data + b"x"):
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                kit.audit_stl(data)

    def test_nonfinite_coordinate_is_rejected(self):
        data = bytearray(self.data)
        struct.pack_into("<f", data, 96, float("nan"))
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            kit.audit_stl(bytes(data))

    def test_reversed_stored_normal_is_rejected(self):
        data = bytearray(self.data)
        normal = struct.unpack_from("<3f", data, 84)
        struct.pack_into("<3f", data, 84, *(-x for x in normal))
        with self.assertRaisesRegex(ValueError, "normal"):
            kit.audit_stl(bytes(data))

    def test_degenerate_face_is_rejected(self):
        data = bytearray(self.data)
        data[108:120] = data[96:108]
        with self.assertRaisesRegex(ValueError, "Degenerate"):
            kit.audit_stl(bytes(data))

    def test_open_boundary_is_rejected(self):
        data = bytearray(self.data[:-50])
        struct.pack_into("<I", data, 80, 7755)
        with self.assertRaisesRegex(ValueError, "edge"):
            kit.audit_stl(bytes(data))

    def test_package_is_deterministic_and_flat(self):
        files = kit.package_files(ROOT)
        first = kit.archive_bytes(files)
        self.assertEqual(first, kit.archive_bytes(dict(reversed(list(files.items())))))
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read(kit.STL_NAME), self.data)
            self.assertTrue(all(Path(n).name == n for n in archive.namelist()))
            self.assertIn("COPYING.txt", archive.namelist())
            self.assertNotIn(".git", archive.namelist())

    def test_unsafe_archive_paths_are_rejected(self):
        for name in ("../secret", "/secret", "dir/file", "dir\\file", ".."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                kit.archive_bytes({name: b"data"})

    def test_checksums_match_every_payload(self):
        files = kit.package_files(ROOT)
        entries = files["SHA256SUMS.txt"].decode().splitlines()
        self.assertEqual(len(entries), len(files) - 1)
        for line in entries:
            checksum, name = line.split("  ", 1)
            self.assertEqual(checksum, hashlib.sha256(files[name]).hexdigest())

    def test_standalone_source_reproduces_original_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            script = folder / "export_calibration_card.py"
            script.write_bytes(kit.source_exporter(ROOT))
            args = [sys.executable, str(script)]
            first = subprocess.run(args, cwd=folder, capture_output=True, timeout=20)
            self.assertEqual(first.returncode, 0, first.stderr.decode())
            target = folder / kit.STL_NAME
            self.assertEqual(target.read_bytes(), self.data)
            second = subprocess.run(args, cwd=folder, capture_output=True, timeout=20)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(target.read_bytes(), self.data)

    def test_listing_exposes_scope_and_canonical_source(self):
        text = (ROOT / "publication/listing.en.txt").read_text(encoding="utf-8")
        for phrase in (
            "https://github.com/Agnuxo1/KlipperLearn",
            "GPL-3.0-or-later",
            "NOT a photograph",
            "Physical validation",
            "AI assistance",
            "without KlipperLearn",
            "not a delivered Android installer",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
