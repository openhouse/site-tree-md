from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from site_tree_md.utils import host_slug, safe_segment

HTML_LIKE_SUFFIXES = {"", ".html", ".htm", ".xhtml", ".php", ".asp", ".aspx"}
DOCUMENT_SUFFIXES = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".tsv",
    ".zip",
    ".ppt",
    ".pptx",
    ".rtf",
    ".epub",
    ".odt",
    ".ods",
}
TEXT_SUFFIXES = {".txt", ".json", ".xml", ".yml", ".yaml"}


def _safe_leaf(segment: str) -> str:
    return safe_segment(segment, preserve={"?", "="})


def _url_dir_parts(url: str) -> list[str]:
    split = urlsplit(url)
    parts = [f"{split.scheme}:", split.netloc]
    path_segments = [segment for segment in split.path.split("/") if segment]
    if path_segments:
        parts.extend(path_segments)
    if split.query:
        if path_segments:
            parts[-1] = f"{parts[-1]}?{split.query}"
        else:
            parts.append(f"_root?{split.query}")
    result = [parts[0], safe_segment(parts[1])]
    result.extend(_safe_leaf(part) for part in parts[2:])
    return result


def url_directory(output_dir: Path, url: str) -> Path:
    return output_dir.joinpath("web", *_url_dir_parts(url))


def markdown_path(output_dir: Path, url: str) -> Path:
    split = urlsplit(url)
    return url_directory(output_dir, url) / f"{host_slug(split.hostname or 'site')}.md"


def binary_path(output_dir: Path, url: str, filename: str) -> Path:
    return url_directory(output_dir, url) / safe_segment(filename)


def _html_sidecar_path(output_dir: Path, url: str, suffix: str) -> Path:
    split = urlsplit(url)
    return url_directory(output_dir, url) / f"{host_slug(split.hostname or 'site')}.{suffix}.html"


def source_html_path(output_dir: Path, url: str) -> Path:
    return source_server_html_path(output_dir, url)


def source_server_html_path(output_dir: Path, url: str) -> Path:
    return _html_sidecar_path(output_dir, url, "source.server")


def source_rendered_html_path(output_dir: Path, url: str) -> Path:
    return _html_sidecar_path(output_dir, url, "source.rendered")


def classify_content(url: str, content_type: str) -> str:
    ctype = (content_type or "").lower()
    if "html" in ctype or "xhtml" in ctype:
        return "html"
    if ctype.startswith("text/") or any(token in ctype for token in ("json", "xml", "yaml")):
        return "text"
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix in DOCUMENT_SUFFIXES:
        return "binary"
    if suffix in TEXT_SUFFIXES:
        return "text"
    if suffix in HTML_LIKE_SUFFIXES:
        return "html"
    return "binary"
