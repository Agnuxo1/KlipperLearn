from pathlib import Path
import tempfile
import unittest

from klipperlearn.config import load_settings


class ConfigTests(unittest.TestCase):
    def test_loads_provenance_and_hashes_source(self) -> None:
        content = """
[moonraker]
url = "http://printer.local:7125"
[camera]
snapshot_url = "http://printer.local/webcam/snapshot"
view = "front"
[observer]
mode = "observe"
[machine]
name = "test-printer"
[material]
type = "PLA"
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(content, encoding="utf-8")
            settings = load_settings(path)
        self.assertEqual(settings.machine["name"], "test-printer")
        self.assertEqual(settings.material["type"], "PLA")
        self.assertEqual(settings.camera["view"], "front")
        self.assertEqual(len(settings.config_sha256), 64)

    def test_rejects_control_mode_and_embedded_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(
                '[moonraker]\nurl = "http://printer.local:7125"\n[observer]\nmode = "control"\n',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_settings(path)
            path.write_text(
                '[moonraker]\nurl = "http://user:secret@printer.local:7125"\n'
                '[observer]\nmode = "observe"\n',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_settings(path)


if __name__ == "__main__":
    unittest.main()
