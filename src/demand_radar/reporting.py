"""How a Run tells someone what happened.

WHY THIS EXISTS
---------------
Two things a Run discovers are findings, not progress: that the theme
taxonomy barely matches the evidence, and that a Word twin could not be
rendered. Both used to exist only as formatted strings printed to a
terminal. The tests that guarded them had to reach for ``capsys`` and
substring-match English prose, so rewording a message broke a test while
the *condition* it described had no representation anywhere.

Stages now report **events**. A reporter decides what, if anything, a
person reads. Console formatting lives in one adapter; tests use a
recording adapter and assert on the event rather than the sentence.

The interface is deliberately small. Most lines a Run prints are ordinary
progress, carried by :meth:`RunReporter.stage` and
:meth:`RunReporter.detail`; only findings get a method of their own. A
reporter method per printed line would be a wide interface pretending to
be an abstraction.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .docx_export import DocxUnavailable
from .run_ledger import Manifest

log = logging.getLogger("demand_radar.run")


class RunReporter(abc.ABC):
    """What a Run reports as it executes. Implementations decide the medium."""

    @abc.abstractmethod
    def stage(self, number: int, total: int, detail: str) -> None:
        """A stage has started."""

    @abc.abstractmethod
    def detail(self, message: str) -> None:
        """A sub-line under the current stage — counts, tallies, progress."""

    @abc.abstractmethod
    def taxonomy_coverage_low(
        self, *, coverage: float, source: str, brand: str
    ) -> None:
        """Too little evidence matched any theme for the counts to mean much.

        A taxonomy tuned for another market still produces counts under a
        correct-looking brand header. This is the only thing standing
        between a reader and meaningless numbers.
        """

    @abc.abstractmethod
    def deliverable_degraded(self, *, path: Path, error: Exception) -> None:
        """A best-effort rendition of a deliverable could not be written."""

    @abc.abstractmethod
    def run_complete(self, *, brand: str, summary: str, manifest: Manifest) -> None:
        """The Run finished. The manifest says what it actually produced."""


class ConsoleReporter(RunReporter):
    """Renders a Run to the terminal. Owns every user-facing word.

    ``echo`` is a console concern, not a Pipeline one: with it off, events
    are still logged, which is what a library caller or a test driving the
    pipeline for its artifacts wants.
    """

    def __init__(self, echo: bool = True) -> None:
        self._echo = echo

    def _write(self, message: str) -> None:
        if self._echo:
            # flush=True keeps progress ordered against errors. stdout is
            # block-buffered when piped while stderr is not, so without this
            # a failure message surfaces *above* the stage that caused it.
            print(message, flush=True)
        log.info(message)

    def stage(self, number: int, total: int, detail: str) -> None:
        self._write(f"[{number}/{total}] {detail}")

    def detail(self, message: str) -> None:
        self._write(f"  {message}")

    def taxonomy_coverage_low(
        self, *, coverage: float, source: str, brand: str
    ) -> None:
        self._write(
            f"  WARNING: only {coverage:.0%} of evidence matched any theme "
            f"(from {source}).\n"
            f"  Theme counts above are unreliable for {brand}. "
            f"Set themes_file in your config to a taxonomy for this market."
        )

    def deliverable_degraded(self, *, path: Path, error: Exception) -> None:
        # DocxUnavailable already carries actionable guidance for a person;
        # anything else needs the reassurance that the Markdown survived.
        if isinstance(error, DocxUnavailable):
            self._write(f"  NOTE: {error}")
        else:
            self._write(
                f"  NOTE: could not write {path.name} ({error}). "
                f"{path.stem}.md is complete and unaffected."
            )

    def run_complete(self, *, brand: str, summary: str, manifest: Manifest) -> None:
        bar = "=" * 60
        self._write(f"\n{bar}\nENTERPRISE DEMAND RADAR — {brand.upper()}\n{bar}\n")
        if self._echo:
            # The summary is the deliverable itself, not narration about it.
            print(summary)
        # Every pointer comes from the manifest — what this Run wrote —
        # rather than from probing the output directory. The Word twin is
        # best-effort and `analyze` writes no evidence CSV, so naming either
        # unconditionally would send someone after a file that never existed.
        self._write(f"\nFull report: {manifest.path('gtm_plan', '.md')}")
        if manifest.wrote("gtm_plan", ".docx"):
            self._write(
                f"  (Word version for sharing: {manifest.path('gtm_plan', '.docx')})"
            )
        if manifest.wrote("evidence", ".csv"):
            self._write(f"Evidence: {manifest.path('evidence', '.csv')}")


# -- recorded events --------------------------------------------------------
@dataclass(frozen=True)
class CoverageWarning:
    coverage: float
    source: str
    brand: str


@dataclass(frozen=True)
class DegradedDeliverable:
    path: Path
    error: Exception


@dataclass(frozen=True)
class Completion:
    brand: str
    summary: str
    manifest: Manifest


@dataclass
class RecordingReporter(RunReporter):
    """Keeps events instead of rendering them.

    Lets a caller ask "did this Run report low coverage, and at what
    percentage?" without parsing a sentence out of stdout.
    """

    stages: list[tuple[int, int, str]] = field(default_factory=list)
    details: list[str] = field(default_factory=list)
    coverage_warnings: list[CoverageWarning] = field(default_factory=list)
    degradations: list[DegradedDeliverable] = field(default_factory=list)
    completions: list[Completion] = field(default_factory=list)

    def stage(self, number: int, total: int, detail: str) -> None:
        self.stages.append((number, total, detail))

    def detail(self, message: str) -> None:
        self.details.append(message)

    def taxonomy_coverage_low(
        self, *, coverage: float, source: str, brand: str
    ) -> None:
        self.coverage_warnings.append(CoverageWarning(coverage, source, brand))

    def deliverable_degraded(self, *, path: Path, error: Exception) -> None:
        self.degradations.append(DegradedDeliverable(path, error))

    def run_complete(self, *, brand: str, summary: str, manifest: Manifest) -> None:
        self.completions.append(Completion(brand, summary, manifest))
