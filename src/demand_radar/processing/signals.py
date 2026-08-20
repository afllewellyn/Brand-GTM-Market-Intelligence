"""Deterministic signal aggregation.

THE COUNTING RULE
-----------------
Every number in this system's outputs — theme counts, query-type counts,
domain counts, totals — is computed here, in Python, from normalized
evidence rows. The LLM receives these counts as read-only input and is
instructed never to alter or invent them. If a count is not in
``signals.json``, it does not exist.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml

from ..schemas.evidence import EvidenceRow
from ..schemas.signals import SignalSummary

# Market-agnostic fallback taxonomy: generic B2B buying signals that appear in
# any enterprise category. It is deliberately not tuned to one market — a
# taxonomy that fits a specific market always beats this one, so a real run
# should set themes_file. Stage 5 warns when coverage against it is low.
DEFAULT_THEMES: dict[str, list[str]] = {
    "pricing_roi": [
        "pricing", "price", "cost", "roi", "return on investment",
        "tco", "payback", "economics", "budget",
    ],
    "compliance_security": [
        "compliance", "security", "privacy", "gdpr", "ccpa", "soc 2",
        "hipaa", "governance", "data residency", "risk", "audit",
    ],
    "performance_validation": [
        "performance", "latency", "reliability", "benchmark", "accuracy",
        "uptime", "case study", "scale", "production", "sla",
    ],
    "implementation": [
        "implementation", "integration", "api", "deployment",
        "migration", "architecture", "onboarding", "rollout",
    ],
    "comparison": [
        " vs ", "versus", "alternative", "alternatives", "compare", "comparison",
    ],
    "vendor_evaluation": [
        "rfp", "rfi", "shortlist", "buyer's guide", "buyers guide",
        "evaluation", "review", "g2", "gartner", "forrester", "procurement",
    ],
    "adoption_enablement": [
        "training", "support", "documentation", "best practices",
        "adoption", "change management", "professional services",
    ],
}


def load_themes(path: str | Path | None) -> dict[str, list[str]]:
    """Load a theme taxonomy from YAML, or fall back to the defaults."""
    if path is None:
        return DEFAULT_THEMES
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    themes = data.get("themes", data) if isinstance(data, dict) else None
    if not isinstance(themes, dict) or not themes:
        raise ValueError(f"No themes found in {path}")
    return {name: [str(k).lower() for k in kws] for name, kws in themes.items()}


def match_themes(text: str, themes: dict[str, list[str]]) -> list[str]:
    """Return theme names whose keywords appear in ``text`` (case-insensitive)."""
    haystack = f" {text.lower()} "
    return [
        name
        for name, keywords in themes.items()
        if any(kw in haystack for kw in keywords)
    ]


def aggregate_signals(
    rows: list[EvidenceRow],
    themes: dict[str, list[str]] | None = None,
    top_n_domains: int = 15,
) -> SignalSummary:
    """Count theme matches, query types, and top domains over evidence rows."""
    themes = themes or DEFAULT_THEMES
    theme_counts: Counter[str] = Counter()
    theme_evidence_ids: dict[str, list[str]] = {name: [] for name in themes}
    query_type_counts: Counter[str] = Counter()
    domains: Counter[str] = Counter()

    for row in rows:
        query_type_counts[row.query_type] += 1
        if row.domain:
            domains[row.domain] += 1
        for theme in match_themes(f"{row.title} {row.snippet}", themes):
            theme_counts[theme] += 1
            theme_evidence_ids[theme].append(row.evidence_id)

    return SignalSummary(
        total_evidence_rows=len(rows),
        theme_counts=dict(theme_counts.most_common()),
        theme_evidence_ids={k: v for k, v in theme_evidence_ids.items() if v},
        query_type_counts=dict(query_type_counts),
        top_domains=dict(domains.most_common(top_n_domains)),
    )
