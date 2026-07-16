# ADR 0002: Bind Evidence to immutable ContentVersion

- Status: Accepted
- Date: 2026-07-15

## Context

External posts, feeds and imported files may change, disappear or be reparsed. A mutable content record cannot support a reproducible ClaimVersion, Investigation synthesis, Product Decision Brief or PRD export.

## Decision

Model ContentItem as a logical identity and ContentVersion as an append-only captured representation. Evidence is an immutable anchor to exactly one ContentVersion plus quote offsets/digest; EvidenceReview appends its decisions. Revise creates an immutable ClaimVersion; append-only, same-Investigation ClaimEvidence links it to Evidence. ClaimReview pins exact ClaimEvidence/EvidenceReview IDs and a digest. InvestigationSynthesisVersion pins verified ClaimVersion plus verifying ClaimReview IDs/digests, while SynthesisReview appends its exact-version decision. Every DecisionBriefVersion is grounded by exactly one verified same-Investigation synthesis, while its blocks pin a provenance subset of ClaimVersion, Evidence and ContentVersion references. DecisionBriefReadinessReview records readiness and DecisionBriefFreshnessRecord records later current/stale assessment for one exact Brief version. A successful BriefExport pins that ready/current version plus selection/reference/render digests. row_version is only optimistic concurrency, never domain history. Corrections and source edits create new versions/reviews/freshness records; reviewed conclusions are reviewed again rather than silently altered.

## Consequences

Storage and retention requirements increase, and UI must distinguish current content from cited historical content. In return, citations can be checked exactly, Research Runs are reproducible, and source deletion/retention changes can be represented without destroying audit lineage.
