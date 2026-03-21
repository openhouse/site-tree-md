from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CrawlTask:
    url: str
    discovered_from: str | None
    external_hops: int = 0
    via_sitemap: bool = False


@dataclass(slots=True)
class FetchResult:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    text: str | None
    content: bytes
    title: str | None


@dataclass(slots=True)
class ManifestRecord:
    requested_url: str
    final_url: str | None
    status_code: int | None
    content_type: str | None
    saved_to: str | None
    page_kind: str
    title: str | None
    discovered_from: str | None
    external_hops: int
    error: str | None = None
    fetched_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    sha256: str | None = None
    conversion_strategy: str | None = None
    extraction_mode: str | None = None
    extraction_warning: str | None = None
    source_html_saved_to: str | None = None
    render_mode: str | None = None
    render_attempted: bool = False
    render_succeeded: bool = False
    render_warning: str | None = None
    render_source: str | None = None
    rendered: bool = False
    markdown_source: str | None = None
    page_source_used: str | None = None
    source_server_html_saved_to: str | None = None
    source_rendered_html_saved_to: str | None = None
    render_wait_until: str | None = None
    render_selector: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CrawlSummary:
    seed_url: str
    scope_prefix: str
    external_hop_depth: int
    output_root: str
    generated_at: str
    fetched_pages: int
    counts_by_kind: dict[str, int]


@dataclass(slots=True)
class SaveResult:
    path: Path
    sha256: str | None
    conversion_strategy: str | None = None
    extraction_mode: str | None = None
    extraction_warning: str | None = None
    source_html_path: Path | None = None
    server_html_path: Path | None = None
    rendered_html_path: Path | None = None
    render_attempted: bool = False
    render_succeeded: bool = False
    render_warning: str | None = None
    render_source: str | None = None
    rendered: bool = False
    markdown_source: str | None = None
    page_source_used: str | None = None
