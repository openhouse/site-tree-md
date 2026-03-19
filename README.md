# site-tree-md

`site-tree-md` archives a site root, subsection, or exact page into a deterministic URL-shaped filesystem tree under `./web/`.

## Features

- BFS crawl within the supplied same-host root scope.
- Default one-hop external capture via `--external-depth 1`.
- HTML converted to readable Markdown with YAML front matter.
- Direct document/file links saved as raw files.
- Sitemap seeding, robots.txt support, manifest, failures log, and summary output.
- Repo-root shim: `uv run archive_site.py https://example.com/`.

## Install

### Development / editable install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

### With uv

```bash
uv sync --extra dev
```

## Quickstart

```bash
site-tree-md https://smallbizunited.com/
python -m site_tree_md https://smallbizunited.com/
uv run archive_site.py https://smallbizunited.com/
```

## Examples

```bash
uv run archive_site.py https://smallbizunited.com/
uv run archive_site.py https://smallbizunited.com/news/
uv run archive_site.py https://smallbizunited.com/ --external-depth 1
uv run archive_site.py https://smallbizunited.com/ --max-pages 2000 --delay 0.5
```

## Scope model

- A root URL like `https://example.com/` crawls the host.
- A subtree URL like `https://example.com/docs/` crawls only that subtree.
- A file-like URL such as `https://example.com/page.html` archives that exact page as the root-scope item.
- External links are captured up to `--external-depth`; at the default `1`, directly linked third-party pages are saved but not recursively expanded further.

## Output layout

HTML pages become Markdown named from the host slug.

```text
web/
  https:/
    smallbizunited.com/
      smallbizunited-com.md
    smallbizunited.com/
      news/
        smallbizunited-com.md
```

Binary assets use a one-URL-one-directory layout:

```text
web/
  https:/
    example.com/
      files/
        report.pdf/
          report.pdf
```

Each run also writes:

- `web/_crawl_manifest.jsonl`
- `web/_crawl_failures.jsonl`
- `web/_crawl_summary.json`

## CLI options

```text
site-tree-md URL [--external-depth N] [--output-dir DIR] [--max-pages N]
                 [--timeout SECONDS] [--delay SECONDS] [--same-host-only]
                 [--ignore-robots] [--no-sitemap-seed] [--user-agent UA]
                 [--verbose]
```

## Limitations

- v1 is single-threaded and does not render JavaScript-heavy sites.
- Internal scope defaults to exact-host root-scope crawling; related-domain crawling is intentionally conservative.
- The crawler focuses on pages and linked documents, not full asset mirroring.

## Development

```bash
ruff format .
ruff check .
pytest
```

## Notes

Use this tool only where you have permission and where archiving complies with site policies and applicable law.
