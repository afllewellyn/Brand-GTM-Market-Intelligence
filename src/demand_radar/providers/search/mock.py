"""Deterministic synthetic search results for demo mode and tests.

Results are generated from a seeded hash of the query, so runs are
reproducible. Titles and snippets deliberately embed theme-taxonomy keywords
(pricing, compliance, benchmark, voice agent, ...) so the deterministic
aggregator produces a varied, realistic signal distribution.

All URLs use clearly fake ``*.example.com``-style domains so synthetic data
can never be mistaken for real sources.
"""

from __future__ import annotations

import hashlib
import random

from .base import SearchProvider

_DOMAINS = [
    "market-signal-daily.example.com",
    "cx-operations-review.example.com",
    "enterprise-ai-briefing.example.com",
    "voice-tech-weekly.example.com",
    "b2b-buyer-journal.example.com",
    "procurement-notes.example.com",
]

_TEMPLATES = [
    ("{q}: pricing and ROI breakdown for enterprise buyers",
     "A look at pricing models, total cost of ownership, and payback periods "
     "reported by enterprise teams evaluating {q}."),
    ("How enterprises evaluate {q} — implementation and integration guide",
     "Covers API integration, deployment architecture, and migration "
     "planning for teams rolling out {q}."),
    ("{q} compliance checklist: SOC 2, GDPR, and data residency",
     "Security and governance questions procurement teams raise during "
     "{q} vendor risk review."),
    ("Benchmark report: latency and accuracy across {q} vendors",
     "Performance benchmarks, uptime data, and a production case study "
     "comparing leading {q} platforms."),
    ("{q} alternatives compared: which vendor fits your contact center?",
     "A versus-style comparison of alternatives for {q}, with evaluation "
     "criteria for customer experience leaders."),
    ("Why voice agents are reshaping the contact center",
     "Enterprise adoption stories of AI agents and phone agents for "
     "customer experience, including {q}."),
    ("Webinar recap: scaling {q} in multilingual markets",
     "Localization, translation quality, and multilingual deployment "
     "lessons for global teams adopting {q}."),
]


class MockSearchProvider(SearchProvider):
    """Seeded synthetic SERP generator. No credentials, no network."""

    name = "mock"

    def search(self, query: str, limit: int = 10) -> list[dict]:
        seed = int(hashlib.sha256(query.encode("utf-8")).hexdigest(), 16) % (2**32)
        rng = random.Random(seed)
        results: list[dict] = []
        for i in range(limit):
            title_tpl, snippet_tpl = _TEMPLATES[(seed + i) % len(_TEMPLATES)]
            domain = _DOMAINS[rng.randrange(len(_DOMAINS))]
            # Python's built-in hash() is salted per-process for str/tuple
            # inputs (PYTHONHASHSEED), so it can't back the "reproducible
            # across runs" guarantee above. Draw from the already-seeded
            # random.Random stream instead, which is stable by seed alone.
            slug = f"{rng.randrange(100000)}"
            results.append(
                {
                    "title": title_tpl.format(q=query),
                    "snippet": snippet_tpl.format(q=query),
                    "url": f"https://{domain}/articles/{slug}",
                }
            )
        return results
