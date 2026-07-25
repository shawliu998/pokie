# Asset provenance

## Qurio V1 final accepted live UI proof — 2026-07-24 18:32:09

These six 1440×960 PNG files are the accepted retained UI E2E from the live Kraken/DeepSeek session
`.run/v1-kraken-deepseek-20260724-183209`. They were captured by reopening the retained SQLite
database in read-only mode through the API and Mac UI, with no worker or model call. The database
SHA-256 remained exactly `9bc9986ba81496a14c862a7b23837bd8266b4766d73c2177578182c0569d90c0`.

- `pokiequant/v1-final-183209-01-data-1440x960.png` — Data workspace with Kraken Spot BTCUSD `4h`, 548 closed bars.
- `pokiequant/v1-final-183209-02-ledger-repair-1440x960.png` — Decision Ledger showing the first Candidate C create rejected and the corrected call accepted.
- `pokiequant/v1-final-183209-03-analysis-selection-1440x960.png` — Analysis with final train ranking C/B/A and structured selection of B via `robustness_override` / `minimum_trade_evidence`.
- `pokiequant/v1-final-183209-04-holdout-revise-1440x960.png` — Sealed holdout failure for B and retained `revise_research` next step.
- `pokiequant/v1-final-183209-05-e0-export-1440x960.png` — E0 JSON evidence export dialog.
- `pokiequant/v1-final-183209-06-history-reopen-1440x960.png` — History reopen of the same Run identity.

SHA-256 hashes:

- `f1a47b5b59c169a9ce0c52b8e8a215ba83cccefc505b22c12f1a1f7736bf6ac1`
- `a8bbdab7e4f80607296221b96cee5f17d02a30d3ffd9b1f8b160b46778f6a700`
- `41d3c1c39d6c4257073f518da2e098fc8274d9568eec100e281fe2d97e703814`
- `b87d31ecb86d2446d8d8390f3382462a71413446dc57337f2bc65fea13140c71`
- `0e0fe676963267a03cc8c42cddb0748ad7086674497d6a30c53adf286dcef5ab`
- `253c94305f57f872b8fc739ba05efb121b5bcfedea4c389c2dbb8afde9f1c708`

These captures are evidence of the bounded connector/model/workflow boundary, not of
profitability, general model reliability or production readiness.

## Qurio P1-C golden mainline captures

These seven PNG files were captured on 2026-07-24 from the actual Qurio React
workbench connected to the deterministic loopback fixture API:

- `pokiequant/p1c-01-data-1440x960.png`
- `pokiequant/p1c-02-plan-approval-1440x960.png`
- `pokiequant/p1c-03-live-ab-1440x960.png`
- `pokiequant/p1c-04-observation-to-c-1440x960.png`
- `pokiequant/p1c-05-report-json-1440x960.png`
- `pokiequant/p1c-05-report-json-1024x960.png`
- `pokiequant/p1c-06-history-reopen-1440x960.png`

They cover Data, plan approval, live A/B evidence, Observation-to-C adaptation,
final JSON evidence export at 1440×960 and 1024×960, and historical report
reopen. The six desktop captures are 1440×960, the responsive export capture is
1024×960, and all seven files have distinct content hashes.

The BTCUSDT `4h` data and Agent progression are deterministic fixtures. These
captures prove the implemented UI path, retained identities and responsive
viewport behavior; they are not evidence of live Binance/Kraken/DeepSeek
reliability, strategy profitability or discovered alpha.

## Historical Glint captures — 2026-07-16

These five PNG files were captured on 2026-07-16 at 1440×960 from the real
Glint React workbench. The
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

The former capture-only Playwright workflow has been retired with the Glint
Investigation surface. The PNG files remain historical provenance assets and
are not part of current Qurio browser acceptance.
