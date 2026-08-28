# 6. Both deliverables share one Markdown subset

Date: 2026-08-28

## Status

Accepted. Resolves the open item left in [ADR-0005](0005-prompts-are-guarded-by-contracts-not-snapshots.md).

## Context

`docx_export` promoted bare uppercase lines (`WHAT CHANGED`) to headings,
and `MockLLMProvider` emitted them, but `build_summary_prompt` never asked
for that format. It listed its questions in sentence case and said "plain
text or light Markdown."

So the renderer and the mock agreed on a convention the prompt was not
party to. Because the mock never reads the prompt, every golden fixture
confirmed that agreement and none of them touched the instruction. A real
model answering that prompt would plausibly write `**What changed?**` or
`## What changed?` or no markup at all; only the middle one renders as a
heading, so `executive_summary.docx` — the artifact people forward to a
CMO — could arrive as one unbroken block of body text.

The contract tests added in ADR-0005 found this but did not fix it: what
format to ask for is a decision about the deliverable, not about tests.

## Decision

The summary prompt asks for each question verbatim as a `##` heading, the
same subset `gtm_plan.md` already uses.

`##` was chosen over formalizing the uppercase convention because it hits
`_HEADING`, an exact regex, rather than `_is_bare_heading`, a heuristic
over line length, casing, and trailing punctuation. One markup language
across both deliverables also means one thing to explain and one path to
maintain.

The prompt additionally forbids a `#` title. `markdown_to_docx` consumes a
leading `# ` as the document name, which would displace the branded title
the Run supplies through the ledger's `title_template`.

**The uppercase path stays, as a fallback rather than the contract.** A
model that ignores the instruction and reverts to plain labels still gets
a document with headings instead of a wall of body text. It is cheap,
already written, and already tested; its test now says "fallback" so the
next reader does not mistake it for the primary path — or delete it as
dead code, which it is not.

One renderer change was required first: `markdown_to_docx` always writes a
title, from a leading `# ` or from `fallback_title`, but only the first
case demoted `##` to Heading 1. The summary relies on the fallback, so its
sections would have rendered a level below the plan's with Heading 1
unused. The demotion now applies either way.

## Consequences

- `tests/golden/executive_summary.md` moved: six heading lines, nothing
  else — matching what the blast-radius table in
  `test_golden_artifacts.py` predicts for this handler.
- Word output is unchanged in structure: Title plus Heading 1 sections,
  verified by running the demo and reading back the paragraph styles.
- The mock now demonstrates what the prompt asks for, so the worked
  example is evidence about the instruction rather than a coincidence
  beside it.
- Still unverified, as in ADR-0005: whether a real model obeys. These are
  unit tests over pure functions, and nothing here exercises a live
  provider.
