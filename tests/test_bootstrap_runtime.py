from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from site_tree_md import bootstrap
from site_tree_md.cli import main
from site_tree_md.crawler import SiteCrawler
from site_tree_md.render import RenderResult


@pytest.fixture(autouse=True)
def reset_runtime_state() -> None:
    bootstrap.reset_browser_runtime_state()
    yield
    bootstrap.reset_browser_runtime_state()


def test_missing_playwright_triggers_package_install_once(monkeypatch) -> None:
    calls: list[list[str]] = []
    state = {"import_calls": 0}

    def fake_import() -> object:
        state["import_calls"] += 1
        if state["import_calls"] == 1:
            raise ImportError("missing")
        return object()

    monkeypatch.setattr(bootstrap, "_import_playwright_sync_api", fake_import)
    monkeypatch.setattr(bootstrap, "_probe_browser", lambda verbose=False: (True, None))
    monkeypatch.setattr(bootstrap, "_playwright_version", lambda: "1.52.0")
    monkeypatch.setattr(bootstrap, "_load_marker", lambda: None)
    monkeypatch.setattr(bootstrap, "_write_marker", lambda browser_name: None)
    monkeypatch.setattr(bootstrap, "_run_command", lambda cmd, verbose=False: calls.append(cmd))

    status = bootstrap.ensure_browser_runtime(verbose=True)
    again = bootstrap.ensure_browser_runtime(verbose=True)

    assert status.available is True
    assert status.install_attempted is True
    assert calls == [[bootstrap.sys.executable, "-m", "pip", "install", "playwright>=1.52"]]
    assert again is status


def test_missing_chromium_triggers_browser_install_once(monkeypatch) -> None:
    calls: list[list[str]] = []
    probes = iter([(False, "missing chromium"), (True, None)])

    monkeypatch.setattr(bootstrap, "_import_playwright_sync_api", lambda: object())
    monkeypatch.setattr(bootstrap, "_probe_browser", lambda verbose=False: next(probes))
    monkeypatch.setattr(bootstrap, "_playwright_version", lambda: "1.52.0")
    monkeypatch.setattr(bootstrap, "_load_marker", lambda: None)
    monkeypatch.setattr(bootstrap, "_write_marker", lambda browser_name: None)
    monkeypatch.setattr(bootstrap, "_run_command", lambda cmd, verbose=False: calls.append(cmd))

    status = bootstrap.ensure_browser_runtime()

    assert status.available is True
    assert calls == [[bootstrap.sys.executable, "-m", "playwright", "install", "chromium"]]


def test_auto_mode_bootstrap_failure_falls_back(monkeypatch, tmp_path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(
        "<html><head><title>SPA</title></head><body><div id='root'></div></body></html>",
        encoding="utf-8",
    )

    class FakeResponse:
        def __init__(self, url: str, text: str) -> None:
            self.url = url
            self.text = text
            self.content = text.encode("utf-8")
            self.status_code = 200
            self.headers = {"content-type": "text/html; charset=utf-8"}

    monkeypatch.setattr(
        "site_tree_md.crawler.ensure_browser_runtime",
        lambda verbose=False: bootstrap.BrowserRuntimeStatus(
            required=True,
            available=False,
            auto_installed=True,
            install_attempted=True,
            install_succeeded=False,
            warning="bootstrap failed",
        ),
    )
    monkeypatch.setattr(
        "site_tree_md.crawler.requests.Session.get",
        lambda self, url, timeout=30.0: FakeResponse(url, site.joinpath("index.html").read_text()),
    )

    crawler = SiteCrawler(
        "https://example.com/",
        tmp_path,
        no_sitemaps=True,
        ignore_robots=True,
        render_mode="auto",
    )
    summary = crawler.crawl()
    crawler.manifest.write_summary(summary)

    assert summary.counts_by_kind.get("html") == 1
    assert summary.counts_by_kind.get("error", 0) == 0
    manifest = json.loads((tmp_path / "web" / "_crawl_manifest.jsonl").read_text().splitlines()[0])
    assert manifest["render_warning"] == "bootstrap failed"
    assert manifest["runtime_bootstrap_succeeded"] is False


def test_always_mode_bootstrap_failure_is_single_error(monkeypatch, tmp_path) -> None:
    class FakeResponse:
        def __init__(self, url: str) -> None:
            self.url = url
            self.text = "<html><body><div id='root'></div></body></html>"
            self.content = self.text.encode()
            self.status_code = 200
            self.headers = {"content-type": "text/html"}

    monkeypatch.setattr(
        "site_tree_md.crawler.ensure_browser_runtime",
        lambda verbose=False: bootstrap.BrowserRuntimeStatus(
            required=True,
            available=False,
            auto_installed=True,
            install_attempted=True,
            install_succeeded=False,
            warning="cannot install chromium",
        ),
    )
    monkeypatch.setattr(
        "site_tree_md.crawler.requests.Session.get",
        lambda self, url, timeout=30.0: FakeResponse(url),
    )

    crawler = SiteCrawler(
        "https://example.com/",
        tmp_path,
        no_sitemaps=True,
        ignore_robots=True,
        render_mode="always",
        max_pages=5,
    )
    summary = crawler.crawl()

    assert summary.counts_by_kind.get("error") == 1
    failures = (tmp_path / "web" / "_crawl_failures.jsonl").read_text().splitlines()
    assert len(failures) == 1


def test_bootstrap_helper_used_once_per_run(monkeypatch, tmp_path) -> None:
    calls = {"count": 0}
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(
        "<html><body><div id='root'></div><a href='/about'>About</a></body></html>",
        encoding="utf-8",
    )
    (site / "about").write_text(
        "<html><body><div id='root'></div></body></html>",
        encoding="utf-8",
    )

    class FakeResponse:
        def __init__(self, url: str, body: str) -> None:
            self.url = url
            self.text = body
            self.content = body.encode()
            self.status_code = 200
            self.headers = {"content-type": "text/html"}

    def fake_get(self, url, timeout=30.0):
        body = (
            site.joinpath("index.html").read_text()
            if url.endswith("/")
            else site.joinpath("about").read_text()
        )
        return FakeResponse(url, body)

    def fake_bootstrap(verbose=False):
        calls["count"] += 1
        return bootstrap.BrowserRuntimeStatus(True, True, False, False, True)

    monkeypatch.setattr("site_tree_md.crawler.ensure_browser_runtime", fake_bootstrap)
    monkeypatch.setattr("site_tree_md.crawler.requests.Session.get", fake_get)
    monkeypatch.setattr(
        "site_tree_md.render.BrowserRenderer.render_page",
        lambda self, url: RenderResult(
            url, url, "<html><body><main>ok</main></body></html>", "ok", 200, "text/html", True
        ),
    )

    crawler = SiteCrawler("https://example.com/", tmp_path, no_sitemaps=True, ignore_robots=True)
    crawler.crawl()

    assert calls["count"] == 1


def test_never_mode_skips_bootstrap(monkeypatch, tmp_path) -> None:
    class FakeResponse:
        def __init__(self, url: str) -> None:
            self.url = url
            self.text = "<html><body><main>plain html body</main></body></html>"
            self.content = self.text.encode()
            self.status_code = 200
            self.headers = {"content-type": "text/html"}

    def fail_bootstrap(verbose=False):
        raise AssertionError("bootstrap should not be called")

    monkeypatch.setattr("site_tree_md.crawler.ensure_browser_runtime", fail_bootstrap)
    monkeypatch.setattr(
        "site_tree_md.crawler.requests.Session.get",
        lambda self, url, timeout=30.0: FakeResponse(url),
    )

    crawler = SiteCrawler(
        "https://example.com/",
        tmp_path,
        no_sitemaps=True,
        ignore_robots=True,
        render_mode="never",
    )
    summary = crawler.crawl()

    assert summary.counts_by_kind.get("html") == 1


def test_zero_success_exit_code_non_zero(monkeypatch, tmp_path) -> None:
    class FakeCrawler:
        def __init__(self, *args, **kwargs) -> None:
            self.manifest = SimpleNamespace(write_summary=lambda summary: None)

        def crawl(self):
            from site_tree_md.models import CrawlSummary

            return CrawlSummary(
                seed_url="https://example.com/",
                scope_prefix="/",
                external_hop_depth=1,
                output_root=str(tmp_path / "web"),
                generated_at="now",
                fetched_pages=1,
                counts_by_kind={"error": 1},
            )

    monkeypatch.setattr("site_tree_md.cli.SiteCrawler", FakeCrawler)
    assert main(["https://example.com/"]) == 1


def test_mixed_success_exit_code_zero(monkeypatch, tmp_path) -> None:
    class FakeCrawler:
        def __init__(self, *args, **kwargs) -> None:
            self.manifest = SimpleNamespace(write_summary=lambda summary: None)

        def crawl(self):
            from site_tree_md.models import CrawlSummary

            return CrawlSummary(
                seed_url="https://example.com/",
                scope_prefix="/",
                external_hop_depth=1,
                output_root=str(tmp_path / "web"),
                generated_at="now",
                fetched_pages=2,
                counts_by_kind={"html": 1, "error": 1},
                render_runtime_available=True,
            )

    monkeypatch.setattr("site_tree_md.cli.SiteCrawler", FakeCrawler)
    assert main(["https://example.com/"]) == 0
