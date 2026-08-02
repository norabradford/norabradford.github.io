#!/usr/bin/env python3
"""Build the static site and its responsive portfolio images."""

from __future__ import annotations

import hashlib
import html
import json
import re
import shutil
import tempfile
from datetime import date
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT, STATIC, DIST = ROOT / "content", ROOT / "static", ROOT / "dist"
PORTFOLIO = ROOT / "img" / "portfolio"
OPTIMIZED = ROOT / "img" / "optimized"
IMAGE_MANIFEST = OPTIMIZED / "manifest.json"
THUMBNAIL_WIDTHS = (320, 640)
IMAGE_PIPELINE_VERSION = 1
STILL_QUALITY = 76
ANIMATED_QUALITY = 70
ANIMATED_METHOD = 6


def inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(
        r"\[([^]]+)]\((https?://[^ )]+|mailto:[^ )]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)


def markdown(source: str) -> str:
    output, paragraph, list_tag = [], [], None

    def flush() -> None:
        nonlocal paragraph
        if paragraph:
            output.append(f"<p>{inline(' '.join(paragraph))}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            output.append(f"</{list_tag}>")
            list_tag = None

    for line in source.splitlines():
        line = line.strip()
        if not line:
            flush()
            close_list()
        elif match := re.match(r"^(#{1,3})\s+(.+)$", line):
            flush()
            close_list()
            level = len(match.group(1))
            output.append(f"<h{level}>{inline(match.group(2))}</h{level}>")
        elif match := re.match(r"^(?:- |\d+\.\s+)(.+)$", line):
            flush()
            tag = "ul" if line.startswith("- ") else "ol"
            if list_tag != tag:
                close_list()
                output.append(f"<{tag}>")
                list_tag = tag
            output.append(f"<li>{inline(match.group(1))}</li>")
        elif line.startswith("<iframe ") and line.endswith("</iframe>"):
            flush()
            close_list()
            output.append(line)
        else:
            paragraph.append(line)
    flush()
    close_list()
    return "\n".join(output)


def layout(title: str, body: str, current: str | None = None) -> str:
    links = [
        ("Writing", "writing.html"),
        ("Research", "research.html"),
        ("About", "about.html"),
        ("Fun", "fun.html"),
        ("CV", "cv.html"),
    ]
    nav_links = []
    for name, url in links:
        active = ' aria-current="page"' if name == current else ""
        nav_links.append(f'<a href="{url}"{active}>{name}</a>')
    nav = "".join(nav_links)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="Nora Bradford is a science writer and lecturer at UPenn.">
  <title>{html.escape(title)} · Nora Bradford</title>
  <link rel="icon" href="img/favicon.png">
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="shell">
    <header><a class="brand" href="index.html">Nora Bradford</a><nav>{nav}</nav></header>
    {body}
    <footer>© {date.today().year} Nora Bradford · <a href="mailto:bnora@upenn.edu">bnora@upenn.edu</a> · <a href="https://bsky.app/profile/norabradford.bsky.social">Bluesky</a> · <a href="https://www.linkedin.com/in/nora-bradford-73809217a/">LinkedIn</a></footer>
  </div>
</body>
</html>"""


def local_portfolio_image(value: str) -> Path | None:
    if value.startswith(("http://", "https://")):
        return None
    source = (ROOT / value).resolve()
    try:
        source.relative_to(PORTFOLIO.resolve())
    except ValueError:
        return None
    return source if source.is_file() else None


def thumbnail_name(source: Path, width: int) -> str:
    relative = source.relative_to(PORTFOLIO)
    key = "-".join(relative.parts).replace(".", "-")
    return f"{key}-{width}.webp"


def thumbnail_url(source: Path, width: int) -> str:
    return f"img/portfolio/{thumbnail_name(source, width)}"


def source_digest(source: Path) -> str:
    with source.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def load_image_manifest() -> dict[str, object]:
    try:
        manifest = json.loads(IMAGE_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return manifest if isinstance(manifest, dict) else {}


def image_recipe() -> dict[str, object]:
    try:
        pillow_version = package_version("Pillow")
    except PackageNotFoundError as error:
        raise RuntimeError("Run 'uv sync' to install build dependencies") from error
    return {
        "animated_method": ANIMATED_METHOD,
        "animated_quality": ANIMATED_QUALITY,
        "pillow": pillow_version,
        "still_quality": STILL_QUALITY,
        "widths": list(THUMBNAIL_WIDTHS),
    }


def write_image_manifest(sources: dict[str, str], recipe: dict[str, object]) -> None:
    manifest = {"version": IMAGE_PIPELINE_VERSION, "recipe": recipe, "sources": sources}
    serialized = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if IMAGE_MANIFEST.is_file() and IMAGE_MANIFEST.read_text(encoding="utf-8") == serialized:
        return
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=OPTIMIZED, prefix=".manifest.", delete=False
    ) as file:
        file.write(serialized)
        temporary = Path(file.name)
    try:
        temporary.replace(IMAGE_MANIFEST)
    finally:
        temporary.unlink(missing_ok=True)


def save_thumbnail(source: Path, output: Path, width: int) -> None:
    try:
        from PIL import Image, ImageOps, ImageSequence
    except ModuleNotFoundError as error:
        raise RuntimeError("Run 'uv sync' to install build dependencies") from error

    size = (width, width * 10 // 16)
    with tempfile.NamedTemporaryFile(
        dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False
    ) as file:
        temporary = Path(file.name)
    try:
        with Image.open(source) as image:
            if getattr(image, "is_animated", False):
                durations: list[int] = []
                frames = []
                default_duration = int(image.info.get("duration", 100))
                for frame in ImageSequence.Iterator(image):
                    durations.append(int(frame.info.get("duration", default_duration)))
                    frames.append(
                        ImageOps.fit(frame.convert("RGBA"), size, Image.Resampling.LANCZOS)
                    )
                frames[0].save(
                    temporary,
                    "WEBP",
                    save_all=True,
                    append_images=frames[1:],
                    duration=durations,
                    loop=int(image.info.get("loop", 0)),
                    quality=ANIMATED_QUALITY,
                    method=ANIMATED_METHOD,
                    minimize_size=True,
                )
            else:
                image = ImageOps.exif_transpose(image)
                mode = "RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB"
                thumbnail = ImageOps.fit(image.convert(mode), size, Image.Resampling.LANCZOS)
                thumbnail.save(temporary, "WEBP", quality=STILL_QUALITY, method=6)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_portfolio_thumbnails(stories: list[dict[str, str]]) -> None:
    sources = {
        source
        for story in stories
        if (source := local_portfolio_image(story.get("image", ""))) is not None
    }
    recipe = image_recipe()
    previous = load_image_manifest()
    previous_sources = (
        previous.get("sources", {})
        if previous.get("version") == IMAGE_PIPELINE_VERSION and previous.get("recipe") == recipe
        else {}
    )
    if not isinstance(previous_sources, dict):
        previous_sources = {}

    OPTIMIZED.mkdir(parents=True, exist_ok=True)
    current_sources: dict[str, str] = {}
    checkpoint_sources = {
        key: value
        for key, value in previous_sources.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    expected: set[Path] = set()
    for source in sorted(sources):
        key = source.relative_to(ROOT).as_posix()
        digest = source_digest(source)
        current_sources[key] = digest
        outputs = [OPTIMIZED / thumbnail_name(source, width) for width in THUMBNAIL_WIDTHS]
        expected.update(outputs)
        if previous_sources.get(key) == digest and all(output.is_file() for output in outputs):
            continue
        for width, output in zip(THUMBNAIL_WIDTHS, outputs, strict=True):
            save_thumbnail(source, output, width)
        checkpoint_sources[key] = digest
        write_image_manifest(checkpoint_sources, recipe)

    for output in OPTIMIZED.glob("*.webp"):
        if output not in expected:
            output.unlink()

    write_image_manifest(current_sources, recipe)


def story_card(story: dict[str, str], index: int) -> str:
    url = html.escape(story["url"], quote=True)
    image = story.get("image", "")
    picture = ""
    if image:
        source = local_portfolio_image(image)
        source_url = thumbnail_url(source, 320) if source else image
        source_set = (
            f' srcset="{thumbnail_url(source, 320)} 320w, {thumbnail_url(source, 640)} 640w"'
            ' sizes="(max-width: 551px) calc(100vw - 38px), '
            '(max-width: 847px) 50vw, (max-width: 1119px) 33vw, 272px"'
            if source
            else ""
        )
        priority = ' fetchpriority="high"' if index == 0 else ""
        loading = "eager" if index < 4 else "lazy"
        picture = (
            f'<a href="{url}" tabindex="-1"><img class="story-image" '
            f'src="{html.escape(source_url, quote=True)}"{source_set} alt="" '
            f'width="640" height="400" loading="{loading}" decoding="async"{priority}></a>'
        )
    published = story.get("date", "")
    timestamp = f"<time>{html.escape(published)}</time>" if published else ""
    description = story.get("description", "")
    summary = f"<p>{inline(description)}</p>" if description else ""
    extra_links = "".join(
        f'<a href="{html.escape(link["url"], quote=True)}">{inline(link["label"])}</a>'
        for link in story.get("links", [])
    )
    extras = f'<div class="story-links">{extra_links}</div>' if extra_links else ""
    return f"""<article class="story">
      {picture}<span class="publication">{inline(story.get("publication", "Story"))}</span>
      <h3><a href="{url}">{inline(story["title"])}</a></h3>{summary}{extras}{timestamp}
    </article>"""


def portrait(class_name: str) -> str:
    return (
        f'<img class="portrait {class_name}" src="img/about.jpg" alt="Nora Bradford" '
        'width="800" height="800">'
    )


def main() -> None:
    stories = json.loads((CONTENT / "stories.json").read_text(encoding="utf-8"))
    stories.sort(key=lambda item: item.get("date", ""), reverse=True)
    ensure_portfolio_thumbnails(stories)
    image_index = 0
    cards_list = []
    for story in stories:
        cards_list.append(story_card(story, image_index))
        if story.get("image"):
            image_index += 1
    cards = "".join(cards_list)
    research = markdown((CONTENT / "research.md").read_text(encoding="utf-8"))
    about = markdown((CONTENT / "about.md").read_text(encoding="utf-8"))
    about = about.replace("</h1>", f"</h1>\n{portrait('about-portrait')}", 1)
    fun = markdown((CONTENT / "fun.md").read_text(encoding="utf-8"))
    home = f"""<main class="section home-intro">
      <div class="home-copy">
        <p class="home-name"><a href="https://norabradford.github.io">Nora Bradford, Ph.D.</a></p>
        <p class="intro">Science writer and lecturer at UPenn.</p>
        <p class="intro">Follow me on Bluesky: <a href="https://bsky.app/profile/norabradford.bsky.social">@norabradford</a></p>
      </div>
      {portrait("home-portrait")}
    </main>"""
    writing = f"""<main class="section">
      <div class="section-title"><h1>Writing</h1><p>Over {len(stories)} stories, features, scripts, and appearances</p></div>
      <div class="stories">{cards}</div>
    </main>"""
    pages = {
        "index.html": ("Home", home, None),
        "writing.html": ("Writing", writing, "Writing"),
        "research.html": (
            "Research",
            f'<main class="section prose research">{research}</main>',
            "Research",
        ),
        "about.html": (
            "About",
            f'<main class="section prose about">{about}</main>',
            "About",
        ),
        "fun.html": ("Fun", f'<main class="section prose fun">{fun}</main>', "Fun"),
    }

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    shutil.copytree(STATIC, DIST, dirs_exist_ok=True)
    images = DIST / "img"
    portfolio = images / "portfolio"
    portfolio.mkdir(parents=True)
    for source in (ROOT / "img").iterdir():
        if source.name in {"optimized", "portfolio"}:
            continue
        target = images / source.name
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    for source in OPTIMIZED.glob("*.webp"):
        shutil.copy2(source, portfolio / source.name)
    shutil.copy2(ROOT / "CNAME", DIST / "CNAME")
    for filename, (title, body, current) in pages.items():
        (DIST / filename).write_text(layout(title, body, current), encoding="utf-8")

    cv_content = markdown((CONTENT / "cv.md").read_text(encoding="utf-8"))
    cv_content = re.sub(
        r"(<h3>[^\n]*</h3>\n<(?P<list>ul|ol)>.*?</(?P=list)>)",
        r'<div class="cv-entry">\1</div>',
        cv_content,
        flags=re.S,
    )
    cv_content = re.sub(
        r"(<h2>[^\n]*</h2>\n<ul>.*?</ul>)",
        r'<div class="cv-list-section">\1</div>',
        cv_content,
        flags=re.S,
    )
    cv_content = re.sub(
        r"^(<h1>[^\n]*</h1>\n<p>[^\n]*</p>)",
        r'<div class="cv-heading"><div>\1</div><button class="print" '
        r'onclick="window.print()">Print / save as PDF</button></div>',
        cv_content,
    )
    cv = f'<main class="section prose cv">{cv_content}</main>'
    (DIST / "cv.html").write_text(layout("CV", cv, "CV"), encoding="utf-8")
    not_found = '<main class="section prose"><h1>Page not found.</h1><p><a href="index.html">Return home</a></p></main>'
    (DIST / "404.html").write_text(layout("Not found", not_found), encoding="utf-8")


if __name__ == "__main__":
    main()
