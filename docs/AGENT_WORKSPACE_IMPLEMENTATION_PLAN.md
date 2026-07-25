# Agent Workspace Implementation Plan

> Historical plan only. PokieQuant no longer exposes the Glint Investigation
> workspace as a supported product route, and its dedicated fixture-state
> selector and E2E contract have been retired. Current implementation planning
> is governed by `docs/POKIEQUANT_CAPABILITY_INVENTORY.md`.

## Delivery strategy

The redesign is split into three stacked, independently reviewable frontend PRs. None changes backend graph behavior, review semantics, or database contracts.

## UI PR 1 — Agent Workspace Shell

Branch: `codex/phase31-agent-workspace-ui`
Base: `codex/phase31-pr0-scope-cleanup`

Deliverables:

- Product/design documents and current-UI audit.
- Pure `agent-presentation.ts` projection from Investigation domain objects to product language.
- Agent Header, Plan Rail, Activity Feed, Action Center, Artifact Card, Run Inspector, and compact segments.
- Ready, Running, Waiting Review, and Completed fixture states visibly labeled `Imported Demo Fixture`.
- Workbench integration without placing presentation parsing inside `Workbench.tsx`.
- Unit tests for status, steps, activity, pending actions, scope, mode, completed/failed plans, and no fake usage/progress.
- Focused E2E comprehension checks and four 1440×960 real-app screenshots.

Implementation sequence:

1. Audit current Investigation layout, state sources, review actions, responsive behavior, and tokens.
2. Freeze copy, information architecture, and state matrix.
3. Build and test the pure presentation model.
4. Add a test-only fixture-state selector; never expose a production selector. (Retired with this historical surface.)
5. Implement the shell components in `features/agent/`.
6. Replace the default Investigation detail composition while reusing existing API actions.
7. Add E2E state assertions and screenshot capture.
8. Run existing quality gates and write an acceptance record.

Rollback boundary: switching Investigation detail back to the previous component removes the shell without altering domain/API contracts.

## UI PR 2 — Evidence and Finding Review

Precise scope:

- `EvidenceReviewWorkspace`, queue, detail, and immutable Source Viewer composition.
- Supporting/Opposing/Neutral/Reviewed/Rejected grouping.
- Only existing `Valid`, `Weak`, and `Reject` mutations are active.
- Finding Review Workspace with supporting/opposing evidence map and source links.
- Existing `Verify` and `Reject` finding mutations, with explicit Investigation-scoped verification copy.
- J/K selection, Enter open, E/F entry, Command+Enter primary review action, and Escape return behavior.
- Component tests and E2E from evidence source open through finding verification.

Excluded: no backend review enum changes, Wrong stance/Duplicate/Not independent actions, scope expansion, or new retrieval.

Rollback boundary: review workspaces are route/view-state composition over the existing review APIs.

## UI PR 3 — Synthesis and Completion

Precise scope:

- Structured synthesis presentation mapped only from Executive Summary, Business Implications, and Limitations.
- Agent draft, Human-edited, Verified, and Rejected state treatment.
- Existing Save revision, Verify, and Reject actions; unsupported “Request more evidence” remains explanatory, not clickable.
- Completed Agent state and verified synthesis → Decision Brief handoff.
- Contextual Agent Workspace Command Palette commands and final keyboard shortcuts.
- Full governed E2E through Decision Brief creation and version-bound export handoff.

Excluded: no invented affected-user, counter-evidence, action, or metric fields; no automatic Decision Ready or export.

Rollback boundary: synthesis/result composition can be removed without reverting PR 1 shell or PR 2 reviews.

## Technical constraints

- Domain objects remain unchanged for presentation needs.
- React components consume `AgentSessionPresentation`; they do not parse raw event strings.
- Unknown events degrade safely to generic product copy with technical data behind Advanced.
- Test fixtures are selected only by the fixture server environment and are always visibly disclosed.
- CSS extends the existing four-pixel grid, typography, color tokens, focus treatment, dark mode, and reduced-motion behavior.
- No percentage progress, hidden reasoning, raw prompts/provider responses, full source bodies, secrets, or unredacted errors appear in the default workspace.

## Verification plan

Required repository gates:

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
GLINT_E2E_API_MODE=fixture pnpm test:e2e
./scripts/verify_phase2.sh
./scripts/verify_phase3_quality.sh
./scripts/verify_tauri_runtime.sh
```

Visual acceptance uses Ready, Running, Waiting Review, and Completed fixture screenshots at 1440×960. Each must show the decision question, authenticity/fixture disclosure, status, scope, mode, plan, current action, human gate or completion handoff, and no private paths/tokens.
