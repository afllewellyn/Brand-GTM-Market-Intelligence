"""Search provider factory plus the Serper adapter.

Production default: :class:`~demand_radar.providers.search.dataforseo.DataForSEOSearchProvider`.
Serper is kept as a supported alternative. Other providers (SerpAPI,
Tavily, Brave) can be added by implementing :class:`SearchProvider` and
registering them in :func:`get_search_provider`.

All providers read credentials from environment variables only — config
files can never carry keys (enforced in ``config.load_config``).
"""

from __future__ import annotations

import logging
import os
import time

import requests

from ...config import RadarConfig
from .base import SearchError, SearchProvider

log = logging.getLogger(__name__)

_SERPER_URL = "https://google.serper.dev/search"


class SerperSearchProvider(SearchProvider):
    """Google results via the Serper.dev API. Requires SERPER_API_KEY."""

    name = "serper"

    def __init__(self, api_key: str | None = None, retries: int = 2) -> None:
        self._key = api_key or os.environ.get("SERPER_API_KEY")
        if not self._key:
            raise SearchError(
                "SERPER_API_KEY is not set. Export it, or use search.provider: "
                "mock (see config/example.yaml)."
            )
        self._retries = retries

    def search(self, query: str, limit: int = 10) -> list[dict]:
        payload = {"q": query, "num": limit}
        headers = {"X-API-KEY": self._key, "Content-Type": "application/json"}
        last_exc: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                resp = requests.post(
                    _SERPER_URL, json=payload, headers=headers, timeout=20
                )
                resp.raise_for_status()
                organic = resp.json().get("organic", [])
                return [
                    {
                        "title": r.get("title", ""),
                        "snippet": r.get("snippet", ""),
                        "url": r.get("link", ""),
                    }
                    for r in organic[:limit]
                ]
            except requests.RequestException as exc:
                last_exc = exc
                if attempt == self._retries:
                    break  # out of attempts — don't sleep before giving up
                wait = 2**attempt
                log.warning(
                    "Search failed for %r (attempt %d/%d): %s — retrying in %ss",
                    query, attempt + 1, self._retries + 1, exc, wait,
                )
                time.sleep(wait)
        raise SearchError(f"Search failed for {query!r}: {last_exc}")


def get_search_provider(config: RadarConfig) -> SearchProvider:
    """Factory keyed on ``search.provider`` in the run config."""
    if config.search.provider == "mock":
        from .mock import MockSearchProvider

        return MockSearchProvider()
    if config.search.provider == "serper":
        return SerperSearchProvider()
    if config.search.provider == "dataforseo":
        from .dataforseo import DataForSEOSearchProvider

        return DataForSEOSearchProvider(
            language_code=config.search.language_code,
            location_code=config.search.location_code,
        )
    raise SearchError(f"Unknown search provider: {config.search.provider}")
