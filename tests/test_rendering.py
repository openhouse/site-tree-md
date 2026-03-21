from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from site_tree_md.crawler import SiteCrawler
from site_tree_md.markdown import html_to_markdown, is_sparse_shell_html
from site_tree_md.render import RenderResult

SPA_SHELL = (
    "<html><head><title>Fixture SPA</title></head><body>"
    "<div id='root'></div><script src='/app.js'></script></body></html>"
)
HYDRATION_SCRIPT = (
    b"document.addEventListener('DOMContentLoaded',()=>{"
    b"const r=document.getElementById('root');"
    b"const p=location.pathname==='/'"
    b"?'Home route rendered body text for members.'"
    b":'About route rendered story for neighborhood merchants.';"
    b"const link=location.pathname==='/'?'<a href=\"/about\">About</a>':'';"
    b"r.innerHTML='<main><h1>'+p+'</h1>'"
    b"+'<p>Hydrated content appears after script execution.</p>'+link+'</main>';"
    b"});"
)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


class FixtureHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/", "/index.html", "/about"}:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(SPA_SHELL.encode("utf-8"))
            return
        if self.path == "/app.js":
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.end_headers()
            self.wfile.write(HYDRATION_SCRIPT)
            return
        return super().do_GET()


def serve(handler, directory: Path | None = None):
    handler_factory = partial(handler, directory=str(directory)) if directory else handler
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_factory)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_sparse_shell_detection() -> None:
    html = "<html><body><div id='root'></div><script src='/app.js'></script></body></html>"
    assert is_sparse_shell_html(html)


def test_rendered_html_selected_for_markdown(monkeypatch, tmp_path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(SPA_SHELL.replace("Fixture SPA", "Shared"), encoding="utf-8")
    server, thread = serve(QuietHandler, site)
    hydrated_html = (
        "<html><head><title>Shared</title></head><body>"
        "<main><h1>Hydrated route</h1>"
        "<p>Rendered content for local businesses appears here.</p></main>"
        "</body></html>"
    )
    try:

        def fake_render(self, url):
            return RenderResult(
                requested_url=url,
                final_url=url,
                html=hydrated_html,
                title="Shared",
                status_code=200,
                content_type="text/html",
                render_succeeded=True,
            )

        monkeypatch.setattr("site_tree_md.render.BrowserRenderer.render_page", fake_render)
        crawler = SiteCrawler(
            f"http://127.0.0.1:{server.server_port}/",
            tmp_path,
            no_sitemaps=True,
            ignore_robots=True,
            render_mode="auto",
            save_rendered_html=True,
        )
        crawler.crawl()
        page = next((tmp_path / "web").rglob("*.md"))
        text = page.read_text(encoding="utf-8")
        assert "Hydrated route" in text
        manifest_lines = (tmp_path / "web" / "_crawl_manifest.jsonl").read_text(encoding="utf-8")
        record = json.loads(manifest_lines.splitlines()[0])
        assert record["page_source_used"] == "rendered_html"
        assert record["render_attempted"] is True
        assert record["render_succeeded"] is True
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_render_failure_keeps_stub(monkeypatch, tmp_path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(
        SPA_SHELL.replace(
            "<title>Fixture SPA</title>",
            "<title>Shared</title><meta name='description' content='Meta desc'>",
        ),
        encoding="utf-8",
    )
    server, thread = serve(QuietHandler, site)
    try:

        def fake_render(self, url):
            return RenderResult(
                requested_url=url,
                final_url=url,
                html=None,
                title=None,
                status_code=500,
                content_type="text/html",
                render_succeeded=False,
                render_warning="timeout",
            )

        monkeypatch.setattr("site_tree_md.render.BrowserRenderer.render_page", fake_render)
        crawler = SiteCrawler(
            f"http://127.0.0.1:{server.server_port}/",
            tmp_path,
            no_sitemaps=True,
            ignore_robots=True,
            render_mode="auto",
        )
        crawler.crawl()
        page = next((tmp_path / "web").rglob("*.md"))
        text = page.read_text(encoding="utf-8")
        assert "Meta description: Meta desc" in text
        manifest_lines = (tmp_path / "web" / "_crawl_manifest.jsonl").read_text(encoding="utf-8")
        manifest = json.loads(manifest_lines.splitlines()[0])
        assert manifest["render_succeeded"] is False
        assert manifest["render_warning"] == "timeout"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_render_sidecars_and_rendered_link_discovery(monkeypatch, tmp_path) -> None:
    server, thread = serve(FixtureHandler)
    try:

        def fake_render(self, url):
            if url.endswith("/about"):
                html = (
                    "<html><head><title>Fixture SPA</title></head><body>"
                    "<main><h1>About route rendered story</h1>"
                    "<p>About page body from hydrated DOM.</p></main></body></html>"
                )
            else:
                html = (
                    "<html><head><title>Fixture SPA</title></head><body>"
                    "<main><h1>Home route rendered body text</h1>"
                    "<p>Hydrated content appears after script execution.</p>"
                    "<a href='/about'>About</a></main></body></html>"
                )
            return RenderResult(
                requested_url=url,
                final_url=url,
                html=html,
                title="Fixture SPA",
                status_code=200,
                content_type="text/html",
                render_succeeded=True,
            )

        monkeypatch.setattr("site_tree_md.render.BrowserRenderer.render_page", fake_render)
        crawler = SiteCrawler(
            f"http://127.0.0.1:{server.server_port}/",
            tmp_path,
            no_sitemaps=True,
            ignore_robots=True,
            render_mode="auto",
            save_rendered_html=True,
            max_pages=10,
        )
        crawler.crawl()
        all_md = sorted((tmp_path / "web").rglob("*.md"))
        assert len(all_md) >= 2
        sidecars = sorted(path.name for path in (tmp_path / "web").rglob("*.html"))
        assert any(name.endswith(".source.server.html") for name in sidecars)
        assert any(name.endswith(".source.rendered.html") for name in sidecars)
        about_texts = [
            path.read_text(encoding="utf-8") for path in all_md if path.parent.name == "about"
        ]
        assert any("About route rendered story" in text for text in about_texts)
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_html_to_markdown_stub_includes_metadata() -> None:
    html = (
        "<html><head><title>Page</title><meta name='description' content='Desc'>"
        "<meta property='og:description' content='OG Desc'>"
        "<link rel='canonical' href='https://example.com/page'></head>"
        "<body><div id='root'></div><script src='/app.js'></script></body></html>"
    )
    result = html_to_markdown(html, "https://example.com/page")
    assert result.conversion_strategy == "failure_stub"
    assert "Meta description: Desc" in result.markdown
    assert "Canonical URL: https://example.com/page" in result.markdown
