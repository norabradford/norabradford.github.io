# Nora Bradford

A small portfolio. Stories live in `content/stories.json`; the CV, research, About, and Fun sections are Markdown.

```sh
uv sync --locked
uv run python scripts/preview.py       # http://localhost:8000
uv run python scripts/preview.py 8080  # choose another port
uv run python scripts/preview.py --host 0.0.0.0  # preview from a phone on the same network
uv run python scripts/add-story.py 'https://example.com/a-new-story'
uv run python scripts/add-story.py --batch missing-story-links.txt
uv run python scripts/add-story.py --dry-run 'https://example.com/a-new-story'
uv run python scripts/add-story.py --check
uv run python scripts/build.py
```

`add-story.py` reads the linked page's title, description, publication, date, and social image. It saves the image in `img/portfolio`, then adds an editable entry with the local image path to `content/stories.json`.

It refuses duplicate URLs, retries blocked publishers through Jina Reader, and leaves unavailable fields blank rather than guessing.
Use `--dry-run` to inspect the result without adding it; `--check` validates every existing entry and local image.
Use `--batch FILE` to add several stories from a file containing one URL per line. Blank lines and lines beginning with `#` are ignored; duplicate and failed links do not stop the remaining imports.

The build creates 320px and 640px WebP thumbnails in `img/optimized`. Animated sources remain animated, and unchanged images are reused on later builds. A dry run only reports the remote image URL and does not download it.

Pushing to `main` builds and publishes the site with GitHub Pages.
