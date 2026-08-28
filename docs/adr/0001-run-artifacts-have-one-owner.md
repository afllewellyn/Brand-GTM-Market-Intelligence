# 1. A Run's artifacts have one owner

Date: 2026-08-28

## Status

Accepted.

## Context

`output.py` held three one-line wrappers (`write_json`, `write_text`,
`ensure_dir`) plus an evidence CSV writer. Deleting them would not have
concentrated complexity anywhere — it would have moved it back inline. The
module's interface was its implementation.

Meanwhile the complexity that *did* deserve hiding sat in `Pipeline`. Not
"how do I write a file," but: which files a Run produces, in what formats,
which are allowed to fail, and which must be cleared before the Run starts.
That was spread across five places:

- `_RUN_ARTIFACTS` and `_ANALYZE_ARTIFACTS`, two hand-maintained tuples of
  filenames that had to stay in step with each other and with the stages;
- `_clear_artifacts`;
- `_write_docx`, wrapping the Word twin in a best-effort `try/except`;
- `_write_metadata`;
- two `Path.exists()` probes in `_print_summary`, asking the filesystem
  what the Pipeline had itself just done.

Adding one deliverable meant editing four sites. The tuples already encoded
something untrue — they listed `gtm_plan.docx` unconditionally, though
`_write_docx` degrades to a warning. And one real invariant existed
nowhere: `analyze` must not delete `evidence.json`, because that file is
its own `--input`. The rule survived only as an *absence* from
`_ANALYZE_ARTIFACTS`, undocumented and untested.

## Decision

Introduce `run_ledger.py`, owning everything a Run writes. Absorb
`output.py` into it and delete that module.

**One table describes every artifact; everything else derives from it.**

- An artifact declares which `RunMode` produces it. A mode's clear-list is
  exactly the files it is about to write, which makes the `analyze` /
  `evidence.json` hazard structurally impossible rather than merely
  avoided. No `preserve` flag, no comment to overlook.
- An artifact has one or more **renditions** — the same content in more
  than one format. `evidence` is JSON plus CSV; `gtm_plan` is Markdown plus
  a Word twin. This collapses two things that were special cases into one
  concept.
- A rendition is required or best-effort. Best-effort is how a Word
  rendering problem degrades to a note instead of failing a Run whose LLM
  and search calls are already paid for.
- `finalize()` returns a **manifest** of what was actually written.
  `_print_summary` reads it instead of probing the directory.

Deliberate boundaries:

- **The ledger does not narrate.** A degradation carries the exception, not
  a rendered sentence; `Pipeline` decides what a person reads. Reporting is
  a separate seam and merging the two would fuse two audiences into one
  module.
- **The manifest is not persisted.** Its only consumers are in-process.
  Writing it to disk would add a file to a documented output contract in
  exchange for nothing.
- **There is no context manager and no `finally`.** `finalize()` runs only
  on the success path, so a Run that fails mid-way leaves visibly missing
  files. A `__exit__` that wrote metadata on failure would turn a broken
  Run into one that looks complete — the exact outcome the clear-first
  design exists to prevent.
- **The on-disk output is unchanged.** Same filenames, same flat `output/`
  directory, byte-identical content. `tests/test_golden_artifacts.py`
  pinned that before the refactor began, and was verified to be capable of
  failing.

Two smaller changes ride along, both consequences rather than goals:

- `self._metadata`, an untyped dict written by two stages and read back
  with `.get(key, 0)` defaults, becomes a typed `RunStats`.
- Constructing a `Pipeline` no longer creates the output directory; the
  ledger does, when a Run opens. A constructor with a filesystem side
  effect was never intended behaviour.

## Consequences

- Adding a deliverable is one table entry, not a four-site edit.
- `Pipeline` shrank by roughly 60 lines and no longer knows a single
  filename.
- The ledger has its own tests (`tests/test_run_ledger.py`). Clearing
  policy, rendition failure, and manifest behaviour were previously
  reachable only by driving a whole Pipeline.
- Run-scoped output directories, a persisted manifest, and run history all
  become local changes to one module. None of them are done here — this
  record is about who owns the decision, not about making it.
- One test moved with the seam: the Word-failure test now patches
  `run_ledger.markdown_to_docx` rather than `pipeline.markdown_to_docx`.

### Considered and rejected

- **A thinner ledger** (writers and clearing only, leaving Word twinning
  and metadata in `Pipeline`). Rejected: the `exists()` probes survive,
  and those were the clearest symptom.
- **A wider ledger** that also owns the closing summary. Rejected: see the
  narration boundary above.
- **One row per file** instead of renditions. Rejected: it leaves the CSV
  and the Word twin as two unrelated special cases and duplicates the
  call site for evidence.
- **Doing this together with unifying `run()` and `analyze_only()`.**
  Rejected as one refactor touching orchestration and I/O at once, which
  would leave a green suite proving very little. That change is now much
  smaller, and is the natural follow-up.
