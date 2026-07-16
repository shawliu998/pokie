# ADR 0005: Investigation and Decision Brief are the product aggregates

- Status: Accepted
- Date: 2026-07-15

## Context

Product design uses Inbox → Investigation → Decision Brief, while an earlier engineering model treated ResearchRun, Insight and generic Deliverable as equivalent top-level lifecycle objects. That would create competing sources of truth and make a retrying ResearchRun overwrite durable PM work.

## Decision

Investigation is the user work aggregate. In MVP it starts from one Signal, owns the Decision Question and versioned scope, contains one or more ResearchRuns, and collects Evidence, ClaimVersions and an intermediate synthesis.

ResearchRun is one bounded execution attempt. The earlier Insight concept is implemented as InvestigationSynthesisVersion: an Investigation-scoped, reviewed intermediate snapshot with no independent navigation, owner or long-term decision lifecycle.

Product Decision Brief is the sole decision-level aggregate. Every DecisionBriefVersion is grounded by exactly one verified InvestigationSynthesisVersion owned by the same Investigation; direct Claim/Evidence references are a frozen provenance subset, not a second creation path. It has typed Fact, origin-labelled Synthesis, PM Judgment and Recommendation blocks; deterministic output may never be labelled AI. Exact-version readiness is an immutable review record. PRD Research Input is a stateless preview and a terminal immutable BriefExport bound to one DecisionBriefVersion plus selection/reference/render digests; it is never an editable sibling document or generic Deliverable.

## Consequences

Architecture modules, database relationships, OpenAPI resources, generated client enums and quality gates must use this vocabulary. A Run failure does not fail the Investigation automatically. Changing a Claim, synthesis or Brief creates a new immutable version; review outcomes append exact-version records. Future output formats may render from DecisionBriefVersion but cannot introduce a parallel decision object without a new ADR.
