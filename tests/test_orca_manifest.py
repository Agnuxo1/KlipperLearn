"""Synthetic sliced-file tests; never execute any G-code."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("manifest", Path(__file__).parents[1] /
    "integrations/orca/klipperlearn_manifest.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "fixture.gcode"
        self.content = b"; SYNTHETIC FIXTURE - DO NOT PRINT\nG1 X1 Y2 E0.1 F1200\n"
        self.source.write_bytes(self.content)

    def test_fingerprint_matches_and_preserves_source(self):
        record = module.fingerprint(self.source)
        self.assertEqual(record["sha256"], hashlib.sha256(self.content).hexdigest())
        self.assertEqual(record["byte_count"], len(self.content))
        self.assertEqual(self.source.read_bytes(), self.content)
        self.assertFalse(record["quality_assessed"])
        self.assertFalse(record["geometry_verified"])
        self.assertFalse(record["parameters_inferred"])

    def test_manifest_omits_private_path(self):
        text = json.dumps(module.fingerprint(self.source))
        self.assertNotIn(self.source.name, text)
        self.assertNotIn(str(self.root), text)

    def test_repeated_export_is_idempotent(self):
        a = module.write_manifest(self.source, self.root / "output")
        b = module.write_manifest(self.source, self.root / "output")
        self.assertEqual(a, b)
        self.assertEqual(len(list(a.parent.iterdir())), 1)

    def test_conflicting_manifest_is_never_overwritten(self):
        target = module.write_manifest(self.source, self.root / "output")
        target.write_text("different")
        with self.assertRaises(ValueError):
            module.write_manifest(self.source, self.root / "output")
        self.assertEqual(target.read_text(), "different")

    def test_empty_file_rejected(self):
        self.source.write_bytes(b"")
        with self.assertRaises(ValueError):
            module.fingerprint(self.source)

    def test_directory_rejected(self):
        with self.assertRaises(ValueError):
            module.fingerprint(self.root)

    def test_input_symlink_rejected(self):
        link = self.root / "link.gcode"
        try:
            link.symlink_to(self.source)
        except OSError:
            self.skipTest("Symlinks unavailable")
        with self.assertRaises(ValueError):
            module.fingerprint(link)

    def test_cli_success(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code = module.main(["--output-dir", str(self.root / "output"), str(self.source)])
        self.assertEqual(code, 0)
        self.assertEqual(self.source.read_bytes(), self.content)

    def test_cli_missing_file_fails(self):
        with contextlib.redirect_stderr(io.StringIO()):
            code = module.main([str(self.root / "missing.gcode")])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
