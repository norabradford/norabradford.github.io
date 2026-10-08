# Nora Bradford

A small portfolio. Stories live in `content/stories.json`; the CV, research, About, and Fun sections are Markdown.

To add a story on GitHub, go to **Actions → Add story → Run workflow**, paste the URL into **Story URL**, and click **Run workflow**.
After a few minutes, the new story will appear in the website.
If it fails, check the action logs for the error.

```sh
uv sync --locked
uv run python scripts/preview.py       # http://localhost:8000
uv run python scripts/preview.py 8080  # choose another preview port (if 8000 is in use)
uv run python scripts/preview.py --host 0.0.0.0  # preview from a phone on the same network
uv run python scripts/add-story.py 'https://example.com/a-new-story'
uv run python scripts/add-story.py --batch missing-story-links.txt
uv run python scripts/add-story.py --dry-run 'https://example.com/a-new-story' 
uv run python scripts/add-story.py --check # validate all existing stories and local images
uv run python scripts/build.py
```


`add-story.py` reads the linked page's title, description, publication, date, and social image. It saves the image in `img/portfolio`, then adds an editable entry with the local image path to `content/stories.json`.
New stories set `"show-descrition": false`, so descriptions stay hidden unless that flag is manually changed to `true`.

It refuses duplicate URLs, retries blocked publishers through Jina Reader, and leaves unavailable fields blank rather than guessing.
Use `--dry-run` to inspect the result without adding it; `--check` validates every existing entry and local image.
Use `--batch FILE` to add several stories from a file containing one URL per line. Blank lines and lines beginning with `#` are ignored; duplicate and failed links do not stop the remaining imports.

The build creates 320px and 640px WebP thumbnails in `img/optimized`.

Pushing to `main` builds and publishes the site with GitHub Pages.
