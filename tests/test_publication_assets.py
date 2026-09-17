"""Offline checks for the public site's privacy, links and scope labels."""

from html.parser import HTMLParser
from pathlib import Path
import unittest
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = []

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "docs/index.html").read_text(encoding="utf-8")
        self.page = Page()
        self.page.feed(self.text)

    def test_no_scripts_forms_or_embedded_third_parties(self):
        self.assertFalse(
            {tag for tag, _ in self.page.nodes} & {"script", "form", "iframe", "object", "embed"}
        )
        self.assertIn("connect-src 'none'", self.text)

    def test_assets_exist_inside_the_public_site(self):
        for tag, attributes in self.page.nodes:
            link = attributes.get("src") or (
                attributes.get("href")
                if tag == "link" and attributes.get("rel") in ("stylesheet", "icon")
                else None
            )
            if link:
                self.assertFalse(urlsplit(link).scheme)
                target = (ROOT / "docs" / link).resolve()
                self.assertTrue(target.is_relative_to((ROOT / "docs").resolve()))
                self.assertTrue(target.is_file())

    def test_all_ten_integration_links_resolve_to_our_sources(self):
        for name in (
            "klipper",
            "moonraker",
            "orca",
            "prusaslicer",
            "cura",
            "octoprint",
            "mainsail",
            "fluidd",
            "kiauh",
            "voron",
        ):
            self.assertIn("/integrations/" + name + '"', self.text)
            self.assertTrue((ROOT / "integrations" / name / "README.md").is_file())

    def test_reference_demo_matches_canonical_sources(self):
        for name in ("index.html", "app.js", "core.js", "demo.js", "style.css"):
            self.assertEqual(
                (ROOT / "docs/demo" / name).read_bytes(), (ROOT / "reference" / name).read_bytes()
            )
        self.assertEqual(
            (ROOT / "docs/demo/LICENSE.txt").read_bytes(),
            (ROOT / "LICENSES/MIT-reference.txt").read_bytes(),
        )

    def test_scope_and_accessibility_are_explicit(self):
        self.assertIn('lang="en"', self.text)
        self.assertIn('href="#main"', self.text)
        self.assertIn("experimental", self.text.lower())
        self.assertIn("directory publication is still pending", self.text)
        self.assertIn("not ten merged features", self.text)
        for tag, attrs in self.page.nodes:
            if tag == "img":
                self.assertTrue(attrs.get("alt"))
        self.assertTrue((ROOT / ".github/ISSUE_TEMPLATE/compatibility.yml").is_file())


if __name__ == "__main__":
    unittest.main()
