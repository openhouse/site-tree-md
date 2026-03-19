from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

import tldextract

from site_tree_md.utils import looks_like_file_path, normalize_url


@dataclass(slots=True)
class CrawlScope:
    seed_url: str
    same_host_only: bool = False
    scheme: str = field(init=False)
    host: str = field(init=False)
    seed_path: str = field(init=False)
    seed_query: str = field(init=False)
    seed_is_exact: bool = field(init=False)
    registered_domain: str = field(init=False)

    def __post_init__(self) -> None:
        self.seed_url = normalize_url(self.seed_url)
        split = urlsplit(self.seed_url)
        self.scheme = split.scheme
        self.host = split.hostname or ""
        self.seed_path = split.path or "/"
        self.seed_query = split.query
        self.seed_is_exact = bool(self.seed_query) or looks_like_file_path(self.seed_path)
        extracted = tldextract.extract(self.host)
        self.registered_domain = extracted.top_domain_under_public_suffix or self.host

    def is_internal(self, url: str) -> bool:
        split = urlsplit(normalize_url(url))
        host = split.hostname or ""
        if self.same_host_only:
            return host == self.host
        extracted = tldextract.extract(host)
        return (extracted.top_domain_under_public_suffix or host) == self.registered_domain

    def in_root_scope(self, url: str) -> bool:
        normalized = normalize_url(url)
        split = urlsplit(normalized)
        if split.hostname != self.host:
            return False
        if self.seed_is_exact:
            return normalized == self.seed_url
        if self.seed_path == "/":
            return True
        seed = self.seed_path if self.seed_path.endswith("/") else f"{self.seed_path}/"
        return split.path == self.seed_path or split.path.startswith(seed)

    def allowed(self, url: str, external_hops: int, max_external_hops: int) -> bool:
        normalized = normalize_url(url)
        if not normalized:
            return False
        if self.in_root_scope(normalized):
            return True
        if self.is_internal(normalized):
            return False
        return external_hops <= max_external_hops
