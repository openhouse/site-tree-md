from __future__ import annotations

import json
import time
from collections import Counter, deque
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from site_tree_md.manifest import ManifestWriter
from site_tree_md.markdown import MarkdownConversionResult, extract_title, html_to_markdown
from site_tree_md.models import CrawlSummary, CrawlTask, ManifestRecord, SaveResult
from site_tree_md.paths import binary_path, classify_content, markdown_path, source_html_path
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
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.manifest = ManifestWriter(output_dir)
        self.robots = RobotsCache(self.session, timeout, user_agent)
        self.counts = Counter()

    def crawl(self) -> CrawlSummary:
        queue = deque([CrawlTask(self.seed_url, None, 0)])
        seen = set()
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
                save_result = self._save_response(task, response, kind)
                title = extract_title(response.text) if kind == "html" else None
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
                    )
                )
                if self.verbose:
                    if kind == "html":
                        print(
                            f"saved [{kind}] {final_url} -> {save_result.path} "
                            f"(conversion={save_result.conversion_strategy})"
                        )
                    else:
                        print(f"saved [{kind}] {final_url} -> {save_result.path}")
                if kind == "html":
                    for next_task in self._extract_links(task, response.text, final_url):
                        if next_task.url not in seen:
                            queue.append(next_task)
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
                    )
                )
        return CrawlSummary(
            seed_url=self.seed_url,
            scope_prefix=self.scope.seed_path,
            external_hop_depth=self.external_depth,
            output_root=str((self.output_dir / "web").resolve()),
            generated_at=datetime.now(UTC).isoformat(),
            fetched_pages=sum(self.counts.values()),
            counts_by_kind=dict(self.counts),
        )

    def _front_matter_lines(
        self,
        task: CrawlTask,
        response: requests.Response,
        final_url: str,
        conversion: MarkdownConversionResult,
    ) -> list[str]:
        front_matter = {
            "requested_url": task.url,
            "final_url": final_url,
            "title": extract_title(response.text),
            "fetched_at": datetime.now(UTC).isoformat(),
            "discovered_from": task.discovered_from,
            "external_hops": task.external_hops,
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "conversion_strategy": conversion.conversion_strategy,
            "extraction_mode": self.page_mode,
            "extraction_warning": conversion.extraction_warning,
        }
        lines = ["---"]
        lines.extend(f"{key}: {json.dumps(value)}" for key, value in front_matter.items())
        lines.append("---\n")
        return lines

    def _save_html_source(self, final_url: str, html: str) -> Path:
        path = source_html_path(self.output_dir, final_url)
        ensure_parent(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
        return path

    def _save_response(self, task: CrawlTask, response: requests.Response, kind: str) -> SaveResult:
        final_url = normalize_url(response.url)
        if kind == "html":
            conversion = html_to_markdown(response.text, final_url, mode=self.page_mode)
            path = markdown_path(self.output_dir, final_url)
            lines = self._front_matter_lines(task, response, final_url, conversion)
            lines.append(conversion.markdown)
            payload = "\n".join(lines).encode("utf-8")
            html_sidecar: Path | None = None
            if self.save_source_html or conversion.extraction_warning:
                html_sidecar = self._save_html_source(final_url, response.text)
        elif kind == "text":
            filename = final_url.rstrip("/").rsplit("/", 1)[-1] or "document.txt"
            if "." not in filename:
                filename = f"{filename}.txt"
            path = binary_path(self.output_dir, final_url, filename)
            payload = response.content
            conversion = MarkdownConversionResult(markdown="", conversion_strategy=None)
            html_sidecar = None
        else:
            filename = final_url.rstrip("/").rsplit("/", 1)[-1] or "download.bin"
            path = binary_path(self.output_dir, final_url, filename)
            payload = response.content
            conversion = MarkdownConversionResult(markdown="", conversion_strategy=None)
            html_sidecar = None
        ensure_parent(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return SaveResult(
            path=path,
            sha256=sha256_bytes(payload),
            conversion_strategy=conversion.conversion_strategy,
            extraction_mode=self.page_mode if kind == "html" else None,
            extraction_warning=conversion.extraction_warning,
            source_html_path=html_sidecar,
        )

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
