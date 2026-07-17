# Agent Workspace Copy

This document is the source of product-facing Agent Workspace language. Internal identifiers remain available only in Advanced disclosure.

## Status labels

| Condition | Label | Supporting copy |
| --- | --- | --- |
| No run | Ready to start | Approved scope is frozen. Review the plan before starting. |
| Queued | Preparing | Glint is confirming the approved scope for this run. |
| Running | Running | Glint is working within the frozen Investigation scope. |
| Human review pending | Waiting for review | Agent proposals are ready for an authorized human to review. |
| Waiting for structured input | Needs input | The run paused safely and cannot continue without an authorized action. |
| Verified result path | Completed | The governed research workflow is complete for this Investigation. |
| Failed | Failed | The Agent stopped safely. Review retained work and diagnostics before retrying. |
| Cancelled | Cancelled | This run was cancelled. Persisted artifacts remain visible. |

## Research mode

- Deterministic research
- Model-assisted research
- No model egress
- Model egress approved for this run

Do not display raw enum copy such as `generation_method=model`.

## Plan steps

| Internal label | Product label | Description |
| --- | --- | --- |
| `validate_manifest` | Confirming approved scope | Checks the frozen question, source boundary, content versions, window, and configured limits. |
| `bound_content` | Preparing approved sources | Makes only the approved immutable content available to this run. |
| `propose_evidence` | Analyzing evidence | Proposes relevant passages from the approved source set. |
| `validate_evidence` | Verifying citations | Checks proposal references against immutable content versions. |
| `propose_claim` | Drafting findings | Proposes findings supported by the current evidence set. |
| `require_human_review` | Waiting for your review | Pauses before any evidence, finding, or synthesis can be treated as reviewed. |

## Human gates

- Review evidence
- Review findings
- Review synthesis
- Approve decision brief

Supporting governance copy:

> Agent outputs remain proposals until an authorized human completes the relevant review.

> Verification means the finding is sufficiently supported for this Investigation. It is not a universal truth guarantee.

## Current action templates

- Glint is confirming the approved scope.
- Glint is preparing approved sources.
- Glint is analyzing evidence.
- Glint is verifying citations.
- Glint is drafting findings.
- Glint is waiting for your review.
- The Agent stopped safely.

Purpose templates use factual nouns and counts only:

- `{count} immutable content versions are pinned to this run.`
- `{count} evidence proposals are persisted.`
- `{count} findings are ready for human review.`
- `No action is needed from you right now.`
- `Your review is required before the workflow can continue.`

## Activity projection

| Event | Title | Safe summary |
| --- | --- | --- |
| `run.queued` | Scope confirmed | The immutable run input was accepted. |
| `run.started` | Sources prepared | Approved sources were bounded for this run. |
| `evidence.proposed` | Evidence proposed | Candidate evidence was persisted for review. |
| `evidence.validated` | Citation validation completed | Evidence references were checked against immutable content. |
| `claim.version_proposed` | Findings proposed | Findings were persisted for human review. |
| `run.completed` | Agent paused for review | The run completed its proposal work. Human review remains required. |
| `run.failed` | Agent stopped safely | The run ended without bypassing review or persistence rules. |
| `run.cancelled` | Run cancelled | The run stopped at the user’s request. Persisted artifacts remain visible. |
| unknown | Run activity recorded | A safe run event was recorded. |

The original safe event message may be shown as secondary copy. Raw event name, sequence, and trace reference belong in Advanced disclosure.

## Artifact labels

- Source Scope
- Evidence Proposal
- Finding Proposal
- Synthesis Draft
- Decision Brief
- Run Failure
- Human Review

Origin and state labels:

- Agent proposal
- Deterministic proposal
- Model proposal
- Verified evidence
- Human-reviewed finding
- Agent draft
- Human-edited
- Verified
- Rejected
- Decision artifact

Do not use “AI generated” as the only provenance label.

## Action Center

Evidence:

> `{count} evidence proposals need your review`

Action: `Review evidence`

Findings:

> `{count} findings are based on reviewed evidence`

Action: `Review findings`

Synthesis:

> `The Agent drafted a synthesis from verified findings`

Action: `Review synthesis`

Failure:

> `The Agent stopped safely`

Waiting without a response API:

> `The run is waiting for an authorized action. This version of Glint cannot accept a free-text continuation.`

## Scope and egress

Scope summary:

- `{count} approved source/source connections`
- `{count} immutable content version/versions`
- `{start} – {end}` when known

Egress disclosure:

> `Model egress approved for this run`

> `Will be sent: the Decision Question and selected excerpts from the approved scope.`

> `Will not be sent: workspace credentials, approval state, unrelated workspace content, or local file paths.`

Missing provider/model values must say `Unavailable`, not infer a provider.

## Budget

Preferred limit-only copy:

> `Budget limit: $4.00 · 15 min`

Do not show “$0.00 of $4.00” as proof of measured spend when the API only guarantees a configured maximum.

## Empty states

No Investigation:

> `Investigate an important Signal`

> `Glint can organize approved sources, propose evidence and findings, and pause for your review before creating a Decision Brief.`

No evidence:

> `No evidence proposals yet`

> `The Agent has not completed evidence analysis for this run.`

No opposing evidence:

> `No opposing evidence is currently attached to this Investigation. This does not mean opposing evidence does not exist.`

## Fixture disclosure

All demonstration scenarios use the visible label:

> `Imported Demo Fixture`

Never label fixture data as Live Provider, Live Connector, or real-time customer data.
