from __future__ import annotations

import gzip
from io import BytesIO
from urllib.parse import urljoin
from xml.etree import ElementTree

from requests import Session

from site_tree_md.utils import normalize_url

COMMON_SITEMAPS = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml", "/wp-sitemap.xml"]


def robots_sitemaps(base_url: str, session: Session, timeout: float) -> list[str]:
    robots_url = urljoin(base_url, "/robots.txt")
    try:
        response = session.get(robots_url, timeout=timeout)
        response.raise_for_status()
    except Exception:
        return []
    found = []
    for line in response.text.splitlines():
        if line.lower().startswith("sitemap:"):
            found.append(normalize_url(line.split(":", 1)[1].strip()))
    return [url for url in found if url]


def parse_sitemap_bytes(content: bytes) -> list[str]:
    if content[:2] == b"\x1f\x8b":
        content = gzip.GzipFile(fileobj=BytesIO(content)).read()
    text = content.decode("utf-8", errors="ignore").strip()
    if not text:
        return []
    if text.startswith("http"):
        return [normalize_url(line.strip()) for line in text.splitlines() if line.strip()]
    root = ElementTree.fromstring(text)
    ns = {"sm": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
    locs = (
        [elem.text.strip() for elem in root.findall(".//sm:loc", ns) if elem.text]
        if ns
        else [elem.text.strip() for elem in root.findall(".//loc") if elem.text]
    )
    return [normalize_url(loc) for loc in locs if loc]


def discover_sitemaps(base_url: str, session: Session, timeout: float) -> list[str]:
    candidates = robots_sitemaps(base_url, session, timeout)
    candidates.extend(normalize_url(urljoin(base_url, path)) for path in COMMON_SITEMAPS)
    deduped = []
    seen = set()
    for candidate in candidates:
        if candidate and candidate not in seen:
            deduped.append(candidate)
            seen.add(candidate)
    return deduped
