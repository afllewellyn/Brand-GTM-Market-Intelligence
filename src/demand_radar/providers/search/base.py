"""Search provider interface."""

from __future__ import annotations

import abc


class SearchError(RuntimeError):
    """Raised when a search provider fails after retries."""


class SearchProvider(abc.ABC):
    """Contract for search backends (real APIs or mocks)."""

    name: str = "base"

    @abc.abstractmethod
    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Return raw results as dicts with at least title, snippet, url."""
