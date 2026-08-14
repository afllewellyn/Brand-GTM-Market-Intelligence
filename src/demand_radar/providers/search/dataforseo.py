"""DataForSEO search adapter — the primary production search provider.

Uses the DataForSEO SERP API (Google organic, live mode) with HTTP Basic
auth. Credentials come ONLY from environment variables:

    DATAFORSEO_LOGIN=
    DATAFORSEO_PASSWORD=

They are never read from config files, so a shared or committed config can
never leak credentials.
"""

from __future__ import annotations

import logging
import os
import time

import requests

from .base import SearchError, SearchProvider

log = logging.getLogger(__name__)

_ENDPOINT = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"


class DataForSEOSearchProvider(SearchProvider):
    """Google organic results via the DataForSEO SERP API (live mode)."""

    name = "dataforseo"

    def __init__(
        self,
        login: str | None = None,
        password: str | None = None,
        language_code: str = "en",
        location_code: int = 2840,  # United States
        retries: int = 2,
    ) -> None:
        self._login = login or os.environ.get("DATAFORSEO_LOGIN")
        self._password = password or os.environ.get("DATAFORSEO_PASSWORD")
        if not self._login or not self._password:
            raise SearchError(
                "DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD are not set. Export "
                "them (see .env.example), or use search.provider: serper or "
                "mock. Credentials are read from the environment only — "
                "never put them in config files."
            )
        self._language_code = language_code
        self._location_code = location_code
        self._retries = retries

    def search(self, query: str, limit: int = 10) -> list[dict]:
        payload = [
            {
                "keyword": query,
                "language_code": self._language_code,
                "location_code": self._location_code,
                "depth": max(limit, 10),
            }
        ]
        last_exc: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                resp = requests.post(
                    _ENDPOINT,
                    json=payload,
                    auth=(self._login, self._password),
                    timeout=30,
                )
                resp.raise_for_status()
                return self._parse(resp.json(), limit)
            except (requests.RequestException, SearchError) as exc:
                last_exc = exc
                if attempt == self._retries:
                    break  # out of attempts — don't sleep before giving up
                wait = 2**attempt
                log.warning(
                    "DataForSEO search failed for %r (attempt %d/%d): %s — "
                    "retrying in %ss",
                    query, attempt + 1, self._retries + 1, exc, wait,
                )
                time.sleep(wait)
        raise SearchError(f"DataForSEO search failed for {query!r}: {last_exc}")

    # ------------------------------------------------------------------
    @staticmethod
    def _parse(data: dict, limit: int) -> list[dict]:
        """Extract organic items from a DataForSEO live response."""
        if data.get("status_code") != 20000:
            raise SearchError(
                f"DataForSEO API error {data.get('status_code')}: "
                f"{data.get('status_message')}"
            )
        results: list[dict] = []
        for task in data.get("tasks") or []:
            if task.get("status_code") != 20000:
                log.warning(
                    "DataForSEO task error %s: %s",
                    task.get("status_code"), task.get("status_message"),
                )
                continue
            for result in task.get("result") or []:
                for item in result.get("items") or []:
                    if item.get("type") != "organic":
                        continue
                    results.append(
                        {
                            "title": item.get("title") or "",
                            "snippet": item.get("description") or "",
                            "url": item.get("url") or "",
                        }
                    )
                    if len(results) >= limit:
                        return results
        return results
