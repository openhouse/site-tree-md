from pathlib import Path

from site_tree_md.paths import binary_path, markdown_path


def test_markdown_path_root() -> None:
    path = markdown_path(Path("."), "https://smallbizunited.com/")
    assert path.as_posix() == "web/https:/smallbizunited.com/smallbizunited-com.md"


def test_markdown_path_query() -> None:
    path = markdown_path(Path("."), "https://a860-gpp.nyc.gov/concern/item?locale=en")
    assert path.as_posix() == (
        "web/https:/a860-gpp.nyc.gov/concern/item?locale=en/a860-gpp-nyc-gov.md"
    )


def test_binary_path() -> None:
    path = binary_path(Path("."), "https://example.com/files/report.pdf", "report.pdf")
    assert path.as_posix() == "web/https:/example.com/files/report.pdf/report.pdf"
