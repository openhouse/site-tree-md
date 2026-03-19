from site_tree_md.scope import CrawlScope


def test_root_seed_scope_includes_whole_host() -> None:
    scope = CrawlScope("https://example.com/")
    assert scope.in_root_scope("https://example.com/docs/")
    assert not scope.in_root_scope("https://other.com/docs/")


def test_subsection_scope_only_includes_subtree() -> None:
    scope = CrawlScope("https://example.com/docs/")
    assert scope.in_root_scope("https://example.com/docs/page")
    assert not scope.in_root_scope("https://example.com/blog/")


def test_external_depth_logic() -> None:
    scope = CrawlScope("https://example.com/docs/")
    assert scope.allowed("https://other.com/page", 1, 1)
    assert not scope.allowed("https://other.com/page", 2, 1)
