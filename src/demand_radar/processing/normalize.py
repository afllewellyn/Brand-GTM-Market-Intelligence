"""Deterministic evidence normalization.

URL canonicalization, deduplication, and stable evidence-ID assignment all
live here — in Python, never in the LLM. Every downstream claim can be traced
back to a row produced by this module.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ..schemas.evidence import EvidenceRow

# Query params that never change page identity.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "msclkid", "ref", "referrer", "mc_cid", "mc_eid",
}


def normalize_url(url: str) -> str:
    """Canonicalize a URL for deduplication.

    Lowercases scheme/host, strips ``www.``, drops fragments and tracking
    params, sorts the remaining query params, and removes a trailing slash
    on non-root paths.
    """
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    kept = sorted(
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    )
    return urlunparse((scheme, netloc, path, "", urlencode(kept), ""))


def dedupe_and_assign_ids(rows: list[dict]) -> list[EvidenceRow]:
    """Deduplicate by normalized URL and assign evidence IDs e1..eN.

    Order is preserved (first occurrence wins), so IDs are stable for a
    given input sequence. Rows without a URL are dropped.
    """
    seen: set[str] = set()
    out: list[EvidenceRow] = []
    counter = 0
    for row in rows:
        url = row.get("url", "")
        if not url:
            continue
        key = normalize_url(url)
        if key in seen:
            continue
        seen.add(key)
        counter += 1
        out.append(EvidenceRow(evidence_id=f"e{counter}", **row))
    return out
