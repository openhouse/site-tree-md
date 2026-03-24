from __future__ import annotations

import json
import time
from collections import Counter, deque
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from site_tree_md.bootstrap import (
    BrowserRuntimeBootstrapError,
    RuntimeBootstrapStatus,
    get_runtime_bootstrap_status,
)
from site_tree_md.manifest import ManifestWriter
from site_tree_md.markdown import (
    MarkdownConversionResult,
    extract_page_metadata,
    html_to_markdown,
    is_sparse_shell_html,
    visible_text_length,
)
from site_tree_md.models import CrawlSummary, CrawlTask, ManifestRecord, SaveResult
from site_tree_md.paths import (
    binary_path,
    classify_content,
    markdown_path,
    source_rendered_html_path,
    source_server_html_path,
)
from site_tree_md.render import BrowserRenderer, RenderOptions, RenderResult
from site_tree_md.robots import RobotsCache
from site_tree_md.scope import CrawlScope
from site_tree_md.sitemap import discover_sitemaps, parse_sitemap_bytes
from site_tree_md.utils import ensure_parent, normalize_url, sha256_bytes


class SiteCrawler:
    def __init__(
        self,
        seed_url: str,
        output_dir: Path,
        external_depth: int = 1,
        delay: float = 0.15,
        timeout: float = 30.0,
        max_pages: int = 5000,
        no_sitemaps: bool = False,
        same_host_only: bool = False,
        ignore_robots: bool = False,
        user_agent: str = "site-tree-md/0.1",
        verbose: bool = False,
        page_mode: str = "full-page",
        save_source_html: bool = False,
        render_mode: str = "auto",
        render_timeout: float = 30.0,
        render_wait_until: str = "networkidle",
        render_selector: str | None = None,
        render_wait_ms: int = 1200,
        scroll: bool = False,
        scroll_steps: int = 4,
        scroll_step_px: int = 1200,
        scroll_pause_ms: int = 250,
        show_browser: bool = False,
        ignore_https_errors: bool = False,
        save_rendered_html: bool = False,
    ) -> None:
        self.seed_url = normalize_url(seed_url)
        self.output_dir = output_dir
        self.external_depth = external_depth
        self.delay = delay
        self.timeout = timeout
        self.max_pages = max_pages
        self.no_sitemaps = no_sitemaps
        self.scope = CrawlScope(self.seed_url, same_host_only=same_host_only)
        self.ignore_robots = ignore_robots
        self.verbose = verbose
        self.page_mode = page_mode
        self.save_source_html = save_source_html
        self.render_mode = render_mode
        self.render_timeout = render_timeout
        self.render_wait_until = render_wait_until
        self.render_selector = render_selector
        self.render_wait_ms = render_wait_ms
        self.scroll = scroll
        self.scroll_steps = scroll_steps
        self.scroll_step_px = scroll_step_px
        self.scroll_pause_ms = scroll_pause_ms
        self.show_browser = show_browser
        self.ignore_https_errors = ignore_https_errors
        self.save_rendered_html = save_rendered_html
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.manifest = ManifestWriter(output_dir)
        self.robots = RobotsCache(self.session, timeout, user_agent)
        self.counts = Counter()
        self.warning_count = 0
        self.render_counts = Counter()
        self._renderer: BrowserRenderer | None = None
        self._render_runtime_status = RuntimeBootstrapStatus(available=False)
        self._render_runtime_checked = False
        self._rendering_disabled = render_mode == "never"
        self._fatal_error: str | None = None
        self._user_agent = user_agent

    def crawl(self) -> CrawlSummary:
        queue = deque([CrawlTask(self.seed_url, None, 0)])
        seen = set()
        try:
            if self.render_mode == "always":
                try:
                    self._ensure_renderer_ready(fatal_on_failure=True)
                except BrowserRuntimeBootstrapError as exc:
                    self._fatal_error = str(exc)
                    self.counts["error"] += 1
                    self.manifest.append(
                        ManifestRecord(
                            requested_url=self.seed_url,
                            final_url=None,
                            status_code=None,
                            content_type=None,
                            saved_to=None,
                            page_kind="error",
                            title=None,
                            discovered_from=None,
                            external_hops=0,
                            error=str(exc),
                            render_mode=self.render_mode,
                            runtime_bootstrap_attempted=self._render_runtime_status.attempted,
                            runtime_bootstrap_succeeded=self._render_runtime_status.available,
                            runtime_bootstrap_warning=self._render_runtime_status.warning,
                        )
                    )
                    return self._build_summary()
            if not self.no_sitemaps:
                for sitemap_url in discover_sitemaps(self.seed_url, self.session, self.timeout):
                    try:
                        response = self.session.get(sitemap_url, timeout=self.timeout)
                        response.raise_for_status()
                        for url in parse_sitemap_bytes(response.content):
                            if self.scope.in_root_scope(url):
                                queue.append(CrawlTask(url, sitemap_url, 0, via_sitemap=True))
                    except Exception:
                        continue
            while queue and (self.max_pages <= 0 or sum(self.counts.values()) < self.max_pages):
                task = queue.popleft()
                if task.url in seen:
                    continue
                seen.add(task.url)
                if not self.ignore_robots and not self.robots.can_fetch(task.url):
                    continue
                if self.delay:
                    time.sleep(self.delay)
                try:
                    response = self.session.get(task.url, timeout=self.timeout)
                    final_url = normalize_url(response.url)
                    if final_url in seen and final_url != task.url:
                        continue
                    kind = classify_content(final_url, response.headers.get("content-type", ""))
                    save_result, link_html, title = self._save_response(task, response, kind)
                    self.counts[kind] += 1
                    self.manifest.append(
                        ManifestRecord(
                            requested_url=task.url,
                            final_url=final_url,
                            status_code=response.status_code,
                            content_type=response.headers.get("content-type"),
                            saved_to=str(save_result.path.relative_to(self.output_dir)),
                            page_kind=kind,
                            title=title,
                            discovered_from=task.discovered_from,
                            external_hops=task.external_hops,
                            sha256=save_result.sha256,
                            conversion_strategy=save_result.conversion_strategy,
                            extraction_mode=save_result.extraction_mode,
                            extraction_warning=save_result.extraction_warning,
                            source_html_saved_to=(
                                str(save_result.source_html_path.relative_to(self.output_dir))
                                if save_result.source_html_path
                                else None
                            ),
                            render_mode=self.render_mode if kind == "html" else None,
                            render_attempted=save_result.render_attempted,
                            render_succeeded=save_result.render_succeeded,
                            render_warning=save_result.render_warning,
                            render_source=save_result.render_source,
                            rendered=save_result.rendered,
                            markdown_source=save_result.markdown_source,
                            page_source_used=save_result.page_source_used,
                            source_server_html_saved_to=(
                                str(save_result.server_html_path.relative_to(self.output_dir))
                                if save_result.server_html_path
                                else None
                            ),
                            source_rendered_html_saved_to=(
                                str(save_result.rendered_html_path.relative_to(self.output_dir))
                                if save_result.rendered_html_path
                                else None
                            ),
                            render_wait_until=self.render_wait_until if kind == "html" else None,
                            render_selector=self.render_selector if kind == "html" else None,
                            runtime_bootstrap_attempted=save_result.runtime_bootstrap_attempted,
                            runtime_bootstrap_succeeded=save_result.runtime_bootstrap_succeeded,
                            runtime_bootstrap_warning=save_result.runtime_bootstrap_warning,
                        )
                    )
                    if (
                        save_result.render_warning
                        or save_result.extraction_warning
                        or save_result.runtime_bootstrap_warning
                    ):
                        self.warning_count += 1
                    if self.verbose:
                        if kind == "html":
                            print(
                                f"saved [{kind}] {final_url} -> {save_result.path} "
                                "("
                                f"conversion={save_result.conversion_strategy}, "
                                f"source={save_result.markdown_source}"
                                ")"
                            )
                        else:
                            print(f"saved [{kind}] {final_url} -> {save_result.path}")
                    if kind == "html":
                        for next_task in self._extract_links(task, link_html, final_url):
                            if next_task.url not in seen:
                                queue.append(next_task)
                except BrowserRuntimeBootstrapError as exc:
                    self._fatal_error = str(exc)
                    self.counts["error"] += 1
                    self.manifest.append(
                        ManifestRecord(
                            requested_url=task.url,
                            final_url=None,
                            status_code=None,
                            content_type=None,
                            saved_to=None,
                            page_kind="error",
                            title=None,
                            discovered_from=task.discovered_from,
                            external_hops=task.external_hops,
                            error=str(exc),
                            render_mode=self.render_mode,
                            runtime_bootstrap_attempted=self._render_runtime_status.attempted,
                            runtime_bootstrap_succeeded=self._render_runtime_status.available,
                            runtime_bootstrap_warning=self._render_runtime_status.warning,
                        )
                    )
                    break
                except Exception as exc:
                    self.counts["error"] += 1
                    self.manifest.append(
                        ManifestRecord(
                            requested_url=task.url,
                            final_url=None,
                            status_code=None,
                            content_type=None,
                            saved_to=None,
                            page_kind="error",
                            title=None,
                            discovered_from=task.discovered_from,
                            external_hops=task.external_hops,
                            error=str(exc),
                            render_mode=self.render_mode,
                            runtime_bootstrap_attempted=self._render_runtime_status.attempted,
                            runtime_bootstrap_succeeded=self._render_runtime_status.available,
                            runtime_bootstrap_warning=self._render_runtime_status.warning,
                        )
                    )
            return self._build_summary()
        finally:
            if self._renderer is not None:
                self._renderer.close()

    def _build_summary(self) -> CrawlSummary:
        archived_html_pages = self.counts.get("html", 0)
        archived_binary_pages = self.counts.get("binary", 0) + self.counts.get("text", 0)
        return CrawlSummary(
            seed_url=self.seed_url,
            scope_prefix=self.scope.seed_path,
            external_hop_depth=self.external_depth,
            output_root=str((self.output_dir / "web").resolve()),
            generated_at=datetime.now(UTC).isoformat(),
            fetched_pages=sum(self.counts.values()),
            counts_by_kind=dict(self.counts),
            archived_html_pages=archived_html_pages,
            archived_binary_pages=archived_binary_pages,
            warnings=self.warning_count,
            errors=self.counts.get("error", 0),
            pages_render_attempted=self.render_counts.get("attempted", 0),
            pages_render_succeeded=self.render_counts.get("succeeded", 0),
            pages_render_failed=self.render_counts.get("failed", 0),
            pages_fell_back_to_server_html=self.render_counts.get("fell_back_to_server_html", 0),
            pages_written_as_failure_stub=self.render_counts.get("failure_stub", 0),
            render_runtime_required=self.render_mode != "never",
            render_runtime_available=self._render_runtime_status.available,
            render_runtime_auto_installed=self._render_runtime_status.auto_installed,
            render_runtime_install_attempted=self._render_runtime_status.install_attempted,
            render_runtime_install_succeeded=self._render_runtime_status.install_succeeded,
            render_runtime_warning=self._render_runtime_status.warning,
            fatal_error=self._fatal_error,
        )

    def _ensure_renderer_ready(self, *, fatal_on_failure: bool) -> RuntimeBootstrapStatus:
        if self._rendering_disabled:
            return self._render_runtime_status
        if self._renderer is None:
            self._renderer = BrowserRenderer(
                RenderOptions(
                    timeout=self.render_timeout,
                    wait_until=self.render_wait_until,
                    wait_selector=self.render_selector,
                    wait_ms=self.render_wait_ms,
                    scroll=self.scroll,
                    scroll_steps=self.scroll_steps,
                    scroll_step_px=self.scroll_step_px,
                    scroll_pause_ms=self.scroll_pause_ms,
                    show_browser=self.show_browser,
                    ignore_https_errors=self.ignore_https_errors,
                    user_agent=self._user_agent,
                    verbose=self.verbose,
                )
            )
        if self._render_runtime_checked:
            if fatal_on_failure and not self._render_runtime_status.available:
                raise BrowserRuntimeBootstrapError(
                    self._render_runtime_status.warning or "browser runtime unavailable"
                )
            return self._render_runtime_status
        self._render_runtime_checked = True
        try:
            self._renderer.start()
            self._render_runtime_status = RuntimeBootstrapStatus(available=True, attempted=True)
        except BrowserRuntimeBootstrapError as exc:
            self._render_runtime_status = RuntimeBootstrapStatus(
                available=False,
                attempted=True,
                auto_installed=True,
                install_attempted=True,
                install_succeeded=False,
                warning=str(exc),
            )
            self._rendering_disabled = True
            if fatal_on_failure:
                if self.verbose:
                    print(f"Fatal browser runtime bootstrap failure: {exc}")
                raise
        else:
            bootstrap_status = get_runtime_bootstrap_status()
            if bootstrap_status is not None:
                self._render_runtime_status = bootstrap_status
            else:
                self._render_runtime_status.attempted = True
            if self.verbose and self._render_runtime_status.attempted:
                print("Browser runtime is available for rendered fallback.")
        return self._render_runtime_status

    def _front_matter_lines(
        self,
        task: CrawlTask,
        response: requests.Response,
        final_url: str,
        conversion: MarkdownConversionResult,
        *,
        source_html: str,
        rendered_html: str | None,
        save_result: SaveResult,
    ) -> list[str]:
        source_metadata = extract_page_metadata(rendered_html or source_html)
        front_matter = {
            "requested_url": task.url,
            "final_url": final_url,
            "title": source_metadata.title,
            "meta_description": source_metadata.meta_description,
            "canonical_url": source_metadata.canonical_url,
            "fetched_at": datetime.now(UTC).isoformat(),
            "discovered_from": task.discovered_from,
            "external_hops": task.external_hops,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "conversion_strategy": conversion.conversion_strategy,
            "extraction_mode": self.page_mode,
            "extraction_warning": conversion.extraction_warning,
            "render_mode": self.render_mode,
            "render_attempted": save_result.render_attempted,
            "render_succeeded": save_result.render_succeeded,
            "render_warning": save_result.render_warning,
            "render_source": save_result.render_source,
            "rendered": save_result.rendered,
            "markdown_source": save_result.markdown_source,
            "page_source_used": save_result.page_source_used,
            "runtime_bootstrap_attempted": save_result.runtime_bootstrap_attempted,
            "runtime_bootstrap_succeeded": save_result.runtime_bootstrap_succeeded,
            "runtime_bootstrap_warning": save_result.runtime_bootstrap_warning,
            "source_server_html_saved_to": (
                str(save_result.server_html_path.relative_to(self.output_dir))
                if save_result.server_html_path
                else None
            ),
            "source_rendered_html_saved_to": (
                str(save_result.rendered_html_path.relative_to(self.output_dir))
                if save_result.rendered_html_path
                else None
            ),
        }
        lines = ["---"]
        lines.extend(f"{key}: {json.dumps(value)}" for key, value in front_matter.items())
        lines.append("---\n")
        return lines

    def _save_html(self, path: Path, html: str) -> Path:
        ensure_parent(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        return path

    def _should_attempt_render(
        self,
        html: str,
        conversion: MarkdownConversionResult,
    ) -> tuple[bool, str | None]:
        if self.render_mode == "never":
            return False, None
        if self.render_mode == "always":
            return True, "render_mode_always"
        if conversion.conversion_strategy == "failure_stub":
            return True, "failure_stub"
        if conversion.extraction_warning:
            return True, conversion.extraction_warning
        if visible_text_length(html) <= 40:
            return True, "very_low_visible_text"
        if is_sparse_shell_html(html):
            return True, "client_rendered_shell_detected"
        return False, None

    def _select_html_source(
        self,
        server_html: str,
        server_conversion: MarkdownConversionResult,
        render_result: RenderResult | None,
        final_url: str,
    ) -> tuple[str, MarkdownConversionResult, str, bool, str | None]:
        if not render_result or not render_result.render_succeeded or not render_result.html:
            render_warning = render_result.render_warning if render_result else None
            return server_html, server_conversion, "server_html", False, render_warning
        rendered_conversion = html_to_markdown(render_result.html, final_url, mode=self.page_mode)
        rendered_good = rendered_conversion.conversion_strategy != "failure_stub"
        server_good = server_conversion.conversion_strategy != "failure_stub"
        if self.render_mode == "always":
            source = "rendered_html" if rendered_good or not server_good else "server_html"
        else:
            source = (
                "rendered_html"
                if rendered_good
                and (
                    not server_good
                    or visible_text_length(render_result.html) > visible_text_length(server_html)
                )
                else "server_html"
            )
        if source == "rendered_html":
            return (
                render_result.html,
                rendered_conversion,
                source,
                True,
                render_result.render_warning,
            )
        return server_html, server_conversion, "server_html", False, render_result.render_warning

    def _save_response(
        self,
        task: CrawlTask,
        response: requests.Response,
        kind: str,
    ) -> tuple[SaveResult, str, str | None]:
        final_url = normalize_url(response.url)
        if kind == "html":
            server_html = response.text
            server_conversion = html_to_markdown(server_html, final_url, mode=self.page_mode)
            render_attempted, render_reason = self._should_attempt_render(server_html, server_conversion)
            render_result: RenderResult | None = None
            runtime_status = RuntimeBootstrapStatus(available=False)
            if render_attempted:
                self.render_counts["attempted"] += 1
                runtime_status = self._ensure_renderer_ready(
                    fatal_on_failure=self.render_mode == "always"
                )
                if runtime_status.available and self._renderer is not None:
                    render_result = self._renderer.render_page(final_url)
                elif self.render_mode == "auto":
                    warning_reason = runtime_status.warning or "browser runtime unavailable"
                    render_result = RenderResult(
                        requested_url=final_url,
                        final_url=final_url,
                        html=None,
                        title=None,
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type"),
                        render_succeeded=False,
                        render_warning=warning_reason,
                    )
            selected_html, conversion, markdown_source, rendered_used, render_warning = (
                self._select_html_source(
                    server_html,
                    server_conversion,
                    render_result,
                    render_result.final_url if render_result and render_result.final_url else final_url,
                )
            )
            path = markdown_path(self.output_dir, final_url)
            render_source = "requests"
            if render_attempted and not runtime_status.available:
                render_source = "playwright_bootstrap_failed"
            elif render_attempted and render_result and not render_result.render_succeeded:
                render_source = "playwright_render_failed"
            elif rendered_used:
                render_source = "playwright"
            save_result = SaveResult(
                path=path,
                sha256=None,
                conversion_strategy=conversion.conversion_strategy,
                extraction_mode=self.page_mode,
                extraction_warning=conversion.extraction_warning,
                render_attempted=render_attempted,
                render_succeeded=bool(render_result and render_result.render_succeeded),
                render_warning=render_warning,
                render_source=render_source,
                rendered=rendered_used,
                markdown_source=markdown_source,
                page_source_used=markdown_source,
                runtime_bootstrap_attempted=runtime_status.attempted,
                runtime_bootstrap_succeeded=runtime_status.available,
                runtime_bootstrap_warning=runtime_status.warning,
            )
            if render_attempted:
                if save_result.render_succeeded:
                    self.render_counts["succeeded"] += 1
                else:
                    self.render_counts["failed"] += 1
                if save_result.page_source_used == "server_html":
                    self.render_counts["fell_back_to_server_html"] += 1
            if conversion.conversion_strategy == "failure_stub":
                self.render_counts["failure_stub"] += 1
            if self.save_source_html or conversion.extraction_warning or render_attempted:
                save_result.server_html_path = self._save_html(
                    source_server_html_path(self.output_dir, final_url),
                    server_html,
                )
                save_result.source_html_path = save_result.server_html_path
            if (
                render_result
                and render_result.render_succeeded
                and render_result.html
                and (
                    self.save_rendered_html
                    or render_attempted
                    or rendered_used
                    or conversion.extraction_warning
                )
            ):
                save_result.rendered_html_path = self._save_html(
                    source_rendered_html_path(self.output_dir, final_url),
                    render_result.html,
                )
            lines = self._front_matter_lines(
                task,
                response,
                render_result.final_url if render_result and render_result.final_url else final_url,
                conversion,
                source_html=server_html,
                rendered_html=render_result.html if render_result else None,
                save_result=save_result,
            )
            lines.append(conversion.markdown)
            payload = "\n".join(lines).encode("utf-8")
            link_html = server_html
            if render_result and render_result.render_succeeded and render_result.html:
                link_html = server_html + "\n" + render_result.html
        elif kind == "text":
            filename = final_url.rstrip("/").rsplit("/", 1)[-1] or "document.txt"
            if "." not in filename:
                filename = f"{filename}.txt"
            path = binary_path(self.output_dir, final_url, filename)
            payload = response.content
            save_result = SaveResult(path=path, sha256=None)
            link_html = ""
        else:
            filename = final_url.rstrip("/").rsplit("/", 1)[-1] or "download.bin"
            path = binary_path(self.output_dir, final_url, filename)
            payload = response.content
            save_result = SaveResult(path=path, sha256=None)
            link_html = ""
        ensure_parent(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        save_result.path = path
        save_result.sha256 = sha256_bytes(payload)
        title = extract_page_metadata(response.text).title if kind == "html" else None
        return save_result, link_html, title

    def _extract_links(self, task: CrawlTask, html: str, base_url: str) -> list[CrawlTask]:
        soup = BeautifulSoup(html, "html.parser")
        discovered: list[CrawlTask] = []
        for node in soup.find_all(["a", "area"]):
            href = node.get("href")
            if not href:
                continue
            normalized = normalize_url(urljoin(base_url, href))
            if not normalized:
                continue
            if self.scope.in_root_scope(normalized):
                discovered.append(CrawlTask(normalized, base_url, 0))
                continue
            next_hops = task.external_hops + 1
            if self.scope.allowed(normalized, next_hops, self.external_depth):
                discovered.append(CrawlTask(normalized, base_url, next_hops))
        unique: dict[str, CrawlTask] = {}
        for item in discovered:
            unique.setdefault(item.url, item)
        return list(unique.values())
