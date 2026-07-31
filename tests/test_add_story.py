from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "add-story.py"
SPEC = importlib.util.spec_from_file_location("add_story", SCRIPT)
assert SPEC and SPEC.loader
add_story = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(add_story)


class AddStoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = ROOT / "content" / "stories.json"
        self.stories = json.loads(self.database.read_text())

    def test_existing_story_database_is_valid(self) -> None:
        self.assertEqual(add_story.validate_stories(self.stories, ROOT), [])

    def test_every_existing_url_is_rejected_before_fetch(self) -> None:
        def unexpected_fetch(_: str) -> str:
            self.fail("duplicate URL made a network request")

        for story in self.stories:
            with (
                self.subTest(url=story["url"]),
                self.assertRaises(add_story.DuplicateStory),
            ):
                add_story.add_story(story["url"], self.database, unexpected_fetch)

    def test_tracking_parameters_do_not_bypass_duplicate_check(self) -> None:
        story = next(item for item in self.stories if "?" not in item["url"])
        tracked_url = f"{story['url']}?utm_source=test&utm_campaign=duplicate#section"

        with self.assertRaises(add_story.DuplicateStory):
            add_story.add_story(tracked_url, self.database, lambda _: "")

    def test_adds_metadata_with_attributes_in_any_order(self) -> None:
        page = """
        <html><head>
          <meta content="A newly reported story" property="og:title">
          <meta content="Science Example" property="og:site_name">
          <meta content="A concise description." name="description">
          <meta content="/images/story.jpg" property="og:image">
          <meta content="2026-07-29T14:00:00Z" property="article:published_time">
        </head></html>
        """
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "stories.json"
            database.write_text("[]\n")
            entry = add_story.add_story(
                "https://example.com/new-story?utm_source=newsletter",
                database,
                lambda _: page,
            )

            self.assertEqual(entry["title"], "A newly reported story")
            self.assertEqual(entry["url"], "https://example.com/new-story")
            self.assertEqual(entry["publication"], "Science Example")
            self.assertEqual(entry["description"], "A concise description.")
            self.assertEqual(entry["image"], "https://example.com/images/story.jpg")
            self.assertEqual(entry["date"], "2026-07-29")
            self.assertEqual(json.loads(database.read_text()), [entry])

    def test_json_ld_is_used_when_social_metadata_is_missing(self) -> None:
        page = """
        <html><head><title>Fallback title</title>
          <script type="application/ld+json">
            {"@type":"NewsArticle","headline":"JSON-LD title",
             "datePublished":"2025-06-25", "description":"From structured data",
             "image":{"url":"https://example.org/photo.jpg"},
             "publisher":{"name":"Example Journal"}}
          </script>
        </head></html>
        """
        entry = add_story.story_from_html("https://example.org/story", page)
        self.assertEqual(entry["title"], "JSON-LD title")
        self.assertEqual(entry["publication"], "Example Journal")
        self.assertEqual(entry["date"], "2025-06-25")

    def test_missing_publication_date_stays_blank(self) -> None:
        page = '<meta property="og:title" content="An undated story">'

        entry = add_story.story_from_html("https://example.org/undated", page)

        self.assertEqual(entry["date"], "")

    def test_visible_article_fields_fill_sparse_metadata(self) -> None:
        page = """
        <meta property="og:title" content="What Frogs Tell Us | Marine Biological Laboratory">
        <meta property="og:site_name" content="Marine Biological Laboratory">
        <h1>What Frogs Tell Us</h1>
        <div><strong>By Nora Bradford</strong> August 05, 2022</div>
        <p>Adverse childhood experiences can be challenging to study in a lab, so
        researchers are working with frogs to understand the effects of early stress.</p>
        """

        entry = add_story.story_from_html("https://www.mbl.edu/news/frogs", page)

        self.assertEqual(entry["title"], "What Frogs Tell Us")
        self.assertEqual(
            entry["description"],
            "Adverse childhood experiences can be challenging to study in a lab, so "
            "researchers are working with frogs to understand the effects of early stress.",
        )
        self.assertEqual(entry["date"], "2022-08-05")

    def test_known_outlets_override_weak_publisher_metadata(self) -> None:
        cases = [
            (
                "https://www.broadinstitute.org/blog/whyiscience",
                '<meta property="og:site_name" content="WhyIScience Q&amp;A">',
                "Broad Institute",
            ),
            (
                "https://www.nationalgeographic.com/science/article/example",
                '<meta property="og:site_name" content="Science">',
                "National Geographic",
            ),
            (
                "https://www.nature.com/articles/example",
                '<meta property="og:site_name" content="Nature Publishing Group UK">',
                "Nature",
            ),
        ]

        for url, page, publication in cases:
            with self.subTest(url=url):
                entry = add_story.story_from_html(url, page)
                self.assertEqual(entry["publication"], publication)

    def test_article_heading_beats_a_generic_page_title(self) -> None:
        page = """
        <meta property="og:title" content="BWH Press Release - Brigham and Women's Hospital">
        <meta property="og:site_name" content="Brigham and Women's Hospital">
        <meta name="description" content="View recent and archived press releases.">
        <h1>Press Releases</h1>
        <span>January 12, 2023</span>
        <h2 class="newsroom-detail__title">Researchers Identify a New Brain Pathway</h2>
        <p>A new study examined neurological and psychiatric datasets and identified a
        common network of brain areas underlying several psychiatric illnesses.</p>
        """

        entry = add_story.story_from_html(
            "https://www.brighamandwomens.org/about-bwh/newsroom/press-releases-detail?id=1",
            page,
        )

        self.assertEqual(entry["title"], "Researchers Identify a New Brain Pathway")
        self.assertEqual(entry["publication"], "Brigham and Women's Hospital")
        self.assertEqual(
            entry["description"],
            "A new study examined neurological and psychiatric datasets and identified a "
            "common network of brain areas underlying several psychiatric illnesses.",
        )
        self.assertEqual(entry["date"], "2023-01-12")

    def test_known_outlet_name_removes_title_suffix(self) -> None:
        page = '<meta property="og:title" content="Do Plants Think? - Elucidations Podcast">'

        entry = add_story.story_from_html("https://elucidations.vercel.app/posts/episode", page)

        self.assertEqual(entry["title"], "Do Plants Think?")
        self.assertEqual(entry["publication"], "Elucidations Podcast")

    def test_reader_fallback_metadata_is_parsed(self) -> None:
        page = """Title: Broad Institute News
URL Source: https://www.broadinstitute.org/news/example
Published Time: 2022-05-02T14:34:44-04:00

Markdown Content:
# Repeated urinary tract infections may stem from a disrupted microbiome

By Nora Bradford

![Bacteria in the bladder](http://www.broadinstitute.org/files/article.jpg)

Urinary tract infections affect millions of people every year, and a new study points to the microbiome as a possible cause.
"""

        entry = add_story.story_from_page("https://www.broadinstitute.org/news/example", page)

        self.assertEqual(
            entry["title"],
            "Repeated urinary tract infections may stem from a disrupted microbiome",
        )
        self.assertEqual(entry["publication"], "Broad Institute")
        self.assertEqual(
            entry["description"],
            "Urinary tract infections affect millions of people every year, and a new "
            "study points to the microbiome as a possible cause.",
        )
        self.assertEqual(entry["image"], "http://www.broadinstitute.org/files/article.jpg")
        self.assertEqual(entry["date"], "2022-05-02")

    def test_fetch_retries_blocked_pages_through_reader(self) -> None:
        page = b"Title: Broad Institute News\nMarkdown Content:\n# Story"
        calls: list[str] = []

        class Headers:
            @staticmethod
            def get_content_charset() -> str:
                return "utf-8"

        class Response:
            headers = Headers()

            def __enter__(self) -> Response:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            @staticmethod
            def read() -> bytes:
                return page

        def opener(request: object, timeout: int) -> Response:
            del timeout
            url = request.full_url
            calls.append(url)
            if len(calls) == 1:
                error = HTTPError(url, 403, "Forbidden", {}, None)
                error.close()
                raise error
            return Response()

        result = add_story.fetch_page("https://www.broadinstitute.org/news/example", opener=opener)

        self.assertEqual(result, page.decode())
        self.assertEqual(
            calls,
            [
                "https://www.broadinstitute.org/news/example",
                "https://r.jina.ai/http://www.broadinstitute.org/news/example",
            ],
        )


if __name__ == "__main__":
    unittest.main()
