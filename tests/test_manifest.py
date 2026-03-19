import json
from datetime import UTC, datetime

from site_tree_md.manifest import ManifestWriter
from site_tree_md.models import CrawlSummary, ManifestRecord


def test_manifest_and_summary_written(tmp_path) -> None:
    writer = ManifestWriter(tmp_path)
    writer.append(
        ManifestRecord(
            requested_url="https://example.com",
            final_url="https://example.com/",
            status_code=200,
            content_type="text/html",
            saved_to="web/https:/example.com/example-com.md",
            page_kind="html",
            title="Example",
            discovered_from=None,
            external_hops=0,
        )
    )
    writer.write_summary(
        CrawlSummary(
            seed_url="https://example.com/",
            scope_prefix="/",
            external_hop_depth=1,
            output_root="/tmp/web",
            generated_at=datetime.now(UTC).isoformat(),
            fetched_pages=1,
            counts_by_kind={"html": 1},
        )
    )
    assert writer.manifest_path.exists()
    summary = json.loads(writer.summary_path.read_text())
    assert summary["fetched_pages"] == 1
