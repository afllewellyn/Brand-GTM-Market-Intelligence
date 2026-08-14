# The AirOps Prototype (V1)

This project began as an AirOps workflow built around an ElevenLabs
enterprise marketing use case, and was later pointed at Pontiac DSP to
support real GTM work. This CLI is the ground-up rebuild of that workflow.

## V1 workflow shape

```
Workflow Inputs
↓
LLM Query Expansion
↓
Iterator: Market Queries
  ↳ Google Search
  ↳ Python Processing
↓
Iterator: Intent Queries
  ↳ Google Search
  ↳ Python Processing
↓
Iterator: Competitor Queries
  ↳ Google Search
  ↳ Python Processing
↓
Normalize Results
↓
Aggregate Signals
↓
LLM Trend Analysis
↓
LLM GTM Recommendations
↓
LLM Executive Summary
↓
AirOps Grid
```

The core idea — deterministic evidence processing feeding constrained LLM
interpretation — was present from V1. The Python steps inside the AirOps
iterators did the counting; the LLM steps interpreted.

## Why rebuild it as a standalone CLI

- **Portability** — runs anywhere Python runs; no workflow platform seat
  required.
- **Testability** — pytest coverage over normalization, counting, config
  validation, and failure handling. Workflow steps are hard to unit test.
- **Evidence integrity** — evidence IDs, URL canonicalization, and
  reference validation are enforced in code, not by prompt convention.
- **Provider independence** — search and LLM sit behind interfaces;
  neither Google-via-AirOps nor a single model vendor is load-bearing.
- **Version control** — prompts, taxonomy, and pipeline logic are diffable
  and reviewable.
- **Model routing** — each task can run on a different model (cheap and
  fast for extraction, deliberative for strategy). See
  `docs/model_routing.md`.
- **Future data joins** — a CLI with JSON/CSV outputs is straightforward to
  integrate with CRM and analytics data later.

## What was preserved

- The eight-stage pipeline order.
- The theme taxonomy and its keyword mappings.
- The buying-stage definitions (early / mid / late).
- Example outputs from the prototype era, clearly labeled as unverified —
  see `examples/historical_prototype_output.json`.
