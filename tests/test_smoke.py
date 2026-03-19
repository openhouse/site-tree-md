from __future__ import annotations

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
            "<html><head><title>Page</title></head><body><main>"
            "<p>hello</p><a href='/doc.pdf'>doc</a></main></body></html>"
        ),
        encoding="utf-8",
    )
    (root / "index.html").write_text(
        (
            "<html><head><title>Home</title></head><body><main>"
            "<a href='/page.html'>page</a></main></body></html>"
        ),
        encoding="utf-8",
    )
    server, thread = serve(root)
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        crawler = SiteCrawler(url, tmp_path, ignore_robots=False, no_sitemaps=True, max_pages=10)
        summary = crawler.crawl()
        crawler.manifest.write_summary(summary)
        assert (tmp_path / "web").exists()
        assert any(path.suffix == ".md" for path in (tmp_path / "web").rglob("*.md"))
        assert any(path.name == "doc.pdf" for path in (tmp_path / "web").rglob("doc.pdf"))
        assert (tmp_path / "web" / "_crawl_manifest.jsonl").exists()
    finally:
        server.shutdown()
        thread.join(timeout=2)
