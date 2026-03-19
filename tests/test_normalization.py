from site_tree_md.utils import normalize_url


def test_normalize_url_strips_tracking_and_fragment() -> None:
    assert (
        normalize_url("HTTPS://Example.com:443/path//to/?utm_source=x&b=2&a=1#frag")
        == "https://example.com/path/to/?a=1&b=2"
    )
