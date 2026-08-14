# Model Routing

## Today: static routing

`LLMRouter` resolves the model for each task from central config — no model
names are hardcoded in pipeline code:

```yaml
llm:
  provider: anthropic
  routing_mode: static
  tasks:
    query_expansion:      { model: claude-haiku-4-5,  reasoning_level: low }
    trend_analysis:       { model: claude-sonnet-5,  reasoning_level: high }
    gtm_recommendations:  { model: claude-sonnet-5,  reasoning_level: medium }
    executive_summary:    { model: claude-haiku-4-5,  reasoning_level: low }
```

Model identifiers live only in configuration, so upgrading models is a
config change, not a code change. Check the Anthropic docs
(https://docs.claude.com/en/api/overview) for currently available models.

`reasoning_level` tunes token budgets today; it is also the hook a future
router will use to decide how much deliberation a task deserves.

## Tomorrow: adaptive routing via an external service

`routing_mode: adaptive` is reserved for a companion project whose job is:

> Select an LLM/model based on task complexity, cost, latency, and need
> for deliberation.

The conceptual routing tiers:

| Task profile | Route to |
|---|---|
| Simple extraction / reformatting | Low-cost, low-latency model |
| Normal analysis | General-purpose model |
| Ambiguous strategic reasoning | Deliberative / higher-reasoning model |

The router would consider: task type, expected schema, context size,
latency budget, cost budget, reasoning complexity, and confidence
requirements.

## Integration contract

The external service plugs in through two seams that already exist:

1. **`RouteDecision`** (in `providers/llm/router.py`) mirrors the decision
   object the service would return.
2. **`ExternalRouterProvider`** is the stub adapter. Conceptually:

```python
decision = router.route(
    task="trend_analysis",
    complexity="high",
    structured_output=True,
    context_tokens=45000,
)

response = provider.complete(
    model=decision.model,
    ...
)
```

Because the pipeline only ever calls `LLMRouter.complete(task, prompt,
schema, reasoning_level)`, swapping static routing for the external service
requires zero pipeline changes — only a new provider registration in
`build_router()`.

Model names are intentionally not hardcoded in this document's routing
logic; the external service (or your config) supplies them.
