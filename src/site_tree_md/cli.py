from __future__ import annotations

import argparse
from pathlib import Path

from site_tree_md.crawler import SiteCrawler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Archive a site subtree into a URL-shaped Markdown tree."
    )
    parser.add_argument("url")
    parser.add_argument("--external-depth", type=int, default=1)
    parser.add_argument("--output-dir", default=".")
    parser.add_argument("--max-pages", type=int, default=5000)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument("--same-host-only", action="store_true")
    parser.add_argument("--ignore-robots", action="store_true")
    parser.add_argument("--no-sitemap-seed", action="store_true")
    parser.add_argument("--user-agent", default="site-tree-md/0.1")
    parser.add_argument("--verbose", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full-page", dest="page_mode", action="store_const", const="full-page")
    mode.add_argument(
        "--main-content",
        dest="page_mode",
        action="store_const",
        const="main-content",
    )
    parser.add_argument(
        "--render-mode",
        choices=("never", "auto", "always"),
        default="auto",
        help="Browser rendering strategy for HTML pages.",
    )
    parser.add_argument(
        "--render-js",
        action="store_true",
        help="Backward-compatible alias for --render-mode auto.",
    )
    parser.add_argument("--render-timeout", type=float, default=30.0)
    parser.add_argument(
        "--render-wait-until",
        choices=("load", "domcontentloaded", "networkidle"),
        default="networkidle",
    )
    parser.add_argument("--render-selector")
    parser.add_argument("--render-wait-ms", type=int, default=1200)
    parser.add_argument("--scroll", action="store_true")
    parser.add_argument("--scroll-steps", type=int, default=4)
    parser.add_argument("--scroll-step-px", type=int, default=1200)
    parser.add_argument("--scroll-pause-ms", type=int, default=250)
    parser.add_argument("--show-browser", action="store_true")
    parser.add_argument("--ignore-https-errors", action="store_true")
    parser.set_defaults(page_mode="full-page", save_source_html=False, save_rendered_html=False)
    parser.add_argument(
        "--save-source-html",
        action="store_true",
        help="Save fetched server HTML alongside markdown for every HTML page.",
    )
    parser.add_argument(
        "--save-rendered-html",
        action="store_true",
        help="Save rendered DOM HTML alongside markdown whenever browser rendering succeeds.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    render_mode = "auto" if args.render_js and args.render_mode == "auto" else args.render_mode
    crawler = SiteCrawler(
        seed_url=args.url,
        output_dir=Path(args.output_dir),
        external_depth=args.external_depth,
        delay=args.delay,
        timeout=args.timeout,
        max_pages=args.max_pages,
        no_sitemaps=args.no_sitemap_seed,
        same_host_only=args.same_host_only,
        ignore_robots=args.ignore_robots,
        user_agent=args.user_agent,
        verbose=args.verbose,
        page_mode=args.page_mode,
        save_source_html=args.save_source_html,
        render_mode=render_mode,
        render_timeout=args.render_timeout,
        render_wait_until=args.render_wait_until,
        render_selector=args.render_selector,
        render_wait_ms=args.render_wait_ms,
        scroll=args.scroll,
        scroll_steps=args.scroll_steps,
        scroll_step_px=args.scroll_step_px,
        scroll_pause_ms=args.scroll_pause_ms,
        show_browser=args.show_browser,
        ignore_https_errors=args.ignore_https_errors,
        save_rendered_html=args.save_rendered_html,
    )
    summary = crawler.crawl()
    crawler.manifest.write_summary(summary)
    return 0
