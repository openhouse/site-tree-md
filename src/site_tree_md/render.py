from __future__ import annotations

import time
from dataclasses import dataclass

from site_tree_md.bootstrap import require_browser_runtime


@dataclass(slots=True)
class RenderResult:
    requested_url: str
    final_url: str | None
    html: str | None
    title: str | None
    status_code: int | None
    content_type: str | None
    render_succeeded: bool
    render_warning: str | None = None


@dataclass(slots=True)
class RenderOptions:
    timeout: float = 30.0
    wait_until: str = "networkidle"
    wait_selector: str | None = None
    wait_ms: int = 1200
    scroll: bool = False
    scroll_steps: int = 4
    scroll_step_px: int = 1200
    scroll_pause_ms: int = 250
    show_browser: bool = False
    ignore_https_errors: bool = False
    user_agent: str = "site-tree-md/0.1"


class BrowserRenderer:
    def __init__(self, options: RenderOptions) -> None:
        self.options = options
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self) -> BrowserRenderer:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.close()

    def start(self) -> None:
        if self._context is not None:
            return
        require_browser_runtime(verbose=False)
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=not self.options.show_browser)
        self._context = self._browser.new_context(
            user_agent=self.options.user_agent,
            ignore_https_errors=self.options.ignore_https_errors,
        )

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def render_page(self, url: str) -> RenderResult:
        self.start()
        assert self._context is not None
        page = self._context.new_page()
        response = None
        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=int(self.options.timeout * 1000),
            )
            target_wait = self.options.wait_until
            try:
                page.wait_for_load_state(target_wait, timeout=int(self.options.timeout * 1000))
            except Exception:
                if target_wait != "load":
                    page.wait_for_load_state("load", timeout=int(self.options.timeout * 1000))
            if self.options.wait_selector:
                page.wait_for_selector(
                    self.options.wait_selector,
                    timeout=int(self.options.timeout * 1000),
                )
            if self.options.scroll:
                self._auto_scroll(page)
            if self.options.wait_ms > 0:
                page.wait_for_timeout(self.options.wait_ms)
            return RenderResult(
                requested_url=url,
                final_url=page.url,
                html=page.content(),
                title=page.title(),
                status_code=response.status if response else None,
                content_type=(response.header_value("content-type") if response else None),
                render_succeeded=True,
            )
        except Exception as exc:  # pragma: no cover - deterministic via mocked tests
            return RenderResult(
                requested_url=url,
                final_url=page.url if page.url else url,
                html=None,
                title=None,
                status_code=response.status if response else None,
                content_type=(response.header_value("content-type") if response else None)
                if response
                else None,
                render_succeeded=False,
                render_warning=str(exc),
            )
        finally:
            page.close()

    def _auto_scroll(self, page) -> None:  # noqa: ANN001
        for _step in range(self.options.scroll_steps):
            page.evaluate("window.scrollBy(0, arguments[0])", self.options.scroll_step_px)
            if self.options.scroll_pause_ms > 0:
                page.wait_for_timeout(self.options.scroll_pause_ms)
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0)
