# Nora Bradford

A small portfolio. Stories live in `content/stories.json`; the CV, research, About, and Fun sections are Markdown.

```sh
python3 scripts/preview.py       # http://localhost:8000
python3 scripts/preview.py 8080  # choose another port
python3 scripts/preview.py --host 0.0.0.0  # preview from a phone on the same network
python3 scripts/add-story.py 'https://example.com/a-new-story'
python3 scripts/add-story.py --dry-run 'https://example.com/a-new-story'
python3 scripts/add-story.py --check
python3 scripts/build.py
```

`add-story.py` reads the linked page's title, description, publication, date, and social image, then adds an editable entry to `content/stories.json`. It refuses duplicate URLs, retries blocked publishers through Jina Reader, and leaves unavailable fields blank rather than guessing. Use `--dry-run` to inspect the result without adding it; `--check` validates every existing entry and local image.

Pushing to `main` builds and publishes the site with GitHub Pages. In repository settings, set Pages source to **GitHub Actions** once.
