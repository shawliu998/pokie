# Glint

Glint is an evidence-backed intelligence workbench for product managers responsible for competitor and user research.

The implementation follows the reviewed contracts in [`docs/`](./docs/README.md). The first fixed output is a version-bound Product Decision Brief; PRD Research Input is an export view, not a second domain object.

## Delivery status

- Phase 0 — contracts and risk validation: complete (`Conditional Go`).
- Phase 1 — Seed/Imported CSV walking skeleton: deterministic local acceptance complete.
- Phase 2 — GitHub/RSS collection contracts, scheduler, collected lineage and Owner loop: deterministic local acceptance complete.
- Phase 3+ — model-assisted research and collaboration: out of scope for the current implementation.

The combined P1/P2 gate exited `0` on 2026-07-16 with no failed layers. Live GitHub/RSS calls were not authorized and were therefore skipped by policy; this is not a production, pilot, or GA claim. See [P1/P2 acceptance](./docs/PHASE1_P2_ACCEPTANCE.md).

## Required vertical path

```text
Monitoring / Imported CSV
→ Inbox Signal
→ Investigation
→ Evidence and ClaimVersion review
→ verified InvestigationSynthesisVersion
→ singly grounded DecisionBriefVersion
→ DecisionReady review
→ version-bound Markdown export
```

Phase 2 extends the same path with scheduled GitHub and RSS collection; it does not create a parallel research or decision model.

## Runtime boundaries

- React/Tauri is a contract client; it does not import database or worker internals.
- FastAPI/domain services own writes and lifecycle transitions.
- Workers consume typed jobs; downstream import jobs accept only terminal `ImportManifest` identifiers.
- Connectors return normalized source content and health. They cannot create Signals, Claims, syntheses, or Decision Briefs directly.
- Seed, imported, collected, deterministic, and model-generated data must remain visibly distinguishable.

## Verification

Remote CI: [Glint verification workflow](https://github.com/shawliu998/Glint/actions/workflows/verify.yml) · [P2.5 green baseline](https://github.com/shawliu998/Glint/actions/runs/29468568771)

Run the deterministic local P1/P2 acceptance gate from the repository root:

```bash
./scripts/verify_phase2.sh
```

The script verifies locked dependencies, lint/type checks, tests, Docker Compose/Postgres/RLS, the collected Owner loop, Tauri native runtime, and fixture/API E2E. Networked live smoke remains opt-in with `GLINT_ENABLE_LIVE_SMOKE=1` and requires separately configured credentials.
