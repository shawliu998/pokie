# ADR 0003: One typed bounded Research Graph

- Status: Accepted
- Date: 2026-07-15

## Context

Research needs planning, retrieval, evidence analysis, counter-evidence review and human approval. Multiple autonomous agents would obscure responsibility, expand tool risk and make costs/state hard to reproduce.

## Decision

Use one LangGraph per ResearchRun inside an Investigation, with a versioned input manifest, Pydantic proposal schemas, fixed deterministic nodes, fixed LLM nodes and persisted human gates. The graph may use bounded parallel retrieval but may not self-create agents/tools/graphs. Model-visible tools are read-only: authorized pinned-content retrieval and deterministic calculations only. LLMs output plan, evidence, ClaimVersion or synthesis proposals as node data; proposal persistence is a worker-to-Domain-Service command, not a model tool. Review, state transitions and export remain graph-external REST/Domain commands with actor, idempotency and version checks.

## Consequences

The graph is inspectable, resumable and evaluable, while product UI remains based on Investigation, RunEvent and ResearchTask rather than LangGraph internals. Future specialized behavior must be added as a typed node or read-only tool capability, not a second autonomous agent or write-capable model tool.
