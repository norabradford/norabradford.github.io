from __future__ import annotations

import importlib.util
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build.py"
SPEC = importlib.util.spec_from_file_location("build", SCRIPT)
assert SPEC and SPEC.loader
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class AssetParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        attribute = "href" if tag in {"a", "link"} else "src"
        if tag in {"a", "iframe", "img", "link"} and attributes.get(attribute):
            self.urls.append(attributes[attribute] or "")


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        build.main()
        cls.dist = ROOT / "dist"

    def test_navigation_uses_dedicated_pages(self) -> None:
        routes = ["writing.html", "research.html", "about.html", "fun.html", "cv.html"]
        for filename in ["index.html", *routes]:
            page = (self.dist / filename).read_text()
            with self.subTest(filename=filename):
                self.assertNotIn("index.html#", page)
                for route in routes:
                    self.assertIn(f'href="{route}"', page)

    def test_home_is_only_the_compact_introduction(self) -> None:
        page = (self.dist / "index.html").read_text()

        self.assertIn("Nora Bradford, Ph.D.", page)
        self.assertIn("@norabradford", page)
        self.assertNotIn('class="hero"', page)
        self.assertNotIn('class="story"', page)

    def test_portrait_appears_on_home_and_about(self) -> None:
        for filename in ("index.html", "about.html"):
            page = (self.dist / filename).read_text()
            with self.subTest(filename=filename):
                self.assertIn('src="img/about.jpg"', page)
                self.assertIn('alt="Nora Bradford"', page)

    def test_portrait_height_tracks_its_responsive_width(self) -> None:
        stylesheet = (self.dist / "style.css").read_text()
        portrait_rule = re.search(r"\.portrait\s*{([^}]*)}", stylesheet, re.S)

        self.assertIsNotNone(portrait_rule)
        self.assertIn("height: auto", portrait_rule.group(1))

    def test_every_story_is_on_the_writing_page(self) -> None:
        stories = json.loads((ROOT / "content" / "stories.json").read_text())
        page = (self.dist / "writing.html").read_text()

        self.assertEqual(page.count('<article class="story">'), len(stories))

    def test_local_links_and_assets_exist(self) -> None:
        for page_path in self.dist.glob("*.html"):
            parser = AssetParser()
            parser.feed(page_path.read_text())
            for url in parser.urls:
                parts = urlsplit(url)
                if parts.scheme or parts.netloc or not parts.path:
                    continue
                with self.subTest(page=page_path.name, url=url):
                    self.assertTrue((page_path.parent / parts.path).is_file())

    def test_new_cv_entries_are_rendered(self) -> None:
        page = (self.dist / "cv.html").read_text()

        for text in (
            "NASW David Perlman Mentoring Program",
            "Outrider Science Media Forum",
            "The problem with ‘happiness’",
            "How Your Brain Creates ‘Aha’ Moments and Why They Stick",
        ):
            with self.subTest(text=text):
                self.assertIn(text, page)

    def test_cv_title_precedes_the_print_control(self) -> None:
        page = (self.dist / "cv.html").read_text()

        self.assertLess(page.index("<h1>Nora Bradford</h1>"), page.index("<button"))


if __name__ == "__main__":
    unittest.main()
