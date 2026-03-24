from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from site_tree_md.bootstrap import (
    BrowserRuntimeBootstrapError,
    RuntimeBootstrapStatus,
    reset_runtime_bootstrap_state,
)
from site_tree_md.cli import main
from site_tree_md.crawler import SiteCrawler
from site_tree_md.render import RenderResult

def setup_function() -> None:
    reset_runtime_bootstrap_state()


SPA_SHELL = (
    "<html><head><title>Fixture SPA</title></head><body>"
    "<div id='root'></div><script src='/app.js'></script></body></html>"
)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def serve(directory: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(directory)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_auto_mode_bootstrap_failure_degrades_gracefully(monkeypatch, tmp_path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(SPA_SHELL, encoding="utf-8")
    server, thread = serve(site)
    try:
        attempts = {"count": 0}

        def fake_ensure(self, *, fatal_on_failure: bool):
            attempts["count"] += 1
            self._render_runtime_checked = True
            self._render_runtime_status = RuntimeBootstrapStatus(
                available=False,
                attempted=True,
                auto_installed=True,
                install_attempted=True,
                install_succeeded=False,
                warning="playwright bootstrap failed: pip failed",
            )
            self._rendering_disabled = True
            if fatal_on_failure:
                raise BrowserRuntimeBootstrapError(self._render_runtime_status.warning)
            return self._render_runtime_status

        monkeypatch.setattr(SiteCrawler, "_ensure_renderer_ready", fake_ensure)
        crawler = SiteCrawler(
            f"http://127.0.0.1:{server.server_port}/",
            tmp_path,
            no_sitemaps=True,
            ignore_robots=True,
            render_mode="auto",
        )
        summary = crawler.crawl()
        crawler.manifest.write_summary(summary)

        assert attempts["count"] == 1
        assert summary.archived_html_pages == 1
        assert summary.errors == 0
        assert summary.warnings == 1
        assert summary.pages_render_attempted == 1
        assert summary.pages_render_failed == 1
        assert summary.pages_fell_back_to_server_html == 1
        assert summary.pages_written_as_failure_stub == 1
        assert summary.render_runtime_available is False
        record = json.loads((tmp_path / "web" / "_crawl_manifest.jsonl").read_text().splitlines()[0])
        assert record["page_kind"] == "html"
        assert record["render_attempted"] is True
        assert record["render_succeeded"] is False
        assert record["runtime_bootstrap_attempted"] is True
        assert record["runtime_bootstrap_succeeded"] is False
        assert "playwright bootstrap failed" in record["render_warning"]
        assert record["page_source_used"] == "server_html"
        assert not (tmp_path / "web" / "_crawl_failures.jsonl").exists()
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_always_mode_bootstrap_failure_fails_once(monkeypatch, tmp_path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(SPA_SHELL, encoding="utf-8")
    server, thread = serve(site)
    try:
        attempts = {"count": 0}

        def fake_ensure(self, *, fatal_on_failure: bool):
            attempts["count"] += 1
            raise BrowserRuntimeBootstrapError("playwright bootstrap failed: chromium install failed")

        monkeypatch.setattr(SiteCrawler, "_ensure_renderer_ready", fake_ensure)
        crawler = SiteCrawler(
            f"http://127.0.0.1:{server.server_port}/",
            tmp_path,
            no_sitemaps=True,
            ignore_robots=True,
            render_mode="always",
        )
        summary = crawler.crawl()

        assert attempts["count"] == 1
        assert summary.fatal_error == "playwright bootstrap failed: chromium install failed"
        assert summary.errors == 1
        failures = (tmp_path / "web" / "_crawl_failures.jsonl").read_text().splitlines()
        assert len(failures) == 1
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_bootstrap_only_once_for_multiple_pages(monkeypatch, tmp_path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(
        SPA_SHELL.replace("</body>", "<a href='/about/'>About</a></body>"), encoding="utf-8"
    )
    (site / "about").mkdir()
    (site / "about" / "index.html").write_text(SPA_SHELL, encoding="utf-8")
    server, thread = serve(site)
    try:
        attempts = {"count": 0}

        def fake_ensure(self, *, fatal_on_failure: bool):
            if self._render_runtime_checked:
                return self._render_runtime_status
            attempts["count"] += 1
            self._render_runtime_checked = True
            self._render_runtime_status = RuntimeBootstrapStatus(available=True, attempted=True)
            return self._render_runtime_status

        def fake_render(self, url):
            return RenderResult(
                requested_url=url,
                final_url=url,
                html=(
                    "<html><body><main><h1>Rendered</h1>"
                    f"<p>{url}</p></main></body></html>"
                ),
                title="Rendered",
                status_code=200,
                content_type="text/html",
                render_succeeded=True,
            )

        monkeypatch.setattr(SiteCrawler, "_ensure_renderer_ready", fake_ensure)
        monkeypatch.setattr("site_tree_md.render.BrowserRenderer.render_page", fake_render)
        crawler = SiteCrawler(
            f"http://127.0.0.1:{server.server_port}/",
            tmp_path,
            no_sitemaps=True,
            ignore_robots=True,
            render_mode="auto",
            max_pages=10,
        )
        summary = crawler.crawl()

        assert summary.archived_html_pages >= 2
        assert attempts["count"] == 1
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_summary_matches_manifest_warning_counts(monkeypatch, tmp_path, capsys) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(SPA_SHELL, encoding="utf-8")
    server, thread = serve(site)
    try:
        def fake_ensure(self, *, fatal_on_failure: bool):
            self._render_runtime_checked = True
            self._render_runtime_status = RuntimeBootstrapStatus(
                available=False,
                attempted=True,
                auto_installed=True,
                install_attempted=True,
                install_succeeded=False,
                warning="playwright bootstrap failed: chromium install failed",
            )
            self._rendering_disabled = True
            return self._render_runtime_status

        monkeypatch.setattr(SiteCrawler, "_ensure_renderer_ready", fake_ensure)
        exit_code = main(
            [
                f"http://127.0.0.1:{server.server_port}/",
                "--output-dir",
                str(tmp_path),
                "--no-sitemap-seed",
                "--ignore-robots",
                "--render-mode",
                "auto",
            ]
        )
        assert exit_code == 0
        stderr = capsys.readouterr().err
        assert "warnings=1" in stderr

        summary = json.loads((tmp_path / "web" / "_crawl_summary.json").read_text(encoding="utf-8"))
        manifest_records = [
            json.loads(line)
            for line in (tmp_path / "web" / "_crawl_manifest.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        manifest_warning_count = sum(
            1
            for record in manifest_records
            if record.get("render_warning")
            or record.get("extraction_warning")
            or record.get("runtime_bootstrap_warning")
        )
        assert summary["warnings"] == 1 == manifest_warning_count
        assert summary["pages_render_attempted"] == 1
        assert summary["pages_render_failed"] == 1
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_never_mode_skips_bootstrap(monkeypatch, tmp_path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<html><body><main><h1>Hello</h1></main></body></html>", encoding="utf-8")
    server, thread = serve(site)
    try:
        def fail(*args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("bootstrap should not run")

        monkeypatch.setattr(SiteCrawler, "_ensure_renderer_ready", fail)
        crawler = SiteCrawler(
            f"http://127.0.0.1:{server.server_port}/",
            tmp_path,
            no_sitemaps=True,
            ignore_robots=True,
            render_mode="never",
        )
        summary = crawler.crawl()
        assert summary.archived_html_pages == 1
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_cli_exit_behavior_for_zero_success_and_mixed_results(monkeypatch, tmp_path, capsys) -> None:
    class ZeroSuccessCrawler:
        def __init__(self, *args, **kwargs):
            self.manifest = type("Manifest", (), {"write_summary": lambda self, summary: None})()

        def crawl(self):
            from site_tree_md.models import CrawlSummary

            return CrawlSummary(
                seed_url="https://example.com/",
                scope_prefix="/",
                external_hop_depth=1,
                output_root=str(tmp_path / "web"),
                generated_at="2026-03-21T00:00:00+00:00",
                fetched_pages=1,
                counts_by_kind={"error": 1},
                archived_html_pages=0,
                archived_binary_pages=0,
                warnings=0,
                errors=1,
                render_runtime_required=True,
                render_runtime_available=False,
                render_runtime_auto_installed=True,
                render_runtime_install_attempted=True,
                render_runtime_install_succeeded=False,
                render_runtime_warning="playwright bootstrap failed",
                fatal_error="playwright bootstrap failed",
            )

    class MixedCrawler:
        def __init__(self, *args, **kwargs):
            self.manifest = type("Manifest", (), {"write_summary": lambda self, summary: None})()

        def crawl(self):
            from site_tree_md.models import CrawlSummary

            return CrawlSummary(
                seed_url="https://example.com/",
                scope_prefix="/",
                external_hop_depth=1,
                output_root=str(tmp_path / "web"),
                generated_at="2026-03-21T00:00:00+00:00",
                fetched_pages=2,
                counts_by_kind={"html": 1, "error": 1},
                archived_html_pages=1,
                archived_binary_pages=0,
                warnings=1,
                errors=1,
                render_runtime_required=True,
                render_runtime_available=False,
                render_runtime_auto_installed=True,
                render_runtime_install_attempted=True,
                render_runtime_install_succeeded=False,
                render_runtime_warning="playwright bootstrap failed",
                fatal_error=None,
            )

    monkeypatch.setattr("site_tree_md.cli.SiteCrawler", ZeroSuccessCrawler)
    assert main(["https://example.com", "--output-dir", str(tmp_path)]) == 1
    stderr_zero = capsys.readouterr().err
    assert "Fatal error" in stderr_zero

    monkeypatch.setattr("site_tree_md.cli.SiteCrawler", MixedCrawler)
    assert main(["https://example.com", "--output-dir", str(tmp_path)]) == 0
    stderr_mixed = capsys.readouterr().err
    assert "Crawl summary" in stderr_mixed
