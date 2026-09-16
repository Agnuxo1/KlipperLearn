import tempfile
import unittest
from unittest.mock import patch
from klipperlearn.__main__ import main


class CompanionCLITests(unittest.TestCase):
    def test_explicit_moonraker_is_used_without_starting_a_server(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments = [
                "klipperlearn",
                "serve",
                "--session-root",
                directory,
                "--mobile-token",
                "test-key-long-enough",
                "--moonraker",
                "http://printer.test:7125",
            ]
            with (
                patch("sys.argv", arguments),
                patch("uvicorn.run") as run,
                patch("klipperlearn.companion.install_companion") as install,
            ):
                main()
                self.assertEqual(install.call_args.args[2], "http://printer.test:7125")
                self.assertEqual(run.call_count, 1)

    def test_companion_rejects_credentials_and_missing_token(self):
        for extra in [
            ["--moonraker", "http://printer.test"],
            [
                "--moonraker",
                "http://user:secret@printer.test",
                "--mobile-token",
                "test-key-long-enough",
            ],
        ]:
            with patch("sys.argv", ["klipperlearn", "serve", *extra]), patch("uvicorn.run") as run:
                with self.assertRaises(SystemExit):
                    main()
                run.assert_not_called()

    def test_one_click_cli_requires_exact_origin_and_private_network(self):
        for extra in [
            ["--local-connect-origin", "https://127.0.0.1:8765"],
            [
                "--local-connect-origin",
                "https://other:8765",
                "--local-connect-network",
                "192.168.1.0/24",
            ],
            [
                "--local-connect-origin",
                "https://127.0.0.1:8765",
                "--local-connect-network",
                "0.0.0.0/0",
            ],
        ]:
            with (
                patch(
                    "sys.argv",
                    ["klipperlearn", "serve", "--moonraker", "http://printer.test", *extra],
                ),
                patch("uvicorn.run") as run,
            ):
                with self.assertRaises(SystemExit):
                    main()
                run.assert_not_called()
