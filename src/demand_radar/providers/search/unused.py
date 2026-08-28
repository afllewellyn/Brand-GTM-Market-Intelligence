"""A provider that names a backend without being able to reach it."""

from __future__ import annotations

from .base import SearchError, SearchProvider


class UnusedSearchProvider(SearchProvider):
    """Records the configured provider name without needing its credentials.

    ``demand-radar analyze`` replays stages 5-8 over saved evidence and
    never searches, so requiring live search credentials just to label the
    run in its metadata would be wrong. Searching through this raises,
    because reaching one of these means something called a stage that an
    analyze run does not have.
    """

    def __init__(self, name: str) -> None:
        self.name = name

    def search(self, query: str, limit: int = 10) -> list[dict]:
        raise SearchError("analyze does not search; it reuses saved evidence.")
