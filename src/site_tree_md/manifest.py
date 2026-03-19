from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from site_tree_md.models import CrawlSummary, ManifestRecord
from site_tree_md.utils import ensure_parent


class ManifestWriter:
    def __init__(self, output_dir: Path) -> None:
        self.manifest_path = output_dir / "web" / "_crawl_manifest.jsonl"
        self.failures_path = output_dir / "web" / "_crawl_failures.jsonl"
        self.summary_path = output_dir / "web" / "_crawl_summary.json"

    def append(self, record: ManifestRecord) -> None:
        target = self.failures_path if record.page_kind == "error" else self.manifest_path
        ensure_parent(target)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record.to_json(), ensure_ascii=False) + "\n")

    def write_summary(self, summary: CrawlSummary) -> None:
        ensure_parent(self.summary_path)
        with self.summary_path.open("w", encoding="utf-8") as fh:
            json.dump(asdict(summary), fh, indent=2)
