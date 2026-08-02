#!/usr/bin/env python3
"""Add a linked story to content/stories.json."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable, Iterator
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
STORIES = ROOT / "content" / "stories.json"
TRACKING_PARAMETERS = {"fbclid", "gclid", "mc_cid", "mc_eid"}
READER_PREFIX = "https://r.jina.ai/"
KNOWN_PUBLICATIONS = {
    "brighamandwomens.org": "Brigham and Women's Hospital",
    "broadinstitute.org": "Broad Institute",
    "casw.org": "CASW Student Newsroom",
    "elucidations.vercel.app": "Elucidations Podcast",
    "lohdownonscience.com": "The Loh Down on Science",
    "nasw.org": "National Association of Science Writers",
    "nationalgeographic.com": "National Geographic",
    "nature.com": "Nature",
    "socsci.uci.edu": "UCI Social Sciences",
    "spectrumnews.org": "The Transmitter",
    "thetransmitter.org": "The Transmitter",
}


class StoryError(Exception):
    """A story could not be added."""


class DuplicateStory(StoryError):
    """The story URL is already present."""


class MetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title: list[str] = []
        self.heading: list[str] = []
        self.json_ld: list[str] = []
        self.article_text: list[str] = []
        self.paragraphs: list[str] = []
        self._capture: list[str] | None = None
        self._paragraph: list[str] | None = None
        self._after_heading = False
        self._specific_heading = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value or "" for key, value in attrs}
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name") or attributes.get("itemprop")
            content = attributes.get("content")
            if key and content:
                self.meta.setdefault(key.lower(), content.strip())
        elif tag == "title":
            self._capture = self.title
        elif tag == "script" and "ld+json" in attributes.get("type", "").lower():
            self.json_ld.append("")
            self._capture = self.json_ld
        elif tag == "h1" or (
            tag == "h2"
            and any(
                marker in attributes.get("class", "").lower()
                for marker in (
                    "article-title",
                    "detail__title",
                    "entry-title",
                    "headline",
                )
            )
        ):
            if tag == "h1" or not self._specific_heading:
                self.heading.clear()
                self._capture = self.heading
                self._specific_heading = tag == "h2"
        if tag == "h1":
            self._after_heading = True
        elif tag == "p" and self._after_heading:
            self._paragraph = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"h1", "h2", "title", "script"}:
            self._capture = None
        if tag == "p" and self._paragraph is not None:
            self.paragraphs.append(clean_text("".join(self._paragraph)))
            self._paragraph = None

    def handle_data(self, data: str) -> None:
        if self._capture is self.title:
            self.title.append(data)
        elif self._capture is self.heading:
            self.heading.append(data)
        elif self._capture is self.json_ld:
            self.json_ld[-1] += data
        if self._after_heading:
            self.article_text.append(data)
        if self._paragraph is not None:
            self._paragraph.append(data)


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_title(title: object, publication: object) -> str:
    title = clean_text(title)
    publication = clean_text(publication)
    for separator in (" | ", " — ", " - "):
        suffix = separator + publication
        if publication and title.casefold().endswith(suffix.casefold()):
            return title[: -len(suffix)].rstrip()
    return title


def publication_name(url: str, candidate: object = "") -> str:
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    return KNOWN_PUBLICATIONS.get(host, clean_text(candidate) or host)


def extract_date(value: object) -> str:
    text = clean_text(value)
    iso = re.search(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", text)
    if iso:
        return iso.group(0)
    written = re.search(
        r"\b(?:January|February|March|April|May|June|July|August|September|October|"
        r"November|December) \d{1,2}, \d{4}\b",
        text,
    )
    if not written:
        return ""
    try:
        return datetime.strptime(written.group(0), "%B %d, %Y").date().isoformat()
    except ValueError:
        return ""


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise StoryError("Story URL must begin with http:// or https://")
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
        ]
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def walk_json(value: object) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def structured_metadata(scripts: list[str]) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    for script in scripts:
        try:
            objects.extend(walk_json(json.loads(script)))
        except (json.JSONDecodeError, TypeError):
            continue
    article_types = {"article", "newsarticle", "reportagenewsarticle", "blogposting"}
    for item in objects:
        item_types = item.get("@type", [])
        if isinstance(item_types, str):
            item_types = [item_types]
        if any(str(item_type).lower() in article_types for item_type in item_types):
            return item
    return next((item for item in objects if item.get("headline")), {})


def nested_text(value: object, *keys: str) -> str:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        return next((text for item in value if (text := nested_text(item, *keys))), "")
    if isinstance(value, dict):
        return next((text for key in keys if (text := nested_text(value.get(key), *keys))), "")
    return ""


def story_from_html(url: str, page: str) -> dict[str, str]:
    parser = MetadataParser()
    parser.feed(page)
    structured = structured_metadata(parser.json_ld)
    meta = parser.meta

    title = (
        clean_text("".join(parser.heading))
        or nested_text(structured.get("headline"), "name")
        or meta.get("og:title")
        or meta.get("twitter:title")
        or clean_text("".join(parser.title))
        or url
    )
    publication = publication_name(
        url,
        meta.get("og:site_name") or nested_text(structured.get("publisher"), "name"),
    )
    paragraph = next((text for text in parser.paragraphs if len(text) >= 80), "")
    description = (
        meta.get("description")
        or meta.get("og:description")
        or nested_text(structured.get("description"), "text")
        or paragraph
    )
    if paragraph and clean_text(description).lower().startswith("view recent and archived"):
        description = paragraph
    image = (
        meta.get("og:image")
        or meta.get("twitter:image")
        or nested_text(structured.get("image"), "url", "contentUrl", "@id")
    )
    published = (
        meta.get("article:published_time")
        or meta.get("date")
        or meta.get("datepublished")
        or nested_text(structured.get("datePublished"), "value")
        or " ".join(parser.article_text)
    )

    return {
        "title": clean_title(title, publication),
        "url": canonical_url(url),
        "publication": clean_text(publication),
        "description": clean_text(description),
        "image": urljoin(url, clean_text(image)) if image else "",
        "date": extract_date(published),
    }


def markdown_text(value: str) -> str:
    value = re.sub(r"!\[[^]]*]\([^)]*\)", "", value)
    value = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", value)
    return clean_text(re.sub(r"[*_`>#]", "", value))


def story_from_reader(url: str, page: str) -> dict[str, str]:
    header, _, markdown = page.partition("Markdown Content:")
    fields = {
        key: value
        for line in header.splitlines()
        if ": " in line
        for key, value in [line.split(": ", 1)]
    }
    heading = re.search(r"(?m)^#\s+(.+?)\s*$", markdown)
    article = markdown[heading.end() :] if heading else markdown
    title = markdown_text(heading.group(1)) if heading else clean_text(fields.get("Title"))
    header_title = clean_text(fields.get("Title"))
    site_name = header_title.rsplit(" | ", 1)[-1] if " | " in header_title else header_title
    site_name = re.sub(r"\s+(?:home(?:page)?|news)$", "", site_name, flags=re.IGNORECASE)
    publication = publication_name(url, site_name if site_name != title else "")
    image_match = re.search(r"!\[[^]]*]\((https?://[^)\s]+)", article)
    description = next(
        (
            text
            for block in re.split(r"\n\s*\n", article)
            if len(text := markdown_text(block)) >= 80 and not text.lower().startswith("by ")
        ),
        "",
    )
    return {
        "title": clean_title(title or url, publication),
        "url": canonical_url(url),
        "publication": publication,
        "description": description,
        "image": image_match.group(1) if image_match else "",
        "date": extract_date(fields.get("Published Time", "") + " " + article[:1000]),
    }


def story_from_page(url: str, page: str) -> dict[str, str]:
    if re.search(r"(?m)^Markdown Content:\s*$", page):
        return story_from_reader(url, page)
    return story_from_html(url, page)


def request_for(url: str, accept: str = "text/html,application/xhtml+xml") -> Request:
    return Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/126 Safari/537.36",
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        },
    )


def download(request: Request, opener: Callable[..., Any]) -> str:
    with opener(request, timeout=20) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, "replace")


def reader_url(url: str) -> str:
    parts = urlsplit(url)
    source = urlunsplit(("http", parts.netloc, parts.path, parts.query, ""))
    return READER_PREFIX + source


def fetch_page(url: str, opener: Callable[..., Any] = urlopen) -> str:
    try:
        return download(request_for(url), opener)
    except HTTPError as error:
        if error.code not in {401, 403, 429}:
            raise StoryError(f"The page returned HTTP {error.code}: {url}") from error
        fallback = reader_url(url)
        try:
            return download(request_for(fallback, "text/plain"), opener)
        except (HTTPError, URLError) as fallback_error:
            raise StoryError(f"The publisher blocked this page: {url}") from fallback_error
    except URLError as error:
        raise StoryError(f"Could not open {url}: {error.reason}") from error


def load_stories(path: Path) -> list[dict[str, Any]]:
    try:
        stories = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise StoryError(f"Could not read story database: {path}") from error
    if not isinstance(stories, list):
        raise StoryError(f"Story database must contain a JSON list: {path}")
    return stories


def validate_stories(stories: list[dict[str, Any]], root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    seen_urls: set[str] = set()
    required = {"title", "url", "publication", "description", "image", "date"}
    for index, story in enumerate(stories, 1):
        label = clean_text(story.get("title")) or f"entry {index}"
        missing = required - story.keys()
        if missing:
            errors.append(f"{label}: missing {', '.join(sorted(missing))}")
        try:
            url = canonical_url(clean_text(story.get("url")))
            if url in seen_urls:
                errors.append(f"{label}: duplicate URL")
            seen_urls.add(url)
        except StoryError as error:
            errors.append(f"{label}: {error}")
        published = clean_text(story.get("date"))
        if published and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published):
            errors.append(f"{label}: invalid date {published!r}")
        image = clean_text(story.get("image"))
        if image and not image.startswith(("http://", "https://")) and not (root / image).is_file():
            errors.append(f"{label}: image not found: {image}")
        links = story.get("links", [])
        if not isinstance(links, list) or any(
            not isinstance(link, dict) or not link.get("label") or not link.get("url")
            for link in links
        ):
            errors.append(f"{label}: links must contain labels and URLs")
    return errors


def add_story(
    url: str,
    database: Path = STORIES,
    fetcher: Callable[[str], str] = fetch_page,
) -> dict[str, str]:
    stories = load_stories(database)
    normalized_url = canonical_url(url)
    existing_urls = {canonical_url(clean_text(story.get("url"))) for story in stories}
    if normalized_url in existing_urls:
        raise DuplicateStory("That story is already listed.")

    entry = story_from_page(normalized_url, fetcher(normalized_url))
    stories.append(entry)
    database.write_text(json.dumps(stories, indent=2, ensure_ascii=False) + "\n")
    return entry


def parse_args(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", help="published story URL")
    parser.add_argument("--check", action="store_true", help="validate the existing story database")
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch metadata without changing files"
    )
    parser.add_argument("--database", type=Path, default=STORIES, help=argparse.SUPPRESS)
    args = parser.parse_args(arguments)
    if args.check == bool(args.url):
        parser.error("provide a URL, or use --check")
    return args


def main(arguments: list[str] | None = None) -> int:
    args = parse_args(arguments)
    try:
        if args.check:
            stories = load_stories(args.database)
            errors = validate_stories(stories)
            if errors:
                raise StoryError("\n".join(errors))
            print(f"{len(stories)} stories OK")
            return 0
        if args.dry_run:
            url = canonical_url(args.url)
            print(json.dumps(story_from_page(url, fetch_page(url)), indent=2))
            return 0
        entry = add_story(args.url, args.database)
        print(f"Added: {entry['title']}")
        return 0
    except StoryError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    raise SystemExit(main())
