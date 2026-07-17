# PokieQuant Reference and Reuse Audit

Status: Phase 0 provenance and license gate

Audit date: 2026-07-17 (Asia/Shanghai)

## 1. Conclusion

PokieQuant may reuse the inherited Glint repository’s first-party architecture and code patterns within this history-preserving fork. It may use Apache ECharts only after a dependency slice pins the exact version, verifies the published license/artifact, updates the lockfile and notices, and passes license/security tests.

Codex, Claude Code, TradingView, and Grok Build are product references only. No source, logo, proprietary icon, brand asset, unique copy, or unpublished design file may be copied from them.

No Spark Agent or PokieTicker code is approved for migration:

- the local SparkAgent candidate is an instruction/memory scaffold, not the required execution runtime, and has no license or remote;
- no PokieTicker repository, immutable commit, file list, or license was supplied or found;
- therefore PokieTicker capabilities are roadmap requirements only and must be labeled **pending repository/commit/license review**.

## 2. Classification model

Every reference belongs to exactly one of these classes:

| Class | Permitted use | Required evidence |
| --- | --- | --- |
| First-party inherited source | reuse/refactor under repository authority | repository, commit, history, owned paths, regression tests |
| Reviewed open-source dependency | link/import package under its terms | exact version, resolved artifact, SPDX/license text, notice obligations, security review |
| External source migration | selected file-level migration only | source repo, immutable commit, file paths, license, modifications, notices, security/provenance review |
| Closed-source product reference | product-pattern inspiration only | written boundary; no copied code/assets/copy |
| Unknown or unlicensed | no code migration | obtain affirmative license/authority before use |

Public visibility is not a license. The absence of a repository license must not be interpreted as open-source permission.

## 3. Glint baseline audit

| Item | Evidence |
| --- | --- |
| Source remote | `https://github.com/shawliu998/Glint.git` |
| Baseline branch | `codex/phase31-agent-workspace-ui` |
| Baseline/tag commit | `eb9a4be58c4a16b790d0b7568735c53a3627fe51` |
| Local baseline tag | `glint-agent-workspace-baseline` |
| History handling | fetched/checked out with history; no source export or rewrite |
| Root license file | none found in the audited worktree |

Because no root `LICENSE`, `COPYING`, or `NOTICE` for the first-party repository was found, this audit does **not** classify Glint itself as open source. Glint is treated as inherited first-party source made available within the authorized repository/fork task. Before external distribution, commercialization, or accepting third-party contributions, the repository owner must establish an explicit project license and confirm that it is compatible with dependency obligations and upstream ownership.

### Directly reusable Glint responsibilities

| Area | Concrete audited seam | PokieQuant treatment |
| --- | --- | --- |
| Resizable workbench | `apps/mac/src/features/workbench/WorkbenchLayout.tsx` | reuse panel/collapse/persistence behavior |
| Agent composition | `apps/mac/src/features/agent/AgentWorkspace.tsx` and sibling components | generalize component anatomy; feed Quant presentation models |
| Pure projection | `apps/mac/src/features/agent/agent-presentation.ts` | reproduce the pure-projection boundary in `quant-presentation.ts` |
| Run stream | `apps/mac/src/hooks/useRunStream.ts`, `apps/mac/src/api.ts` | reuse cursor, duplicate suppression, reset, reconnect pattern |
| Contract wire mapping | `packages/contracts/events/run_events.py` | add one Quant persistence-to-wire map and secret-free payload union |
| API policy kernel | auth/errors/presenters/research service patterns | reuse workspace scope, RLS, idempotency, optimistic concurrency, audit |
| Worker kernel | worker main, leases, `WorkerDomainAdapter` style | reuse claim/lease/fence/heartbeat pattern behind a Quant port |
| Test system | Vitest, Playwright, fixture API, verify scripts | add Quant cases and additive gate; do not weaken existing gates |

### Glint elements requiring generalization

- `GlintApi`, `GLINT_*`, `VITE_GLINT_*`, `@glint/*`, app/bundle names: controlled identity migration only after Quant modules exist;
- `AgentSessionPresentation`: extract domain-neutral primitives or create a parallel `QuantSessionPresentation`;
- `AgentWorkspace` props: remove direct Investigation/Evidence/DecisionBrief assumptions for shared use;
- `Workbench.tsx`: integrate new destinations without adding raw state parsing;
- `domain.ts` and `api.ts`: leave Glint types/commands intact; add separate Quant modules and extract only generic transport.

### Glint elements not reusable as Quant domain

The following semantics remain Glint product intelligence and must not be renamed into finance:

- Signal, Watchlist, detection score, and source scheduling;
- Investigation and InvestigationScopeVersion;
- Evidence/EvidenceReview;
- Claim/ClaimVersion/ClaimReview;
- InvestigationSynthesis and review;
- DecisionBrief, readiness, freshness, and PRD export;
- GitHub/RSS collection, CSV import consent/finalization, and model-research provider behavior.

They may remain in the repository, but they are outside the PokieQuant main path and Phase 0 Quant persistence model.

## 4. Current third-party dependency boundary

`THIRD_PARTY_NOTICES.md`, `uv.lock`, `pnpm-lock.yaml`, and the Tauri Cargo lock are the audited dependency records. The existing notice includes MIT, Apache-2.0, BSD-3-Clause, dual MIT/Apache-2.0, and the existing unmodified `psycopg`/`psycopg-binary` LGPL-3.0-only package use.

The repository policy blocks default addition of:

- GPL or AGPL code;
- SSPL or Commons Clause packages;
- non-commercial or research-only terms;
- unknown/custom terms without an explicit review.

This policy applies to source snippets, generated components, vendored files, model outputs that reproduce source, fonts, icons, datasets, and packages—not only package-manager dependencies.

## 5. Apache ECharts proposal

Current audited state:

- `echarts` is not present in `apps/mac/package.json` or `pnpm-lock.yaml`;
- no ECharts notice exists in `THIRD_PARTY_NOTICES.md`;
- therefore ECharts is not currently part of PokieQuant and must not be described as implemented.

The requirements propose `echarts@6.1.0` under Apache-2.0 for candlesticks, volume, equity/drawdown, and sensitivity charts. The market-workspace implementation slice must perform all of these atomically:

1. verify the exact npm artifact, upstream repository, version, and license text;
2. pin `echarts` to exactly `6.1.0`, with no caret/range;
3. update `apps/mac/package.json` and `pnpm-lock.yaml`;
4. add the notice/attribution required by the verified artifact;
5. review transitive dependency licenses and security advisories;
6. sanitize or avoid HTML in tooltip/formatter paths;
7. add license, bundle, tooltip, and rendering tests.

If any verified fact differs from this proposal, stop the slice and update the reference audit before merging.

## 6. Spark Agent audit

Audited local candidate: `/Users/a1-6/Documents/SparkAgent/2026-07-15-1812`

| Fact | Finding |
| --- | --- |
| Commit | `259ed60847de5771bfb21ceecd066b45016ed9f6` (`Initialize workspace`) |
| Remote | none configured |
| License/notice | none found |
| Content | `evolve-agent` instructions/memory scaffold (`AGENTS.md`, `KNOWLEDGE.md`, `knowledge/`, `notes/`) |
| Required runtime features | no Python sandbox, Jupyter runtime, immutable payload executor, artifact hashing service, or recovery engine found |
| Migration decision | prohibited for Phase 0 |

The name “Spark Agent” in the product requirements does not establish that this local directory is the intended runtime. Phase 0 may define only a `QuantExecutionRuntime` port. A future Spark migration requires the actual repository, immutable commit, license, owned file list, architecture/security review, and sandbox threat model.

## 7. PokieTicker audit

No PokieTicker working tree was found locally, and no remote, immutable commit, license, or file list was supplied. Consequently, this document makes no claim that PokieTicker code is available, compatible, or migratable.

The following are capability candidates only:

- symbol search;
- OHLCV/candlestick data adapter;
- news/event timeline and chart markers;
- imported market-data fixtures and snapshot conventions;
- interval-event explanation and similar-history lookup.

Required label in all planning documents:

> PokieTicker migration is pending repository/commit/license review.

Before any code or data migration, record:

```text
source repository
immutable commit/tag
source and destination file paths
license and copyright owner
dependency licenses
data license/redistribution rights
modifications made
required NOTICE/attribution
security and privacy review
tests proving behavior/provenance
```

Until that record is approved, implement only original PokieQuant contracts and synthetic/imported fixtures. Do not fork or merge an assumed PokieTicker backend.

## 8. Closed-source product references

| Reference | Permitted structural inspiration | Prohibited |
| --- | --- | --- |
| OpenAI Codex-class task console | persistent tasks, background status, cancel/retry/review, outcome-oriented composer, command palette | name, branding, proprietary source/assets/icons/copy |
| Claude Code | Ask/Plan/Auto-style mode clarity and explicit permission gates | brand UI, source, exact copy, internal permission implementation |
| TradingView | symbol/interval toolbar, chart/report split, tabs, dense market hierarchy, resizable panels | widget as core implementation, source, logo, branded colors/icons/copy |
| Grok Build | workflow/reference concepts only where documented | any source/assets/copy or implied integration |

The replication boundary is information architecture, interaction model, workflow structure, state expression, and density—not pixel copying. PokieQuant must have its own name, wording, visual tokens, icons, and component implementation.

## 9. Data provenance and financial-result boundary

Market data and event/news data can carry separate licenses and redistribution restrictions even when adapter code is permissively licensed. A future data adapter review must record provider terms, redistribution/storage limits, attribution, permitted derived artifacts, retention, rate limits, and whether screenshots/reports may include the data.

Phase 0 avoids this uncertainty by using only bundled deterministic fixtures labeled `Synthetic Demo Fixture` or `Imported Demo Fixture`. Fixture provenance must include generator/source, schema version, date range, symbol, digest, and an explicit statement that metrics are demonstration values.

## 10. Migration ledger template

Append one row per future external migration; do not group an entire repository under a single approval.

| Status | Source repo | Commit | Source paths | Destination paths | License | Modification | Notice/data obligations | Reviewer/date |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Pending | PokieTicker (not supplied) | not supplied | not supplied | future adapters only | unknown | none | unknown | required before use |
| Rejected for Phase 0 | local SparkAgent scaffold | `259ed608…` | instruction/memory files | none | none found | none | cannot migrate | audit 2026-07-17 |

## 11. Merge gate

Reject a change when any of the following is true:

- it introduces source/data without repository, commit/version, and license evidence;
- it copies a closed-source visual asset, unique copy, or proprietary implementation;
- it labels PokieTicker/Spark code as migrated without the required audit;
- it adds ECharts without exact pin, lockfile, notice, and security/license tests;
- it adds blocked/unknown terms without explicit owner approval;
- it removes an existing notice or quality gate;
- it describes fixture financial data as live, real, or performance evidence.
