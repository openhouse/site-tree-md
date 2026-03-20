from __future__ import annotations

from site_tree_md import markdown as markdown_module
from site_tree_md.markdown import (
    absolutize_links,
    extract_embedded_app_text,
    full_page_html_to_markdown,
    html_to_markdown,
    is_thin_markdown,
    visible_text_length,
)


def test_absolutize_links_uses_base_href() -> None:
    html = """
    <html><head><base href="https://example.com/base/"></head><body>
      <a href="docs/page.html">Docs</a>
      <img src="images/logo.png" alt="Logo" />
    </body></html>
    """
    normalized = absolutize_links(html, "https://example.com/start/")
    assert 'href="https://example.com/base/docs/page.html"' in normalized
    assert 'src="https://example.com/base/images/logo.png"' in normalized


def test_title_only_trafilatura_output_falls_back(monkeypatch) -> None:
    html = """
    <html><head><title>Small Business United</title></head>
    <body>
      <header><nav><a href="/why">Why we exist</a></nav></header>
      <main><p>We organize neighborhood merchants around city policy.</p>
      <p>Join the coalition to protect storefront businesses.</p></main>
      <footer><p>Footer contact text.</p></footer>
    </body></html>
    """

    monkeypatch.setattr(
        markdown_module.trafilatura, "extract", lambda *args, **kwargs: "Small Business United"
    )

    result = html_to_markdown(html, "https://example.com/", mode="main-content")

    assert result.conversion_strategy == "full_page_fallback"
    assert "Join the coalition" in result.markdown
    assert "Footer contact text" in result.markdown
    assert result.markdown.strip() != "Small Business United"


def test_full_page_mode_keeps_more_than_main_content(monkeypatch) -> None:
    html = """
    <html><head><title>Shared Title</title></head>
    <body>
      <header><p>Header alert</p></header>
      <nav><a href="/stories">Stories</a></nav>
      <main><h1>Welcome</h1><p>Main section body.</p></main>
      <footer><p>Footer CTA</p></footer>
    </body></html>
    """

    extracted_markdown = (
        "# Welcome\n\nMain section body with practical campaign details and member stories."
        "\n\nAction steps are listed for neighborhood merchants."
    )
    monkeypatch.setattr(
        markdown_module.trafilatura,
        "extract",
        lambda *args, **kwargs: extracted_markdown,
    )

    full_page = html_to_markdown(html, "https://example.com/")
    main_content = html_to_markdown(html, "https://example.com/", mode="main-content")

    assert "Header alert" in full_page.markdown
    assert "Stories" in full_page.markdown
    assert "Footer CTA" in full_page.markdown
    assert "Header alert" not in main_content.markdown


def test_full_page_conversion_removes_scripts_and_preserves_sections() -> None:
    html = """
    <html><head><title>Page</title><style>.x{display:none}</style></head>
    <body>
      <header><p>Header text</p></header>
      <script>console.log('noise')</script>
      <main><p>Body text</p><button>Join the coalition</button></main>
      <footer><p>Footer text</p></footer>
    </body></html>
    """
    markdown = full_page_html_to_markdown(html, "https://example.com/")
    assert "console.log" not in markdown
    assert ".x" not in markdown
    assert "Header text" in markdown
    assert "Body text" in markdown
    assert "[button: Join the coalition]" in markdown
    assert "Footer text" in markdown


def test_embedded_json_text_recovery_when_dom_is_thin() -> None:
    html = """
    <html><head><title>Shared Title</title></head>
    <body><div id="app"></div>
    <script id="__NEXT_DATA__" type="application/json">
    {"props":{"pageProps":{"sections":[
      {"heading":"Protect NYC storefronts now"},
      {"body":"Coalition members get updates about hearings and grants."},
      {"cta":"Join neighborhood businesses today for practical support."}
    ]}}}
    </script>
    </body></html>
    """
    embedded = extract_embedded_app_text(html)
    assert "Embedded app data" in embedded
    assert "Protect NYC storefronts now" in embedded
    assert "Coalition members get updates" in embedded


def test_is_thin_markdown_detects_title_only_output() -> None:
    html = (
        "<html><head><title>Shared Title</title></head><body><p>"
        + ("words " * 80)
        + "</p></body></html>"
    )
    visible_len = visible_text_length(html)
    assert is_thin_markdown("# Shared Title", "Shared Title", visible_len)
    rich_markdown = (
        "# Shared Title\n\nDetailed body text with many more words present across several "
        "sentences. Neighborhood merchants need policy updates, grant guidance, "
        "and coalition alerts. This richer body should not be treated as title-only "
        "output."
    )
    assert not is_thin_markdown(rich_markdown, "Shared Title", visible_len)
