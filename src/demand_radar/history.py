"""Run-over-run comparison foundation (interface only for now).

"There are many pricing mentions" is a weaker claim than "pricing interest
is increasing." Distinguishing the two requires comparing the current run's
deterministic counts against a previous run's. This module defines that
interface; persistence of past runs is a TODO.

Future output shape::

    {
      "pricing_roi": {"current": 31, "previous": 19, "delta": 12,
                       "percent_change": 63.2}
    }
"""

from __future__ import annotations

from .schemas.signals import SignalSummary  # noqa: F401  (interface reference)


def compare_theme_counts(
    current: dict[str, int], previous: dict[str, int]
) -> dict[str, dict[str, float]]:
    """Compute deltas between two theme-count dicts. Pure and deterministic."""
    out: dict[str, dict[str, float]] = {}
    for theme in sorted(set(current) | set(previous)):
        cur = current.get(theme, 0)
        prev = previous.get(theme, 0)
        delta = cur - prev
        pct = round((delta / prev) * 100, 1) if prev else None
        out[theme] = {
            "current": cur,
            "previous": prev,
            "delta": delta,
            "percent_change": pct,
        }
    return out


class HistoryStore:
    """Interface for persisting and retrieving prior runs' signal summaries.

    TODO: implement a filesystem-backed store, e.g.::

        output/history/<run_id>/signals.json

    then have the pipeline call ``load_previous()`` and feed
    :func:`compare_theme_counts` output into the trend-analysis prompt so the
    LLM can reason about direction, not just volume.
    """

    def save(self, run_id: str, summary: "SignalSummary") -> None:
        raise NotImplementedError("Historical persistence is not implemented yet.")

    def load_previous(self, before_run_id: str | None = None) -> "SignalSummary | None":
        raise NotImplementedError("Historical persistence is not implemented yet.")
