# site-tree-md

`site-tree-md` archives a site root, subsection, or exact page into a deterministic URL-shaped filesystem tree under `./web/`.

## Features

- BFS crawl within the supplied same-host root scope.
- Default one-hop external capture via `--external-depth 1`.
- HTML converted to full-page Markdown with YAML front matter by default.
- Thin-output guard rejects title-only / overly sparse markdown and falls back to broader extraction.
- Optional `--main-content` mode keeps the previous article-style extraction behavior as an opt-in.
- Raw fetched HTML can be saved alongside Markdown with `--save-source-html`, and thin HTML pages automatically get a `.source.html` sidecar for debugging.
- Direct document/file links saved as raw files.
- Sitemap seeding, robots.txt support, manifest, failures log, and summary output.
- Repo-root shim: `uv run archive_site.py https://example.com/`.

## Install

### Development / editable install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .[dev]
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
uv run archive_site.py https://smallbizunited.com/ --main-content
uv run archive_site.py https://smallbizunited.com/ --save-source-html
```

## HTML conversion behavior

By default, HTML responses are archived as **full-page Markdown translations** of the fetched server HTML.

The conversion pipeline is:

1. Extract the title and measure visible text for heuristics.
2. Absolutize relative links and images using the page URL and any `<base href>`.
3. Remove only obvious non-content tags such as `script`, `style`, `noscript`, and `template`.
4. Convert the full `<body>` to Markdown, preserving headers, nav, main content, footer, lists, links, tables, forms, and buttons where practical.
5. If the result is suspiciously thin, recover text from embedded JSON app data and/or fall back to broader body text extraction.
6. If the fetched HTML is still too sparse, emit a warning stub and save a `.source.html` sidecar so the archive does not silently pretend success.

Use `--main-content` only when you explicitly want narrower article-style extraction.

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

Thin or explicitly requested HTML sidecars are saved next to the Markdown file:

```text
web/
  https:/
    smallbizunited.com/
      smallbizunited-com.md
      smallbizunited-com.source.html
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

Manifest records for HTML pages now include `conversion_strategy`, `extraction_mode`, `extraction_warning`, and `source_html_saved_to` when applicable.

## CLI options

```text
site-tree-md URL [--external-depth N] [--output-dir DIR] [--max-pages N]
                 [--timeout SECONDS] [--delay SECONDS] [--same-host-only]
                 [--ignore-robots] [--no-sitemap-seed] [--user-agent UA]
                 [--full-page | --main-content] [--save-source-html]
                 [--verbose]
```

## Limitations

- v1 is single-threaded and does not render JavaScript-heavy sites in a browser.
- For client-rendered app shells, the archive reflects fetched server HTML plus any recoverable embedded JSON text.
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
