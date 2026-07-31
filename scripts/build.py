#!/usr/bin/env python3
"""Build the static site with Python's standard library."""

from __future__ import annotations

import html
import json
import re
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT, STATIC, DIST = ROOT / "content", ROOT / "static", ROOT / "dist"


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


def story_card(story: dict[str, str]) -> str:
    url = html.escape(story["url"], quote=True)
    image = story.get("image", "")
    picture = (
        f'<a href="{url}" tabindex="-1"><img class="story-image" src="{html.escape(image, quote=True)}" alt="" loading="lazy"></a>'
        if image
        else ""
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
    stories = json.loads((CONTENT / "stories.json").read_text())
    stories.sort(key=lambda item: item.get("date", ""), reverse=True)
    cards = "".join(story_card(story) for story in stories)
    research = markdown((CONTENT / "research.md").read_text())
    about = markdown((CONTENT / "about.md").read_text())
    about = about.replace("</h1>", f"</h1>\n{portrait('about-portrait')}", 1)
    fun = markdown((CONTENT / "fun.md").read_text())
    home = f"""<main class="section home-intro">
      <div class="home-copy">
        <p class="home-name"><a href="https://norabradford.github.io">Nora Bradford, Ph.D.</a></p>
        <p class="intro">Science writer and lecturer at UPenn. Follow me on Bluesky: <a href="https://bsky.app/profile/norabradford.bsky.social">@norabradford</a></p>
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
        "about.html": ("About", f'<main class="section prose about">{about}</main>', "About"),
        "fun.html": ("Fun", f'<main class="section prose fun">{fun}</main>', "Fun"),
    }

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    shutil.copytree(STATIC, DIST, dirs_exist_ok=True)
    shutil.copytree(ROOT / "img", DIST / "img")
    shutil.copy2(ROOT / "CNAME", DIST / "CNAME")
    for filename, (title, body, current) in pages.items():
        (DIST / filename).write_text(layout(title, body, current))

    cv_content = markdown((CONTENT / "cv.md").read_text())
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
    (DIST / "cv.html").write_text(layout("CV", cv, "CV"))
    not_found = '<main class="section prose"><h1>Page not found.</h1><p><a href="index.html">Return home</a></p></main>'
    (DIST / "404.html").write_text(layout("Not found", not_found))


if __name__ == "__main__":
    main()
