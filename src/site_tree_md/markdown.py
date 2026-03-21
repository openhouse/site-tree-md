from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import trafilatura
from bs4 import BeautifulSoup, Tag
from markdownify import MarkdownConverter

THIN_CHAR_THRESHOLD = 80
SUBSTANTIAL_VISIBLE_TEXT_THRESHOLD = 300
THIN_RATIO_DENOMINATOR = 5
MEANINGFUL_BLOCK_THRESHOLD = 2
EMBEDDED_TEXT_MIN_CHARS = 120
SPARSE_VISIBLE_TEXT_THRESHOLD = 60
SPARSE_ROOT_IDS = {"root", "app", "__next", "__nuxt", "app-root"}
IGNORED_EMBEDDED_KEYS = {
    "id",
    "_id",
    "url",
    "href",
    "src",
    "image",
    "images",
    "slug",
    "class",
    "classname",
    "hash",
    "type",
    "__typename",
}


@dataclass(slots=True)
class PageMetadata:
    title: str | None
    meta_description: str | None = None
    og_description: str | None = None
    canonical_url: str | None = None


@dataclass(slots=True)
class MarkdownConversionResult:
    markdown: str
    conversion_strategy: str
    extraction_warning: str | None = None


class FullPageMarkdownConverter(MarkdownConverter):
    def convert_form(self, el: Tag, text: str, parent_tags: dict[str, Any]) -> str:  # noqa: ARG002
        return f"\n{text}\n" if text.strip() else ""

    def convert_input(self, el: Tag, text: str, parent_tags: dict[str, Any]) -> str:  # noqa: ARG002
        input_type = (el.get("type") or "text").strip().lower()
        if input_type in {"hidden", "submit", "reset", "image"}:
            return ""
        label = el.get("placeholder") or el.get("aria-label") or el.get("name") or el.get("value")
        if input_type == "checkbox":
            return "[checkbox]"
        if input_type == "radio":
            return "[radio]"
        suffix = f": {label.strip()}" if isinstance(label, str) and label.strip() else ""
        return f"[input{suffix}]"

    def convert_button(self, el: Tag, text: str, parent_tags: dict[str, Any]) -> str:  # noqa: ARG002
        label = _normalize_whitespace(text or el.get_text(" ", strip=True))
        return f"[button: {label}]" if label else "[button]"

    def convert_label(self, el: Tag, text: str, parent_tags: dict[str, Any]) -> str:  # noqa: ARG002
        label = _normalize_whitespace(text or el.get_text(" ", strip=True))
        return f"{label}: " if label else ""

    def convert_textarea(self, el: Tag, text: str, parent_tags: dict[str, Any]) -> str:  # noqa: ARG002
        label = el.get("placeholder") or el.get("aria-label") or el.get("name")
        suffix = f": {label.strip()}" if isinstance(label, str) and label.strip() else ""
        return f"[textarea{suffix}]"

    def convert_select(self, el: Tag, text: str, parent_tags: dict[str, Any]) -> str:  # noqa: ARG002
        label = el.get("aria-label") or el.get("name")
        suffix = f": {label.strip()}" if isinstance(label, str) and label.strip() else ""
        return f"[select{suffix}]"


def _normalize_whitespace(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _normalize_markdown_text(text: str | None) -> str:
    normalized = _normalize_whitespace(text)
    normalized = re.sub(r"^[#>*\-\s`_~]+", "", normalized)
    normalized = re.sub(r"[#>*`_~]+$", "", normalized)
    normalized = re.sub(r"[^\w\s]", "", normalized)
    return normalized.casefold().strip()


def _markdown_body(markdown: str) -> str:
    stripped = markdown.strip()
    if stripped.startswith("---\n"):
        parts = stripped.split("\n---\n", 1)
        if len(parts) == 2:
            return parts[1].strip()
    return stripped


def _meaningful_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _meta_content(
    soup: BeautifulSoup, *, name: str | None = None, prop: str | None = None
) -> str | None:
    attrs = {}
    if name:
        attrs["name"] = name
    if prop:
        attrs["property"] = prop
    node = soup.find("meta", attrs=attrs)
    if node and node.get("content"):
        return node["content"].strip() or None
    return None


def extract_page_metadata(html: str) -> PageMetadata:
    soup = BeautifulSoup(html, "html.parser")
    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip() or None
    if title is None:
        h1 = soup.find("h1")
        title = h1.get_text(" ", strip=True) if h1 else None
    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    canonical_url = canonical.get("href", "").strip() or None if canonical else None
    return PageMetadata(
        title=title,
        meta_description=_meta_content(soup, name="description"),
        og_description=_meta_content(soup, prop="og:description"),
        canonical_url=canonical_url,
    )


def extract_title(html: str) -> str | None:
    return extract_page_metadata(html).title


def absolutize_links(html: str, page_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    base_url = page_url
    base_tag = soup.find("base", href=True)
    if base_tag and base_tag.get("href"):
        base_url = urljoin(page_url, base_tag["href"])
    for tag_name, attr in (("a", "href"), ("img", "src"), ("source", "src"), ("source", "srcset")):
        for node in soup.find_all(tag_name):
            value = node.get(attr)
            if not value:
                continue
            if attr == "srcset":
                candidates = []
                for item in value.split(","):
                    parts = item.strip().split()
                    if not parts:
                        continue
                    parts[0] = urljoin(base_url, parts[0])
                    candidates.append(" ".join(parts))
                node[attr] = ", ".join(candidates)
            else:
                node[attr] = urljoin(base_url, value)
    return str(soup)


def clean_html_for_full_page_markdown(html: str, page_url: str) -> str:
    soup = BeautifulSoup(absolutize_links(html, page_url), "html.parser")
    for selector in ("script", "style", "noscript", "template", "meta"):
        for node in soup.select(selector):
            node.decompose()
    for link_node in soup.find_all("link"):
        rel_values = {value.lower() for value in link_node.get("rel", [])}
        if rel_values & {
            "preload",
            "prefetch",
            "modulepreload",
            "dns-prefetch",
            "preconnect",
            "icon",
            "manifest",
        }:
            link_node.decompose()
    for node in soup.find_all(["svg", "canvas"]):
        aria_label = _normalize_whitespace(node.get("aria-label"))
        title_text = _normalize_whitespace(node.get_text(" ", strip=True))
        replacement = aria_label or title_text
        if replacement:
            node.replace_with(soup.new_string(replacement))
        else:
            node.decompose()
    return str(soup.body or soup)


def visible_text_length(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    for selector in ("script", "style", "noscript", "template"):
        for node in soup.select(selector):
            node.decompose()
    return len(_normalize_whitespace((soup.body or soup).get_text(" ", strip=True)))


def full_page_html_to_markdown(html: str, page_url: str) -> str:
    cleaned_html = clean_html_for_full_page_markdown(html, page_url)
    rendered = FullPageMarkdownConverter(
        heading_style="ATX",
        bullets="-",
        newline_style="BACKSLASH",
        strip=["base"],
        escape_underscores=False,
        escape_asterisks=False,
    ).convert(cleaned_html)
    normalized_lines = [line.rstrip() for line in rendered.splitlines()]
    normalized = "\n".join(normalized_lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def main_content_html_to_markdown(html: str, page_url: str) -> str:
    extracted = trafilatura.extract(
        html,
        url=page_url,
        output_format="markdown",
        include_links=True,
        include_tables=True,
        include_images=True,
        favor_precision=True,
        deduplicate=True,
    )
    return (extracted or "").strip()


def _looks_human_readable(text: str) -> bool:
    normalized = _normalize_whitespace(text)
    if len(normalized) < 24:
        return False
    if normalized.startswith(("http://", "https://")):
        return False
    alpha_count = sum(char.isalpha() for char in normalized)
    digit_count = sum(char.isdigit() for char in normalized)
    if alpha_count < 12 or digit_count > alpha_count:
        return False
    lower = normalized.casefold()
    if lower in {"true", "false", "null", "undefined"}:
        return False
    return True


def _collect_embedded_strings(
    value: Any, seen: set[str], output: list[str], key: str | None = None
) -> None:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            _collect_embedded_strings(child_value, seen, output, child_key)
        return
    if isinstance(value, list):
        for item in value:
            _collect_embedded_strings(item, seen, output, key)
        return
    if not isinstance(value, str):
        return
    if key and key.casefold() in IGNORED_EMBEDDED_KEYS:
        return
    normalized = _normalize_whitespace(value)
    if not _looks_human_readable(normalized):
        return
    canonical = normalized.casefold()
    if canonical in seen:
        return
    seen.add(canonical)
    output.append(normalized)


def extract_embedded_app_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    collected: list[str] = []
    seen: set[str] = set()
    script_nodes = soup.find_all("script")
    for node in script_nodes:
        script_type = (node.get("type") or "").lower()
        script_text = node.string or node.get_text("\n", strip=True)
        if not script_text:
            continue
        candidates: list[str] = []
        if script_type in {"application/ld+json", "application/json"}:
            candidates.append(script_text)
        if node.get("id") == "__NEXT_DATA__":
            candidates.append(script_text)
        for marker in ("__NUXT__=", "window.__INITIAL_STATE__=", "window.__APOLLO_STATE__="):
            if marker in script_text:
                candidates.append(script_text.split(marker, 1)[1].strip().rstrip(";"))
        for raw in candidates:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                continue
            _collect_embedded_strings(parsed, seen, collected)
    if not collected:
        return ""
    markdown = "## Embedded app data\n\n" + "\n".join(f"- {item}" for item in collected[:40])
    return markdown if len(_markdown_body(markdown)) >= EMBEDDED_TEXT_MIN_CHARS else ""


def _fallback_body_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for selector in ("script", "style", "noscript", "template"):
        for node in soup.select(selector):
            node.decompose()
    blocks: list[str] = []
    for node in (soup.body or soup).find_all(
        ["h1", "h2", "h3", "p", "li", "td", "th", "button", "label"]
    ):
        text = _normalize_whitespace(node.get_text(" ", strip=True))
        if text and text not in blocks:
            blocks.append(text)
    return "\n\n".join(blocks).strip() or _normalize_whitespace(
        (soup.body or soup).get_text("\n", strip=True)
    )


def is_thin_markdown(markdown: str, title: str | None, visible_len: int) -> bool:
    body = _markdown_body(markdown)
    normalized_body = _normalize_markdown_text(body)
    normalized_title = _normalize_markdown_text(title)
    if not normalized_body:
        return True
    if normalized_title and normalized_body == normalized_title:
        return True
    lines = _meaningful_lines(body)
    if len(lines) <= 1 and len(normalized_body) < THIN_CHAR_THRESHOLD:
        return True
    if len(lines) < MEANINGFUL_BLOCK_THRESHOLD and len(normalized_body) < THIN_CHAR_THRESHOLD:
        return True
    if (
        normalized_title
        and len(lines) == 1
        and _normalize_markdown_text(lines[0]) == normalized_title
    ):
        return True
    if (
        visible_len > SUBSTANTIAL_VISIBLE_TEXT_THRESHOLD
        and len(normalized_body) * THIN_RATIO_DENOMINATOR < visible_len
    ):
        return True
    unique_words = {word for word in re.findall(r"\b\w+\b", normalized_body) if len(word) > 2}
    return len(unique_words) < 8 and len(normalized_body) < max(
        THIN_CHAR_THRESHOLD, visible_len // 4
    )


def is_sparse_shell_html(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.body or soup
    visible_len = visible_text_length(html)
    root_like = False
    meaningful_children = 0
    for child in body.find_all(recursive=False):
        if not isinstance(child, Tag):
            continue
        child_text = _normalize_whitespace(child.get_text(" ", strip=True))
        if child.name in {"script", "style", "noscript", "template"}:
            continue
        if (
            child.name == "div"
            and (child.get("id") or "").lower() in SPARSE_ROOT_IDS
            and not child_text
        ):
            root_like = True
            continue
        if child_text:
            meaningful_children += 1
        elif child.name not in {"script", "style", "noscript", "template"}:
            meaningful_children += 1
    script_markers = any(
        script.get("src") or "import(" in script.get_text(" ", strip=True)
        for script in soup.find_all("script")
    )
    embedded = extract_embedded_app_text(html)
    return bool(
        visible_len <= SPARSE_VISIBLE_TEXT_THRESHOLD
        and root_like
        and meaningful_children <= 1
        and script_markers
        and not embedded
    )


def _failure_stub(url: str, metadata: PageMetadata, warning: str) -> str:
    lines = [f"> Warning: extracted HTML for {url} remains too sparse for rich markdown."]
    lines.append("")
    lines.append(f"- Title: {metadata.title or 'Untitled page'}")
    if metadata.meta_description:
        lines.append(f"- Meta description: {metadata.meta_description}")
    if metadata.og_description and metadata.og_description != metadata.meta_description:
        lines.append(f"- OG description: {metadata.og_description}")
    if metadata.canonical_url:
        lines.append(f"- Canonical URL: {metadata.canonical_url}")
    lines.append(f"- Warning: {warning}")
    return "\n".join(lines)


def html_to_markdown(html: str, url: str, mode: str = "full-page") -> MarkdownConversionResult:
    metadata = extract_page_metadata(html)
    title = metadata.title
    visible_len = visible_text_length(html)
    shell_detected = is_sparse_shell_html(html)

    if mode == "main-content":
        markdown = main_content_html_to_markdown(html, url)
        if not is_thin_markdown(markdown, title, visible_len):
            return MarkdownConversionResult(markdown=markdown, conversion_strategy="main_content")
        full_page = full_page_html_to_markdown(html, url)
        warning = "thin_main_content_detected"
        if not is_thin_markdown(full_page, title, visible_len):
            return MarkdownConversionResult(
                markdown=full_page,
                conversion_strategy="full_page_fallback",
                extraction_warning=warning,
            )
        fallback = _fallback_body_text(html)
        if not is_thin_markdown(fallback, title, visible_len):
            return MarkdownConversionResult(
                markdown=fallback,
                conversion_strategy="text_fallback",
                extraction_warning=warning,
            )
        final_warning = "client_rendered_shell_detected" if shell_detected else warning
        return MarkdownConversionResult(
            markdown=_failure_stub(url, metadata, final_warning),
            conversion_strategy="failure_stub",
            extraction_warning=final_warning,
        )

    full_page = full_page_html_to_markdown(html, url)
    if not is_thin_markdown(full_page, title, visible_len):
        return MarkdownConversionResult(markdown=full_page, conversion_strategy="full_page")

    embedded = extract_embedded_app_text(html)
    if embedded:
        merged = full_page.strip()
        if merged:
            merged = f"{merged}\n\n{embedded}".strip()
        else:
            merged = embedded
        if not is_thin_markdown(merged, title, visible_len):
            return MarkdownConversionResult(
                markdown=merged,
                conversion_strategy="full_page_with_embedded_data",
                extraction_warning="thin_full_page_detected",
            )

    fallback = _fallback_body_text(html)
    if not is_thin_markdown(fallback, title, visible_len):
        return MarkdownConversionResult(
            markdown=fallback,
            conversion_strategy="text_fallback",
            extraction_warning="thin_full_page_detected",
        )

    warning = (
        "client_rendered_shell_detected"
        if shell_detected
        else "fetched_html_too_sparse_for_markdown"
    )
    return MarkdownConversionResult(
        markdown=_failure_stub(url, metadata, warning),
        conversion_strategy="failure_stub",
        extraction_warning=warning,
    )
