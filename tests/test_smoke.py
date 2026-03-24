from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from site_tree_md.crawler import SiteCrawler


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def serve(directory: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(directory)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_crawler_smoke(tmp_path) -> None:
    root = tmp_path / "site"
    root.mkdir()
    (root / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n", encoding="utf-8"
    )
    (root / "sitemap.xml").write_text(
        "<?xml version='1.0'?><urlset><url><loc>http://127.0.0.1:9/ignored</loc></url></urlset>",
        encoding="utf-8",
    )
    (root / "doc.pdf").write_bytes(b"%PDF-1.4 test")
    (root / "page.html").write_text(
        (
            "<html><head><title>Shared Title</title></head><body>"
            "<header><p>Neighborhood merchants unite</p></header>"
            "<nav><a href='/doc.pdf'>doc</a></nav>"
            "<main><h1>About the coalition</h1><p>hello from the page body</p>"
            "<p>More page-specific detail for this route.</p></main>"
            "<footer><p>Footer hotline</p></footer></body></html>"
        ),
        encoding="utf-8",
    )
    (root / "index.html").write_text(
        (
            "<html><head><title>Shared Title</title></head><body>"
            "<header><p>Shared header text</p></header>"
            "<nav><a href='/page.html'>page</a></nav>"
            "<main><h1>Home</h1><p>Home route specific content lives here.</p></main>"
            "<footer><p>Site footer</p></footer></body></html>"
        ),
        encoding="utf-8",
    )
    server, thread = serve(root)
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        crawler = SiteCrawler(
            url,
            tmp_path,
            ignore_robots=False,
            no_sitemaps=True,
            max_pages=10,
            save_source_html=True,
        )
        summary = crawler.crawl()
        crawler.manifest.write_summary(summary)
        assert (tmp_path / "web").exists()
        assert any(path.suffix == ".md" for path in (tmp_path / "web").rglob("*.md"))
        assert any(path.name == "doc.pdf" for path in (tmp_path / "web").rglob("doc.pdf"))
        assert (tmp_path / "web" / "_crawl_manifest.jsonl").exists()

        markdown_files = sorted((tmp_path / "web").rglob("*.md"))
        page_markdown = next(path for path in markdown_files if path.parent.name == "page.html")
        page_text = page_markdown.read_text(encoding="utf-8")
        assert "Neighborhood merchants unite" in page_text
        assert "hello from the page body" in page_text
        assert "Footer hotline" in page_text
        assert "https://127.0.0.1" not in page_text  # ensure content is body-rich, not only links
        assert "Shared Title" in page_text
        assert "More page-specific detail for this route." in page_text

        manifest_path = tmp_path / "web" / "_crawl_manifest.jsonl"
        records = [
            json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()
        ]
        html_records = [record for record in records if record["page_kind"] == "html"]
        assert all(record["conversion_strategy"] for record in html_records)
        assert all(record["extraction_mode"] == "full-page" for record in html_records)
        assert any(record["source_html_saved_to"] for record in html_records)
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_acceptance_script_is_repo_canonical() -> None:
    script = Path("scripts/acceptance_render.sh")
    text = script.read_text(encoding="utf-8")
    assert "python -m pip install -e \"$repo_root\"" in text
    assert "python -m site_tree_md \"https://smallbizunited.com/\"" in text
    assert "feature/scaffold" not in text
