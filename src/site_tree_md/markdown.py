from __future__ import annotations

import trafilatura
from bs4 import BeautifulSoup
from markdownify import markdownify as md


def extract_title(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    return h1.get_text(" ", strip=True) if h1 else None


def html_to_markdown(html: str, url: str) -> str:
    extracted = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=True,
        include_tables=True,
        include_images=True,
        favor_precision=True,
        deduplicate=True,
    )
    if extracted and extracted.strip():
        return extracted.strip()
    soup = BeautifulSoup(html, "html.parser")
    for selector in ("nav", "footer", "script", "style", "noscript"):
        for node in soup.select(selector):
            node.decompose()
    main = soup.find("main") or soup.body or soup
    rendered = md(str(main), heading_style="ATX")
    return rendered.strip() or soup.get_text("\n", strip=True)
