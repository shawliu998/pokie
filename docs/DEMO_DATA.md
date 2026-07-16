# Glint Demo data profile

The `demo` seed profile creates the portfolio walkthrough through the same HTTP commands,
database contracts, and production worker jobs used by the normal runtime:

```text
Imported Demo Fixture → ContentVersion → Explainable Signal → Human Triage
→ Investigation → ResearchRun worker → Evidence and counter-evidence reviews
→ Claim review → Synthesis review → Decision Brief → DecisionReady
→ terminal PRD Research Input Markdown export
```

It creates or selects:

- Workspace: `Glint Demo`
- Project and Watchlist: `AI Coding Agents`
- Entities: Cursor, Claude Code, Codex, Windsurf, and Zed
- Topics: Permissions, Pricing, Reliability, Context, Enterprise, Migration, and Integrations

## Authenticity boundary

The stable input is [ai-coding-agents-interviews.csv](../fixtures/demo/ai-coding-agents-interviews.csv),
an **Imported Demo Fixture** containing synthetic, curated interview excerpts. It is not Live data,
not a captured copy of private customer material, and must be displayed with API authenticity
`imported`. Its reviewed metadata and a discovery-only public source catalog live in
[ai-coding-agents-manifest.json](../fixtures/demo/ai-coding-agents-manifest.json).

The GitHub and RSS catalog is not fetched by this profile and does not substantiate a Live claim.
Live connector verification remains a separate, opt-in workflow.

The deterministic research worker reads three imported `ContentVersion` records. The profile
requires at least two supporting Evidence records and at least one opposing Evidence record before
it will continue. All Evidence, Claim, synthesis, readiness, and export transitions still require
their normal API reviews; the seed does not insert terminal business rows directly.

## Run and verify

Start the normal API, worker, database, and object-store stack, then run:

```bash
.venv/bin/python -m scripts.seed_runtime \
  --profile demo \
  --auth-output /tmp/glint-demo-auth.json \
  --demo-output /tmp/glint-demo-flow.json

.venv/bin/python -m scripts.verify_demo_flow /tmp/glint-demo-flow.json
```

`--auth-output` is the existing sensitive runtime credential handoff and must remain a private,
temporary file. `--demo-output` is deliberately redacted: its schema permits only identifiers,
counts, statuses, and SHA-256 hashes. It never stores fixture text, rendered Markdown, source
content, local paths, access tokens, or other credentials.

The default `acceptance` profile remains unchanged and is selected when `--profile` is omitted.
