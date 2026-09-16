"""Offline regression tests; a loopback test server is never a real printer."""
import contextlib
import http.server
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import zipfile

SPEC = importlib.util.spec_from_file_location("export_workspace", Path(__file__).parents[1] / "export_workspace.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class SourcesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        self.root.mkdir()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_source_bytes_and_license_preserved(self):
        original = self.write("src/app.py", '"""Original file."""\nprint("hello")\n')
        self.write("LICENSE", "Existing license must remain unchanged.\n")
        entries, report = module.collect_sources(self.root)
        content = dict(entries)
        self.assertEqual(content["source/src/app.py"], original.read_bytes())
        self.assertIn("source/LICENSE", content)
        self.assertEqual(len(report["included"]), 2)
        self.assertTrue(report["requires_human_review"])

    def test_private_directories_and_files_excluded(self):
        for name in ("work/lan-private/token.txt", "data/photo.txt", ".git/config",
                     ".venv/library.py", "src/.env", "src/certificate.pem", "config/token.txt"):
            self.write(name, "DO-NOT-EXPORT")
        entries, report = module.collect_sources(self.root)
        self.assertFalse(entries)
        self.assertGreater(len(report["omitted"]), 0)

    def test_embedded_secret_withheld_not_changed(self):
        path = self.write("src/settings.py", 'token = "a-sensitive-token-do-not-copy"\n')
        before = path.read_bytes()
        entries, report = module.collect_sources(self.root)
        self.assertFalse(entries)
        self.assertIn("possible_embedded_credential", report["omitted"][0]["reason"])
        self.assertEqual(before, path.read_bytes())

    def test_utf8_unicode_preserved(self):
        path = self.write("docs/unicode.md", "Espa\u00f1a \u2014 original user documentation\n")
        entries, _ = module.collect_sources(self.root)
        self.assertEqual(entries[0][1], path.read_bytes())

    def test_missing_source_is_explicit(self):
        entries, report = module.collect_sources(self.root / "missing")
        self.assertFalse(entries)
        self.assertFalse(report["root_found"])
        self.assertIn("error", report)

    def test_binary_and_unknown_file_withheld(self):
        self.write("src/icon.png", "not really an image")
        self.write("src/bad.py", "nul\x00byte")
        entries, report = module.collect_sources(self.root)
        self.assertFalse(entries)
        self.assertEqual(len(report["omitted"]), 2)

    def test_symlink_not_followed(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("private content")
        (self.root / "src").mkdir()
        try:
            (self.root / "src/leak.py").symlink_to(outside)
        except OSError:
            self.skipTest("Symlinks unavailable on this platform")
        entries, report = module.collect_sources(self.root)
        self.assertFalse(entries)
        self.assertEqual(report["omitted"][0]["reason"], "link_or_reparse_point")

    def test_package_offline_has_manifest_and_no_public_ready_claim(self):
        self.write("src/app.py", 'print("ok")\n')
        output = Path(self.temp.name) / "output"
        with contextlib.redirect_stdout(io.StringIO()):
            path = module.create_package(self.root, output, module.DEFAULT_URL, offline=True)
            other = module.create_package(self.root, output, module.DEFAULT_URL, offline=True)
        self.assertNotEqual(path, other)
        with zipfile.ZipFile(path) as archive:
            self.assertIsNone(archive.testzip())
            manifest = json.loads(archive.read("EXPORT_MANIFEST.json"))
            self.assertFalse(manifest["public_release_ready"])
            self.assertFalse(manifest["history_report"]["pagination_finished"])
            self.assertIn("source/src/app.py", archive.namelist())


class HistoryTests(unittest.TestCase):
    def test_short_pages_and_page_count_not_treated_as_total(self):
        jobs = [{"job_id": str(i), "status": "completed", "user": "private-user",
                 "metadata": {"private": "not exported"}} for i in range(5)]
        offsets = []
        def fetch(start, limit, before):
            offsets.append(start)
            page = jobs[start:start + 2]
            return {"jobs": page, "count": len(page)}
        output = module.export_history(fetch, page_size=100)
        self.assertTrue(output["pagination_finished"])
        self.assertEqual(offsets, [0, 2, 4, 5])
        self.assertEqual(output["exported_job_count"], 5)
        self.assertFalse(output["quality_assessed"])
        self.assertFalse(output["transactional_snapshot"])
        self.assertNotIn("user", output["jobs"][0])
        self.assertNotIn("metadata", output["jobs"][0])

    def test_duplicate_pages_are_incomplete(self):
        output = module.export_history(lambda *_: {"jobs": [{"job_id": "1"}]})
        self.assertFalse(output["pagination_finished"])
        self.assertEqual(output["exported_job_count"], 1)
        self.assertTrue(output["warnings"])

    def test_http_unauthorized_is_not_bypassed(self):
        def fetch(*_):
            raise urllib.error.HTTPError("http://127.0.0.1", 401, "Unauthorized", {}, None)
        output = module.export_history(fetch)
        self.assertFalse(output["pagination_finished"])
        self.assertIn("No authentication bypass", output["warnings"][0])

    def test_network_failure_preserves_prior_records(self):
        def fetch(start, *_):
            if start:
                raise urllib.error.URLError("unavailable")
            return {"jobs": [{"job_id": "1"}]}
        output = module.export_history(fetch)
        self.assertFalse(output["pagination_finished"])
        self.assertEqual(output["exported_job_count"], 1)

    def test_malformed_data_is_incomplete(self):
        for payload in ({"jobs": None}, {"jobs": [123]}, {"jobs": [{}]}):
            with self.subTest(payload=payload):
                output = module.export_history(lambda *_, value=payload: value)
                self.assertFalse(output["pagination_finished"])
                self.assertTrue(output["warnings"])

    def test_public_hosts_and_credentials_rejected(self):
        for url in ("https://example.com", "http://8.8.8.8", "http://169.254.169.254",
                    "http://user:secret@192.168.0.16", "http://192.168.0.16/history",
                    "http://192.168.0.16?token=abc", "http://192.168.0.16:70000"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                module.HistoryReader(url)

    def test_private_origin_accepted(self):
        reader = module.HistoryReader("http://192.168.0.16:7125/")
        self.assertEqual(reader.base_url, "http://192.168.0.16:7125")

    def test_get_only_integration_with_local_simulator(self):
        requests = []
        jobs = [{"job_id": str(i), "filename": "cube-%s.gcode" % i,
                 "print_duration": 20.0, "filament_used": 14.0} for i in range(3)]
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.command, self.path))
                parsed = urllib.parse.urlsplit(self.path)
                if parsed.path != "/server/history/list":
                    self.send_error(404)
                    return
                start = int(urllib.parse.parse_qs(parsed.query)["start"][0])
                body = json.dumps({"result": {"jobs": jobs[start:start + 1], "count": 3}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_):
                return
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            reader = module.HistoryReader("http://127.0.0.1:%d" % server.server_port)
            output = module.export_history(reader.page)
            self.assertTrue(output["pagination_finished"])
            self.assertEqual(output["exported_job_count"], 3)
            self.assertEqual(len(requests), 4)
            self.assertTrue(all(method == "GET" for method, _ in requests))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_redirect_is_refused(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://192.168.0.17/other")
                self.end_headers()
            def log_message(self, *_):
                return
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            reader = module.HistoryReader("http://127.0.0.1:%d" % server.server_port)
            output = module.export_history(reader.page)
            self.assertFalse(output["pagination_finished"])
            self.assertIn("302", output["warnings"][0])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class BoundaryTests(unittest.TestCase):
    def test_non_object_pages_are_incomplete(self):
        for value in (None, [], "bad", 12):
            with self.subTest(value=value):
                result = module.export_history(lambda *_: value)
                self.assertFalse(result["pagination_finished"])
                self.assertTrue(result["warnings"])

    def test_invalid_history_fields_are_not_published(self):
        for field, value in (("filename", {}), ("exists", "yes"),
                             ("print_duration", float("nan")),
                             ("filament_used", True), ("end_time", -1)):
            with self.subTest(field=field, value=value):
                result = module.export_history(lambda *_: {"jobs": [{"job_id": "1", field: value}]})
                self.assertFalse(result["pagination_finished"])
                self.assertEqual(result["exported_job_count"], 0)

    def test_empty_ids_rejected(self):
        result = module.export_history(lambda *_: {"jobs": [{"job_id": ""}]})
        self.assertFalse(result["pagination_finished"])
        self.assertEqual(result["exported_job_count"], 0)

    def test_null_end_time_allowed(self):
        def fetch(start, *_):
            return {"jobs": [] if start else [{"job_id": "1", "end_time": None}]}
        result = module.export_history(fetch)
        self.assertTrue(result["pagination_finished"])
        self.assertIsNone(result["jobs"][0]["end_time"])

    def test_invalid_pagination_arguments(self):
        for value in (0, -1, True, 1.5, 1001):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.export_history(lambda *_: {"jobs": []}, page_size=value)

    def test_invalid_time_budgets(self):
        for value in (0, -1, True, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.export_history(lambda *_: {"jobs": []}, max_seconds=value)

    def test_invalid_timeouts(self):
        for value in (0, -1, True, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                module.HistoryReader("http://127.0.0.1:7125", timeout=value)

    def test_finite_json_encoding(self):
        with self.assertRaises(ValueError):
            module.json_bytes({"value": float("nan")})


if __name__ == "__main__":
    unittest.main()
