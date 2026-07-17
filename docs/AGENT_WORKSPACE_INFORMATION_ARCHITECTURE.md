# Agent Workspace Information Architecture

## Place in the product

The global information architecture remains unchanged:

```text
WORK
  Inbox
  Investigations
  Decisions

MANAGE
  Monitoring
```

Agent Workspace replaces the content structure of Investigation detail only. The application Sidebar and Investigation list remain stable.

## Desktop structure (> 1200px)

```text
Investigation detail
  Agent Header
    Decision Question
    Status · Research Mode · Imported Demo Fixture (test-only, when applicable)
    Approved Scope · Model Egress · Budget Limit · Valid Controls
  Workspace body
    Agent Plan Rail (220–260px)
      Research plan
      Human gates
      Output handoff
    Work Canvas (flexible)
      Current action
      Action Center (conditional)
      Activity Feed
      Artifact previews
    Inspector (320–380px)
      Selected Run / Artifact context
      Scope and provenance
      Advanced technical disclosure
```

The Inspector is part of the shell in UI PR 1 and defaults to Run context. Item-driven Source/Evidence/Finding/Synthesis/Decision inspector modes are completed in later UI PRs.

## Medium structure (960–1200px)

The Plan Rail and Work Canvas remain side by side. Inspector content moves below the canvas as an inline drawer-like disclosure so the plan never loses context.

## Compact structure (< 960px detail width)

The Agent Workspace exposes a process-ordered segmented navigation:

```text
Plan | Activity | Review | Result
```

- Plan contains the bounded research steps and human gates.
- Activity contains current action and safe event projection.
- Review contains the Action Center and proposal previews.
- Result contains completed synthesis/Decision Brief handoff context.

Only one segment is shown at a time. The application-level compact list/detail behavior remains unchanged. Single-key shortcuts do not fire while focus is in an editable control.

## Header hierarchy

1. Decision Question is the page title and primary goal.
2. Business status answers whether Glint is preparing, running, waiting, complete, failed, or cancelled.
3. Research mode states deterministic or model-assisted operation.
4. Scope summary states source connections, immutable versions, and time window when known.
5. Egress disclosure appears only when run-scoped cloud-model use is authorized.
6. Budget shows configured limits. Used cost is omitted unless trustworthy usage is available.
7. Controls are conditional: Cancel for cancellable runs, Retry for failed/cancelled runs, and Decision Brief handoff only when the verified-synthesis contract permits it.

## Plan hierarchy

Agent-owned steps:

```text
Confirming approved scope
Preparing approved sources
Analyzing evidence
Verifying citations
Drafting findings
```

Human-owned gates:

```text
Review evidence
Review findings
Review synthesis
Approve decision brief
```

System validation and Agent work use different markers from human gates. Status values are Pending, Running, Completed, Waiting, Failed, and Skipped. Progress is expressed only as a count of real discrete steps.

## Work Canvas hierarchy

### Current action

Always present. It names the current business step, explains its purpose, reports truthful input/artifact counts, and says whether the user must act.

### Action Center

Visible only when a real human action is available or a run has stopped safely. It contains one primary next action and concise governance copy.

In UI PR 1, Review evidence and Review findings route to the existing review surfaces within Investigation detail behavior. The full three-column review workspaces belong to UI PR 2.

### Activity

Chronological safe projection of Run Events. Items may expose technical event names only in their own disclosure. Raw prompt/provider output, source bodies, secrets, and chain of thought are never shown.

### Artifact previews

Important persisted outputs share one card anatomy: artifact type, origin, review state, concise content, related-object count, and a valid action. UUIDs are excluded from the default card.

## Review mode boundary for UI PR 1

UI PR 1 provides entry points and compact proposal previews. It intentionally preserves existing evidence, finding, and synthesis review actions rather than introducing a partially implemented new review workspace.

UI PR 2 will replace those transitional review surfaces with:

```text
Evidence Queue | Evidence Detail | Source Viewer
Findings Queue | Finding Detail | Evidence Map
```

## Inspector content

Default Run Inspector includes status, mode, scope, budget limit, current step, provider/model when applicable, connection status, and timestamps available from events.

Advanced disclosure includes Run ID, Scope Version ID, Graph Version, latest sequence, trace reference, prompt references, and exact internal node only when those values exist. It defaults closed.

## Empty and exceptional states

- Ready: frozen goal and scope, expected plan, and Start Investigation action when a real start operation is available.
- No artifacts yet: explain that analysis has not completed; never show an empty tab.
- Waiting for input without a response API: explain the reason and offer Cancel only.
- No opposing evidence: explicitly warn that absence in the current Investigation does not prove absence in the world.
- Failed: safe summary, completed steps, retained artifacts, Retry when supported, Cancel when valid, and Advanced diagnostics.
- Offline: retain readable state, label cached content, and disable writes, runs, source fetches, and SSE-dependent actions.
