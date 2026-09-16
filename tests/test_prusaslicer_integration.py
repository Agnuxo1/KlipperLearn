"""Exercise PrusaSlicer's appended temporary-file contract without the slicer.

SPDX-License-Identifier: GPL-3.0-or-later
No printer, network service, GUI or installed slicer is used by these tests.
"""

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ADAPTER = Path(__file__).resolve().parents[1] / "integrations/orca/klipperlearn_manifest.py"
spec = importlib.util.spec_from_file_location("kl_prusa_manifest_contract", ADAPTER)
manifest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manifest)


class PrusaSlicerManifestContractTests(unittest.TestCase):
    """Check the documented CLI boundary, not native PrusaSlicer execution."""

    def invoke(self, source, output):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = manifest.main(["--output-dir", str(output), str(source)])
        return code, stdout.getvalue(), stderr.getvalue()

    def test_temporary_unicode_path_is_appended_and_never_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "temporary part café.gcode.tmp"
            raw = b"; synthetic contract fixture\r\nG1 X2 Y3 E0.1\r\n"
            source.write_bytes(raw)
            naming = Path(str(source) + ".output_name")
            naming.write_text("original-output.gcode\n", encoding="utf-8")
            output = root / "evidence sidecars"
            code, stdout, stderr = self.invoke(source, output)
            self.assertEqual(code, 0, stderr)
            self.assertEqual(source.read_bytes(), raw)
            self.assertEqual(naming.read_text(), "original-output.gcode\n")
            files = list(output.iterdir())
            self.assertEqual(len(files), 1)
            record = json.loads(files[0].read_text())
            self.assertEqual(record["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(record["byte_count"], len(raw))
            self.assertFalse(record["geometry_verified"])
            self.assertFalse(record["quality_assessed"])
            self.assertFalse(record["source_modified"])
            self.assertNotIn(str(source), stdout)
            self.assertNotIn(source.name, files[0].read_text())

    def test_slicer_environment_does_not_leak_or_rename_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.tmp"
            source.write_bytes(b"G1 X1\n")
            with patch.dict(
                "os.environ",
                {
                    "SLIC3R_PP_HOST": "PRIVATE-HOST-MARKER",
                    "SLIC3R_PP_OUTPUT_NAME": "PRIVATE-FILENAME-MARKER",
                },
            ):
                code, out, err = self.invoke(source, root / "evidence")
            self.assertEqual(code, 0, err)
            published = next((root / "evidence").iterdir()).read_text()
            self.assertNotIn("PRIVATE-", published + out + err)
            self.assertFalse(Path(str(source) + ".output_name").exists())

    def test_last_script_records_prior_modifications_but_makes_none(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.gcode"
            source.write_bytes(b"G1 X1\n; earlier postprocessor\n")
            before = source.read_bytes()
            code, _, err = self.invoke(source, root / "evidence")
            self.assertEqual(code, 0, err)
            record = json.loads(next((root / "evidence").iterdir()).read_text())
            self.assertEqual(record["sha256"], hashlib.sha256(before).hexdigest())
            self.assertEqual(source.read_bytes(), before)

    def test_repeated_invocation_preserves_the_same_sidecar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.gcode"
            source.write_bytes(b"G1 X1\n")
            output = root / "evidence"
            self.assertEqual(self.invoke(source, output)[0], 0)
            target = next(output.iterdir())
            before = target.read_bytes()
            self.assertEqual(self.invoke(source, output)[0], 0)
            self.assertEqual(list(output.iterdir()), [target])
            self.assertEqual(target.read_bytes(), before)

    def test_failure_is_nonzero_without_creating_a_false_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "empty.gcode"
            source.write_bytes(b"")
            output = root / "evidence"
            code, out, err = self.invoke(source, output)
            self.assertEqual(code, 1)
            self.assertEqual(out, "")
            self.assertIn("failed", err)
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
