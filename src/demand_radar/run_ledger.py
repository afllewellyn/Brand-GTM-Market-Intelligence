"""The Run Ledger: one owner for everything a Run writes to disk.

WHY THIS EXISTS
---------------
Writing a file is not the hard part. The hard part is knowing *which*
files a Run produces, in what shape, which of them are allowed to fail,
and which must be cleared before the Run starts so a failure leaves
visibly missing files rather than a convincing blend of two Runs.

That knowledge used to be spread across the Pipeline: two hand-maintained
tuples of filenames, a clearing helper, a best-effort Word wrapper, a
metadata writer, and two ``Path.exists()`` probes in the closing summary
that asked the filesystem what the Pipeline had just done. Adding one
deliverable meant editing four places, and the tuples could drift out of
step with the stages they described.

Here, one table describes every Artifact. Everything else is derived from
it:

* an Artifact belongs to one or more :class:`RunMode`, and a mode's
  clear-list is exactly the files that mode is about to write. This is
  what makes it structurally impossible for ``analyze`` to delete
  ``evidence.json`` — the file it reads as its own input;
* an Artifact has one or more **Renditions**: the same content written in
  more than one format. ``evidence`` is JSON plus CSV; ``gtm_plan`` is
  Markdown plus a Word twin. A Rendition may be best-effort, which is how
  a Word rendering problem degrades to a note instead of failing a Run
  whose LLM and search calls are already paid for;
* :meth:`RunLedger.finalize` returns a :class:`Manifest` — what was
  actually written — so callers report from a record rather than by
  probing the directory.

The ledger deliberately does not narrate. It records outcomes and hands
them back; deciding what a person reads about them belongs to the caller.
"""

from __future__ import annotations

import csv
import json
import logging
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

from .docx_export import markdown_to_docx
from .processing.serp import utc_now_iso
from .schemas.evidence import EvidenceRow

log = logging.getLogger(__name__)


class RunMode(Enum):
    """Which entry point opened this Run. Decides its Artifact set."""

    FULL = "full"
    """``demand-radar run`` — all eight stages, from seed keywords."""

    ANALYZE = "analyze"
    """``demand-radar analyze`` — stages 5-8 over evidence collected earlier."""


# -- Renditions -------------------------------------------------------------
# Each writer takes (payload, path, title). `title` is meaningful only to
# formats that carry document metadata; the rest accept and ignore it so a
# Rendition is one uniform thing.

def _write_model_json(payload: Any, path: Path, title: str) -> None:
    _write_mapping_json(payload.model_dump(), path, title)


def _write_rows_json(payload: list[EvidenceRow], path: Path, title: str) -> None:
    _write_mapping_json([row.model_dump() for row in payload], path, title)


def _write_mapping_json(payload: Any, path: Path, title: str) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _write_rows_csv(payload: list[EvidenceRow], path: Path, title: str) -> None:
    fields = list(EvidenceRow.model_fields)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in payload:
            writer.writerow(row.model_dump())


def _write_markdown(payload: str, path: Path, title: str) -> None:
    path.write_text(payload, encoding="utf-8")


def _write_docx(payload: str, path: Path, title: str) -> None:
    # Resolved through the module global so tests can substitute the
    # renderer and exercise the degradation path.
    markdown_to_docx(payload, path, title)


@dataclass(frozen=True)
class Rendition:
    """One format an Artifact is written in.

    A required Rendition that fails aborts the Run. A best-effort one
    records a :class:`Degradation` and lets the Run continue — reserved for
    formats derived from a source of truth that is already safely on disk.
    """

    suffix: str
    write: Callable[[Any, Path, str], None]
    required: bool = True


@dataclass(frozen=True)
class ArtifactSpec:
    """One logical output of a Run, in one or more Renditions."""

    name: str
    produced_by: frozenset[RunMode]
    renditions: tuple[Rendition, ...]
    #: Document title for Renditions that carry one. ``{brand}`` is filled in.
    title_template: str = ""

    def filenames(self) -> tuple[str, ...]:
        return tuple(f"{self.name}{r.suffix}" for r in self.renditions)


_BOTH = frozenset({RunMode.FULL, RunMode.ANALYZE})
_FULL_ONLY = frozenset({RunMode.FULL})

#: Every file a Run can write. The single source of truth for filenames,
#: encoding, failure policy, and which mode produces what.
#:
#: `evidence` is FULL-only on purpose: `analyze` replays stages 5-8 over
#: evidence supplied with --input, which is normally this very file. Because
#: a mode clears exactly what it produces, an analyze Run can never delete
#: its own input.
ARTIFACTS: tuple[ArtifactSpec, ...] = (
    ArtifactSpec("queries", _FULL_ONLY, (Rendition(".json", _write_model_json),)),
    ArtifactSpec(
        "evidence",
        _FULL_ONLY,
        (Rendition(".json", _write_rows_json), Rendition(".csv", _write_rows_csv)),
    ),
    ArtifactSpec("signals", _BOTH, (Rendition(".json", _write_model_json),)),
    ArtifactSpec("analysis", _BOTH, (Rendition(".json", _write_model_json),)),
    ArtifactSpec(
        "gtm_plan",
        _BOTH,
        (
            Rendition(".md", _write_markdown),
            Rendition(".docx", _write_docx, required=False),
        ),
        title_template="GTM Plan — {brand}",
    ),
    ArtifactSpec(
        "executive_summary",
        _BOTH,
        (
            Rendition(".md", _write_markdown),
            Rendition(".docx", _write_docx, required=False),
        ),
        title_template="Executive Summary — {brand}",
    ),
    ArtifactSpec("run_metadata", _BOTH, (Rendition(".json", _write_mapping_json),)),
)


# -- Outcomes ---------------------------------------------------------------
@dataclass(frozen=True)
class Degradation:
    """A best-effort Rendition that could not be written.

    Carries the exception rather than a message: how a failure is worded
    for a person is the caller's decision, not the ledger's.
    """

    path: Path
    error: Exception


@dataclass(frozen=True)
class RecordResult:
    """What one :meth:`RunLedger.record` call produced."""

    written: tuple[Path, ...]
    degraded: tuple[Degradation, ...]


class Manifest:
    """What a Run actually wrote.

    Replaces asking the filesystem. A caller that needs to know whether the
    Word twin exists asks the Run that wrote it, not the directory.
    """

    def __init__(self) -> None:
        self._written: dict[tuple[str, str], Path] = {}
        self._degraded: list[Degradation] = []

    def _record_written(self, name: str, suffix: str, path: Path) -> None:
        self._written[(name, suffix)] = path

    def _record_degraded(self, degradation: Degradation) -> None:
        self._degraded.append(degradation)

    def wrote(self, name: str, suffix: str) -> bool:
        return (name, suffix) in self._written

    def path(self, name: str, suffix: str) -> Path:
        """Path of a Rendition this Run wrote. Raises if it did not."""
        try:
            return self._written[(name, suffix)]
        except KeyError:
            raise KeyError(
                f"This Run did not write {name}{suffix}. Check `wrote()` first "
                f"for anything that is not guaranteed."
            ) from None

    @property
    def paths(self) -> tuple[Path, ...]:
        return tuple(self._written.values())

    @property
    def degradations(self) -> tuple[Degradation, ...]:
        return tuple(self._degraded)


@dataclass
class RunStats:
    """Counts a Run accumulates as its stages complete.

    Replaces an untyped dict read back with ``.get(key, 0)`` defaults —
    a missing count now reads as zero because zero is the default, not
    because the key was never set.
    """

    queries_run: int = 0
    raw_results: int = 0
    normalized_evidence_rows: int = 0


class RunLedger:
    """Owns the Artifacts of exactly one Run.

    Constructing one opens the Run: it creates the output directory, mints
    the run id, stamps the start time, and clears the Artifacts this mode
    is about to write. There is no ``begin()`` — an instance is never in a
    state where :meth:`record` is illegal.

    There is deliberately no context manager and no ``finally``. Stale
    Artifacts are cleared up front and :meth:`finalize` runs only on the
    success path, so a Run that fails mid-way leaves visibly missing files.
    Writing metadata on the failure path would turn a broken Run into one
    that looks complete, which is the outcome this design exists to
    prevent.
    """

    def __init__(
        self, output_dir: str | Path, mode: RunMode, brand_name: str
    ) -> None:
        self.mode = mode
        self.brand_name = brand_name
        self.dir = Path(output_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.run_id = uuid.uuid4().hex[:12]
        self.started_at = utc_now_iso()
        self._specs = {s.name: s for s in ARTIFACTS if mode in s.produced_by}
        self._manifest = Manifest()
        self._clear()

    def _clear(self) -> None:
        """Remove the Artifacts this Run will write, and only those."""
        for spec in self._specs.values():
            for filename in spec.filenames():
                (self.dir / filename).unlink(missing_ok=True)

    def record(self, name: str, payload: Any) -> RecordResult:
        """Write every Rendition of one Artifact.

        Returns what was written and what degraded, so the caller can
        report a best-effort failure at the moment it happens.
        """
        try:
            spec = self._specs[name]
        except KeyError:
            known = ", ".join(sorted(self._specs)) or "(none)"
            raise KeyError(
                f"No artifact '{name}' is produced by a {self.mode.value} Run. "
                f"This Run produces: {known}."
            ) from None

        title = (
            spec.title_template.format(brand=self.brand_name)
            if spec.title_template
            else ""
        )
        written: list[Path] = []
        degraded: list[Degradation] = []

        for rendition in spec.renditions:
            path = self.dir / f"{spec.name}{rendition.suffix}"
            try:
                rendition.write(payload, path, title)
            except Exception as exc:
                if rendition.required:
                    raise
                log.warning("Could not write %s: %s", path.name, exc)
                failure = Degradation(path, exc)
                degraded.append(failure)
                self._manifest._record_degraded(failure)
                continue
            written.append(path)
            self._manifest._record_written(spec.name, rendition.suffix, path)

        return RecordResult(tuple(written), tuple(degraded))

    def finalize(
        self,
        *,
        stats: RunStats,
        search_provider: str,
        llm_provider: str,
        models_used: Mapping[str, str],
    ) -> Manifest:
        """Write the run metadata and close the Run; returns its Manifest."""
        self.record(
            "run_metadata",
            {
                "run_id": self.run_id,
                "brand": self.brand_name,
                "started_at": self.started_at,
                "completed_at": utc_now_iso(),
                "search_provider": search_provider,
                "llm_provider": llm_provider,
                "models_used": dict(models_used),
                "queries_run": stats.queries_run,
                "raw_results": stats.raw_results,
                "normalized_evidence_rows": stats.normalized_evidence_rows,
            },
        )
        return self._manifest
