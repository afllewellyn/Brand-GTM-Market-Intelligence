"""Raw SERP result -> normalized result dicts (pre-dedup)."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def extract_domain(url: str) -> str:
    """Return the registrable-ish host, minus a leading ``www.``."""
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def normalize_result(
    raw: dict,
    query: str,
    query_type: str,
    competitor_name: str | None = None,
) -> dict:
    """Shape one raw search result into the pipeline's normalized fields."""
    url = (raw.get("url") or "").strip()
    return {
        "query": query,
        "query_type": query_type,
        "title": (raw.get("title") or "").strip(),
        "snippet": (raw.get("snippet") or "").strip(),
        "url": url,
        "domain": extract_domain(url),
        "source_type": "serp",
        "competitor_name": competitor_name,
        "retrieved_at": utc_now_iso(),
    }
