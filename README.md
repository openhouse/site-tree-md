# site-tree-md

`site-tree-md` archives a site root, subsection, or exact page into a deterministic URL-shaped filesystem tree under `./web/`.

## Features

- BFS crawl within the supplied same-host root scope.
- Default one-hop external capture via `--external-depth 1`.
- HTML converted to full-page Markdown with YAML front matter by default.
- Thin-output guard rejects title-only / overly sparse markdown and falls back to broader extraction.
- Browser-rendered HTML support for client-rendered app shells with `--render-mode never|auto|always`; `auto` is the default.
- Sparse-shell pages can fall back from server HTML to a rendered Chromium DOM, with rendered DOM also used for link discovery.
- Server and rendered HTML provenance sidecars are preserved as `*.source.server.html` and `*.source.rendered.html` when rendering is attempted or debugging is requested.
- Optional `--main-content` mode keeps the previous article-style extraction behavior as an opt-in.
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

### With browser rendering support

```bash
python -m pip install -e .[dev,render]
python -m playwright install chromium
```

The `browser` extra is also available as an alias:

```bash
python -m pip install -e .[dev,browser]
python -m playwright install chromium
```

### With uv

```bash
uv sync --extra dev --extra render
uv run python -m playwright install chromium
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
uv run archive_site.py https://smallbizunited.com/ --render-mode auto --save-rendered-html
```

## HTML conversion behavior

By default, HTML responses are archived as full-page Markdown translations of fetched HTML, with browser rendering available when the server HTML is a sparse client-rendered shell.

### Render modes

- `--render-mode never`: only use `requests`; never launch a browser.
- `--render-mode auto` *(default)*: fetch server HTML first, then render with Playwright only when the server HTML looks like a sparse shell or conversion would otherwise collapse into a warning stub.
- `--render-mode always`: render every HTML page in Chromium and prefer the rendered DOM for Markdown conversion.

`--render-js` remains available as a backward-compatible opt-in alias for browser fallback behavior.

### Render setup and behavior

For rendered pages, the crawler:

1. Fetches server HTML with `requests`.
2. Detects sparse shells using low visible text, root-mount containers such as `#root` / `#app`, app-bundle markers, and failed Markdown conversion.
3. Reuses a Playwright Chromium browser/context across the crawl.
4. Navigates with `page.goto(...)`, waits for `domcontentloaded`, then the configured `--render-wait-until` state, then an additional settle delay via `--render-wait-ms`.
5. Optionally waits for `--render-selector` and optionally auto-scrolls via `--scroll` and related flags.
6. Converts the rendered DOM to Markdown and extracts links from the rendered DOM as well.

If both server HTML and rendered HTML are still too sparse, the crawler writes a warning stub with available metadata instead of pretending success.

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

When source sidecars are saved, server and rendered DOMs stay distinct:

```text
web/
  https:/
    smallbizunited.com/
      smallbizunited-com.md
      smallbizunited-com.source.server.html
      smallbizunited-com.source.rendered.html
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

Manifest records for HTML pages include provenance and diagnostics such as `render_mode`, `render_attempted`, `render_succeeded`, `render_warning`, `render_source`, `markdown_source`, `page_source_used`, `source_server_html_saved_to`, `source_rendered_html_saved_to`, `conversion_strategy`, `extraction_mode`, and `extraction_warning`.

## CLI options

```text
site-tree-md URL [--external-depth N] [--output-dir DIR] [--max-pages N]
                 [--timeout SECONDS] [--delay SECONDS] [--same-host-only]
                 [--ignore-robots] [--no-sitemap-seed] [--user-agent UA]
                 [--full-page | --main-content] [--save-source-html]
                 [--render-mode never|auto|always] [--render-js]
                 [--render-timeout SECONDS]
                 [--render-wait-until load|domcontentloaded|networkidle]
                 [--render-selector CSS] [--render-wait-ms MS]
                 [--scroll] [--scroll-steps N] [--scroll-step-px PX]
                 [--scroll-pause-ms MS] [--show-browser]
                 [--ignore-https-errors] [--save-rendered-html]
                 [--verbose]
```

## Limitations

- Browser rendering is optional and requires Playwright plus a local Chromium install.
- v1 remains single-threaded.
- Internal scope defaults to exact-host root-scope crawling; related-domain crawling is intentionally conservative.
- The crawler focuses on pages and linked documents, not full asset mirroring.

## Development

```bash
ruff format .
ruff check .
pytest
pytest tests/test_rendering.py
```

## Notes

Use this tool only where you have permission and where archiving complies with site policies and applicable law.
