# Portfolio asset provenance

These five PNG files were captured on 2026-07-16 at 1440×960 through
`apps/mac/e2e/portfolio-assets.spec.ts` from the real Glint React workbench. The
workbench was connected to an isolated local Compose runtime containing the
real API, worker, Postgres/RLS database, Redis, and object store.

The input was `fixtures/demo/ai-coding-agents-interviews.csv`, visibly labelled
**Imported Demo Fixture**. It is synthetic imported demo data, not private
customer content, a captured public payload, or live GitHub/RSS data. The
verified run produced 2 supporting and 1 opposing Evidence records, a
`decision_ready` Decision Brief, and a terminal digest-bound Markdown export.
No LLM or model egress was used.

Review checks:

- dimensions are exactly 1440×960;
- all five captures came from the same isolated runtime and identity;
- authenticity labels remain visible;
- no access token, credential value, private path, developer tool, terminal, or
  private customer data is visible;
- the Monitoring credential field shows only the documented opaque reference
  `env://github_token`, never a secret value.

The capture workflow is opt-in (`GLINT_CAPTURE_PORTFOLIO=1`) and requires the
external demo API identity; the ordinary fixture and CI E2E runs skip it.
