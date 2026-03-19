from __future__ import annotations

import hashlib
import posixpath
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAM_RE = re.compile(
    r"^(utm_[^=]+|fbclid|gclid|mc_cid|mc_eid|_hsenc|_hsmi|mkt_tok|igshid|ref_src)$",
    re.IGNORECASE,
)
SKIP_SCHEMES = {"mailto", "tel", "javascript", "data", "blob"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def host_slug(host: str) -> str:
    return host.replace(".", "-")


def clean_query(query: str) -> str:
    items = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        if TRACKING_PARAM_RE.match(key):
            continue
        items.append((key, value))
    items.sort()
    return urlencode(items, doseq=True)


def normalize_url(url: str) -> str:
    split = urlsplit(url)
    if split.scheme.lower() in SKIP_SCHEMES:
        return ""
    scheme = split.scheme.lower() or "https"
    host = split.hostname.lower() if split.hostname else ""
    port = split.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", split.path or "/")
    if not path.startswith("/"):
        path = f"/{path}"
    path = posixpath.normpath(path)
    if split.path.endswith("/") and not path.endswith("/"):
        path = f"{path}/"
    if path == ".":
        path = "/"
    query = clean_query(split.query)
    return urlunsplit((scheme, netloc, path, query, ""))


def looks_like_file_path(path: str) -> bool:
    leaf = path.rstrip("/").rsplit("/", 1)[-1]
    return "." in leaf and not leaf.startswith(".")


def safe_segment(segment: str, preserve: set[str] | None = None) -> str:
    preserve = preserve or set()
    pattern = "".join(ch for ch in '<>:"\\|?*' if ch not in preserve)
    sanitized = re.sub(rf"[{re.escape(pattern)}\x00-\x1f]", "_", segment)
    return sanitized or "_"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
