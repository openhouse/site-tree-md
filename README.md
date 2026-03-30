# site-tree-md

`site-tree-md` archives a site root, subsection, or exact page into a deterministic URL-shaped filesystem tree under `./web/`.

## Features

- BFS crawl within the supplied same-host root scope.
- Default one-hop external capture via `--external-depth 1`.
- HTML converted to full-page Markdown with YAML front matter by default.
- Thin-output guard rejects title-only / overly sparse markdown and falls back to broader extraction.
- Browser-rendered HTML support for client-rendered app shells with `--render-mode never|auto|always`; `auto` is the default.
- Sparse-shell pages can fall back from server HTML to a rendered Chromium DOM, with rendered DOM also used for link discovery.
- Browser runtime bootstrap is automatic on first render attempt, including Playwright package repair and Chromium install when needed.
- In `--render-mode auto`, browser bootstrap failures degrade to server HTML plus warning provenance instead of page-level hard errors.
- In `--render-mode always`, browser bootstrap is attempted once and the crawl fails fast if the runtime still cannot be provisioned.
- Successful HTML archives now persist only `.md`; HTML sidecars are kept only for degraded/diagnostic outcomes (for example failure stubs or extraction warnings).
- Optional `--main-content` mode keeps the previous article-style extraction behavior as an opt-in.
- Direct document/file links saved as raw files.
- Sitemap seeding, robots.txt support, manifest, failures log, and summary output.
- Repo-root shim: `uv run archive_site.py https://example.com/`.

## Install

### Development / editable install

A normal editable install is enough for the default command path.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e .[dev]
```

You can also install the runtime without developer tooling:

```bash
python -m pip install -e .
```

### Browser runtime behavior

- The Python `playwright` package is part of the default install path.
- Chromium is bootstrapped automatically the first time a page actually needs browser rendering.
- The first SPA-heavy run may take longer because `site-tree-md` may run `python -m playwright install chromium` automatically.
- If browser bootstrap fails in `--render-mode auto`, the crawl keeps the server HTML result and records a render warning.
- If browser bootstrap fails in `--render-mode always`, the crawl stops once with a clear fatal error.

### Optional pre-provisioning

If you want to preinstall browser support ahead of time, the extras remain available as aliases:

```bash
python -m pip install -e .[dev,render]
python -m playwright install chromium
```

```bash
python -m pip install -e .[dev,browser]
python -m playwright install chromium
```

### With uv

```bash
uv sync --extra dev
uv run archive_site.py https://smallbizunited.com/
```

## Quickstart

```bash
site-tree-md https://smallbizunited.com/
python -m site_tree_md https://smallbizunited.com/
uv run archive_site.py https://smallbizunited.com/
bash scripts/acceptance_render.sh
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
bash scripts/acceptance_render.sh ./trial-run
```

Use `scripts/acceptance_render.sh` as the canonical acceptance command for rendered-crawl validation. It intentionally runs the current checkout, so there is no stale branch pinning to drift from `feature/render`.

## HTML conversion behavior

By default, HTML responses are archived as full-page Markdown translations of fetched HTML, with browser rendering available when the server HTML is a sparse client-rendered shell.

### Render modes

- `--render-mode never`: only use `requests`; never launch a browser.
- `--render-mode auto` *(default)*: fetch server HTML first, then render with Playwright only when the server HTML looks like a sparse shell or conversion would otherwise collapse into a warning stub. If bootstrap fails here, the crawler keeps server output and records a warning.
- `--render-mode always`: render every HTML page in Chromium and prefer the rendered DOM for Markdown conversion. If the browser runtime still cannot be provisioned, the crawl fails once and exits non-zero.

`--render-js` remains available as a backward-compatible opt-in alias for browser fallback behavior.

### Render setup and behavior

For rendered pages, the crawler:

1. Fetches server HTML with `requests`.
2. Detects sparse shells using low visible text, root-mount containers such as `#root` / `#app`, app-bundle markers, and failed Markdown conversion.
3. Bootstraps Playwright/Chromium once per crawl when rendering is first required, with runtime probing isolated in a subprocess before the main renderer starts.
4. Reuses a Playwright Chromium browser/context across the crawl.
5. Navigates with `page.goto(...)`, waits for `domcontentloaded`, then the configured `--render-wait-until` state, then an additional settle delay via `--render-wait-ms`.
6. Optionally waits for `--render-selector` and optionally auto-scrolls via `--scroll` and related flags.
7. Converts the rendered DOM to Markdown and extracts links from the rendered DOM as well.

If both server HTML and rendered HTML are still too sparse, the crawler writes a warning stub with available metadata instead of pretending success.

`--save-source-html` and `--save-rendered-html` are debug-oriented: they retain sidecars only when the HTML conversion outcome is degraded (for example `failure_stub` or an extraction warning), not for clean Markdown archives.

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

When an HTML page degrades to a diagnostic save, sidecars may be emitted:

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

Manifest records for HTML pages include provenance and diagnostics such as `render_mode`, `render_attempted`, `render_succeeded`, `render_warning`, `render_source`, `markdown_source`, `page_source_used`, `runtime_bootstrap_attempted`, `runtime_bootstrap_succeeded`, `runtime_bootstrap_warning`, `source_server_html_saved_to`, `source_rendered_html_saved_to`, `conversion_strategy`, `extraction_mode`, and `extraction_warning`. For clean HTML->Markdown saves, sidecar path fields remain `null`.

Summary records include `archived_html_pages`, `archived_binary_pages`, `warnings`, `errors`, `pages_render_attempted`, `pages_render_succeeded`, `pages_render_failed`, `pages_fell_back_to_server_html`, `pages_written_as_failure_stub`, `render_runtime_available`, `render_runtime_auto_installed`, `render_runtime_install_attempted`, `render_runtime_install_succeeded`, and `render_runtime_warning`.

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

- Browser bootstrap still depends on the current environment permitting package installs and Playwright browser downloads.
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
