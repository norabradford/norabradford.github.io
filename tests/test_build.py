from __future__ import annotations

import importlib.util
import json
import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock
from urllib.parse import urlsplit

from PIL import Image

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
        self.images: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        attribute = "href" if tag in {"a", "link"} else "src"
        if tag in {"a", "iframe", "img", "link"} and attributes.get(attribute):
            self.urls.append(attributes[attribute])
        if tag == "img":
            self.images.append(attributes)
            self.urls.extend(
                candidate.split()[0]
                for candidate in attributes.get("srcset", "").split(",")
                if candidate.strip()
            )


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        build.main()
        cls.dist = ROOT / "dist"

    def test_navigation_uses_dedicated_pages(self) -> None:
        routes = ["writing.html", "research.html", "about.html", "fun.html", "cv.html"]
        for filename in ["index.html", *routes]:
            page = (self.dist / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertNotIn("index.html#", page)
                for route in routes:
                    self.assertIn(f'href="{route}"', page)

    def test_generated_pages_are_utf8_on_non_utf8_systems(self) -> None:
        try:
            with mock.patch(
                "pathlib.io.text_encoding",
                side_effect=lambda encoding: encoding or "cp1252",
            ):
                build.main()

            for page_path in self.dist.glob("*.html"):
                with self.subTest(page=page_path.name):
                    page_path.read_bytes().decode("utf-8")
        finally:
            build.main()

    def test_home_is_only_the_compact_introduction(self) -> None:
        page = (self.dist / "index.html").read_text(encoding="utf-8")

        self.assertIn("Nora Bradford, Ph.D.", page)
        self.assertIn("@norabradford", page)
        self.assertNotIn('class="hero"', page)
        self.assertNotIn('class="story"', page)

    def test_portrait_appears_on_home_and_about(self) -> None:
        for filename in ("index.html", "about.html"):
            page = (self.dist / filename).read_text(encoding="utf-8")
            with self.subTest(filename=filename):
                self.assertIn('src="img/about.jpg"', page)
                self.assertIn('alt="Nora Bradford"', page)

    def test_portrait_height_tracks_its_responsive_width(self) -> None:
        stylesheet = (self.dist / "style.css").read_text(encoding="utf-8")
        portrait_rule = re.search(r"\.portrait\s*{([^}]*)}", stylesheet, re.S)

        self.assertIsNotNone(portrait_rule)
        self.assertIn("height: auto", portrait_rule.group(1))

    def test_every_story_is_on_the_writing_page(self) -> None:
        stories = json.loads((ROOT / "content" / "stories.json").read_text(encoding="utf-8"))
        page = (self.dist / "writing.html").read_text(encoding="utf-8")

        self.assertEqual(page.count('<article class="story">'), len(stories))

    def test_story_images_are_responsive_and_prioritized(self) -> None:
        parser = AssetParser()
        parser.feed((self.dist / "writing.html").read_text(encoding="utf-8"))
        images = [image for image in parser.images if "story-image" in image.get("class", "")]
        stories = json.loads((ROOT / "content" / "stories.json").read_text(encoding="utf-8"))
        stories.sort(key=lambda story: story.get("date", ""), reverse=True)
        stories_with_images = [story for story in stories if story.get("image")]

        self.assertEqual(len(images), len(stories_with_images))
        for index, (image, story) in enumerate(zip(images, stories_with_images, strict=True)):
            with self.subTest(src=image.get("src")):
                self.assertEqual(image.get("width"), "640")
                self.assertEqual(image.get("height"), "400")
                self.assertEqual(image.get("decoding"), "async")
                self.assertEqual(image.get("loading"), "eager" if index < 4 else "lazy")
                self.assertEqual(image.get("fetchpriority"), "high" if index == 0 else None)
                if story["image"].startswith(("http://", "https://")):
                    self.assertEqual(image.get("src"), story["image"])
                    self.assertNotIn("srcset", image)
                else:
                    self.assertIn(" 320w", image.get("srcset", ""))
                    self.assertIn(" 640w", image.get("srcset", ""))
                    self.assertIn("sizes", image)

    def test_story_images_keep_their_landscape_aspect_ratio(self) -> None:
        stylesheet = (self.dist / "style.css").read_text(encoding="utf-8")
        image_rule = re.search(r"\.story-image\s*{([^}]*)}", stylesheet, re.S)

        self.assertIsNotNone(image_rule)
        self.assertIn("width: 100%", image_rule.group(1))
        self.assertIn("height: auto", image_rule.group(1))
        self.assertIn("aspect-ratio: 16/10", image_rule.group(1))

    def test_deployed_portfolio_has_an_image_budget(self) -> None:
        assets = list((self.dist / "img" / "portfolio").iterdir())

        self.assertTrue(assets)
        self.assertTrue(all(asset.suffix == ".webp" for asset in assets))
        self.assertLess(sum(asset.stat().st_size for asset in assets), 12 * 1024 * 1024)
        self.assertLess(
            sum(asset.stat().st_size for asset in assets if asset.name.endswith("-640.webp")),
            8 * 1024 * 1024,
        )
        for asset in assets:
            width = 640 if asset.name.endswith("-640.webp") else 320
            with self.subTest(asset=asset.name), Image.open(asset) as image:
                self.assertEqual(image.format, "WEBP")
                self.assertEqual(image.size, (width, width * 10 // 16))

    def test_remote_story_images_keep_a_working_fallback(self) -> None:
        story = {
            "title": "Remote image",
            "url": "https://example.com/story",
            "publication": "Example",
            "description": "",
            "image": "https://example.com/image.jpg",
            "date": "",
        }

        card = build.story_card(story, 0)

        self.assertIn('src="https://example.com/image.jpg"', card)
        self.assertNotIn("srcset", card)
        self.assertIn('fetchpriority="high"', card)

    def test_animated_thumbnails_keep_their_animation(self) -> None:
        stories = json.loads((ROOT / "content" / "stories.json").read_text(encoding="utf-8"))
        sources = {
            ROOT / story["image"]
            for story in stories
            if str(story.get("image", "")).lower().endswith(".gif")
            and not str(story["image"]).startswith(("http://", "https://"))
        }

        for source in sources:
            expected = self.animation_signature(source)
            for width in (320, 640):
                name = source.name.replace(".", "-") + f"-{width}.webp"
                thumbnail = self.dist / "img" / "portfolio" / name
                with self.subTest(source=source.name, width=width):
                    self.assertEqual(self.animation_signature(thumbnail), expected)

    @staticmethod
    def animation_signature(path: Path) -> tuple[int, int, list[int]]:
        with Image.open(path) as image:
            frames = int(getattr(image, "n_frames", 1))
            loop = int(image.info.get("loop", 0))
            durations = []
            for index in range(frames):
                image.seek(index)
                image.load()
                durations.append(int(image.info.get("duration", 0)))
        return frames, loop, durations

    def test_local_links_and_assets_exist(self) -> None:
        for page_path in self.dist.glob("*.html"):
            parser = AssetParser()
            parser.feed(page_path.read_text(encoding="utf-8"))
            for url in parser.urls:
                parts = urlsplit(url)
                if parts.scheme or parts.netloc or not parts.path:
                    continue
                with self.subTest(page=page_path.name, url=url):
                    self.assertTrue((page_path.parent / parts.path).is_file())

    def test_new_cv_entries_are_rendered(self) -> None:
        page = (self.dist / "cv.html").read_text(encoding="utf-8")

        for text in (
            "NASW David Perlman Mentoring Program",
            "Outrider Science Media Forum",
            "The problem with ‘happiness’",
            "How Your Brain Creates ‘Aha’ Moments and Why They Stick",
        ):
            with self.subTest(text=text):
                self.assertIn(text, page)

    def test_nora_bradford_is_bolded_in_cv_author_lists(self) -> None:
        source = (ROOT / "content" / "cv.md").read_text(encoding="utf-8")
        page = (self.dist / "cv.html").read_text(encoding="utf-8")

        self.assertEqual(page.count("<strong>N. Bradford</strong>"), source.count("N. Bradford"))

    def test_cv_title_precedes_the_print_control(self) -> None:
        page = (self.dist / "cv.html").read_text(encoding="utf-8")

        self.assertLess(page.index("<h1>Nora Bradford</h1>"), page.index("<button"))


if __name__ == "__main__":
    unittest.main()
