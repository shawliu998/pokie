# ADR 0001: Modular monolith with independent worker

- Status: Accepted
- Date: 2026-07-15

## Context

Glint must deliver one credible product-intelligence loop for a 5–20 person team while retaining strong domain boundaries, auditability and background processing. The product has asynchronous collection and research work, but Phase 0 does not justify operationally independent domain services, Kafka, Kubernetes or a complex workflow platform.

## Decision

Use one Python codebase organized as explicit domain modules, deploy it as a FastAPI API process and an independent Dramatiq worker process, with a scheduler, PostgreSQL, Redis and compatible object store. Modules communicate through public domain commands/queries and transactional outbox events. The Mac app is a separate client/cache, not another authoritative backend.

## Consequences

This reduces deployment and tracing complexity while isolating long-running work from API latency. Module interfaces, ownership and schema migrations must be maintained so future extraction remains possible. A shared database is allowed only behind module-owned repositories and workspace policy; direct cross-module table writes are prohibited.
