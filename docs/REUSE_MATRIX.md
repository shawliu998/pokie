# Open Source Reuse Matrix

Evidence verification completed: `2026-07-15T07:45:20Z` (UTC).

Scope: Glint Phase 0 reuse decisions only. This document does not authorize copying third-party code into this repository, except for the explicitly scoped shadcn/ui generated component path with preserved notices and provenance.

## Evidence Rules

1. An Approved dependency must have an exact selected version, an official registry or release URL, a package digest or upstream commit/tag, and a verification timestamp.
2. License conclusions use a version-bound artifact or a source file pinned to an immutable commit. A floating `main`, `master`, or `dev` URL is not license evidence.
3. Qualification is dimension-specific: `artifact_use`, `source_provenance`, and `runtime_deployment` are reported separately. `Needs verification` blocks only the named dimension and cannot be used to infer permission there; an independently Approved artifact path remains usable within its narrower stated scope.
4. Prefer package dependencies over copied source. shadcn/ui is the only planned source-level reuse path; generated local components must record the CLI version, upstream source, and notices.
5. GPL, custom non-commercial, unclear, or identity-ambiguous projects are not reusable in Glint core code. They may be studied for product or architecture ideas only.
6. Pin exact versions in manifests and lockfiles. Upgrades require a dependency PR with release-note review, license scan, security scan, and the relevant quality gates.
7. Dependencies that collect, crawl, execute shells, automate browsers, or invoke model tools must be isolated behind an adapter and threat-modeled before production use.

## Decision Matrix

| Project | Upstream / docs | License conclusion | Approved reuse scope | Exact baseline and evidence | Replacement cost | Artifact use decision |
|---|---|---|---|---|---:|---|
| Tauri | [repository](https://github.com/tauri-apps/tauri), [Tauri 2 docs](https://v2.tauri.app/) | MIT OR Apache-2.0 | Primary macOS desktop container, native menu/window/plugin layer | `@tauri-apps/cli@2.11.4`, `@tauri-apps/api@2.11.1`; see [Tauri evidence](#tauri) | High | Approved |
| shadcn/ui | [repository](https://github.com/shadcn-ui/ui), [docs](https://ui.shadcn.com/) | MIT | Generate selected React components into Glint's local design system, then adapt tokens and compact desktop density | `shadcn@4.13.0`; see [shadcn/ui evidence](#shadcnui) | Medium | Approved with attribution tracking |
| TanStack Table | [repository](https://github.com/TanStack/table), [docs](https://tanstack.com/table/latest) | MIT | Headless table state for Signal lists, Evidence tables, source runs, and evaluations | `@tanstack/react-table@8.21.3`; see [TanStack Table evidence](#tanstack-table) | Medium | Approved |
| Apache ECharts | [repository](https://github.com/apache/echarts), [docs](https://echarts.apache.org/) | Apache-2.0 | Trend, distribution, heatmap, anomaly-marker, and comparison charts | `echarts@6.1.0`; see [Apache ECharts evidence](#apache-echarts) | Medium | Approved |
| Tiptap | [repository](https://github.com/ueberdosis/tiptap), [docs](https://tiptap.dev/) | MIT for OSS core/editor; Pro extensions have separate commercial terms | Exact OSS npm artifacts as Product Decision Brief editor and version-bound export preview; no source vendoring | `@tiptap/core@3.27.4`, `@tiptap/react@3.27.4`; see [Tiptap evidence](#tiptap) | Medium | Approved: exact OSS package artifacts only |
| LangGraph | [repository](https://github.com/langchain-ai/langgraph), [Python docs](https://docs.langchain.com/oss/python/langgraph/overview) | MIT | Bounded ResearchRun orchestration with schema-validated proposals and persisted human checkpoints | `langgraph==1.2.9`; see [LangGraph evidence](#langgraph) | High | Approved |
| Langfuse | [server repository](https://github.com/langfuse/langfuse), [JS SDK repository](https://github.com/langfuse/langfuse-js), [Python SDK repository](https://github.com/langfuse/langfuse-python) | MIT for OSS source outside `ee/`, `web/src/ee/`, and `worker/src/ee/`; those EE paths have separate terms | Exact OSS SDK artifacts for tracing/evaluation integration; this row does not authorize a server image | `langfuse==4.14.0`, `langfuse@3.38.20`; see [Langfuse evidence](#langfuse) | Medium | Approved: exact JS/Python SDK artifacts only |
| DeerFlow | [repository](https://github.com/bytedance/deer-flow), [site](https://deerflow.tech/) | MIT | Architecture reference only: run/thread model, streaming events, tool registry, artifacts, sandbox abstractions, skills/provider config | No package selected; fixed license snapshot in [license evidence](#reference-and-blocked-license-evidence) | Medium | Reference only |
| Agent Reach | [repository](https://github.com/Panniantong/Agent-Reach) | MIT | Possible future local sidecar/connectors through a `SourceConnector` adapter only | No package selected; fixed license snapshot in [license evidence](#reference-and-blocked-license-evidence) | High | Not approved/not selected |
| TrendRadar | [repository](https://github.com/sansan0/TrendRadar) | GPL-3.0 | Product and architecture reference only: RSS, aggregation, scheduling, keyword rules, notifications | No package selected; fixed license snapshot in [license evidence](#reference-and-blocked-license-evidence) | Low for reference, high for code | Blocked for code reuse |
| BettaFish | [repository](https://github.com/666ghj/BettaFish) | Custom restricted license: learning/research only; no commercial use without written consent | Conceptual reference only: query/media/insight/report responsibilities and counter-evidence patterns | No package selected; fixed license snapshot in [license evidence](#reference-and-blocked-license-evidence) | Low for reference, high for code | Blocked for code reuse |

## Qualification Status By Dimension

This table is the authority when one project has an approved narrow path and a separate unresolved path.

| Project/path | Artifact use status | Source provenance status | Runtime deployment status | Enforced boundary |
|---|---|---|---|---|
| Tiptap `@tiptap/core@3.27.4` / `@tiptap/react@3.27.4` | Approved exact npm artifacts | Needs verification for upstream tag/commit match | Not applicable | Package install is allowed; source-level inspection, copying and vendoring are blocked until provenance closes. |
| Langfuse JS/Python SDK versions above | Approved exact SDK artifacts | Verified at fixed SDK commits/artifacts | Not applicable | SDK integration is allowed in Phase 3 within redaction/egress controls. |
| Langfuse self-host server | No artifact selected | Fixed source license boundary recorded, but not tied to a selected runtime | Needs verification | No server deployment until a release/image digest, notices, EE boundary and advisories are verified. |
| Agent Reach adapter/sidecar | No artifact selected; not approved | Fixed license snapshot only; distribution/transitive/ToS review incomplete | Needs verification | No dependency, copied code, packaged CLI or sidecar execution before the full adapter review. |
| Tauri, shadcn/ui, TanStack Table, ECharts, LangGraph | Approved at the exact versions above | Verified for the selected artifact/source relation | Phase-specific normal dependency controls | Use only at the approved scope with exact pins, notices and security gates. |
| DeerFlow / TrendRadar / BettaFish | Reference-only or blocked as stated above | Fixed license snapshots recorded | Not applicable | No code reuse outside the explicit shadcn path. |

## Approved Version Evidence

All entries in this section were checked at `2026-07-15T07:45:20Z` (UTC). Registry URLs are official package metadata endpoints and contain the recorded artifact integrity values. Release, tag, commit, and license URLs are official upstream GitHub URLs.

### Tauri

- Exact artifacts: [`@tauri-apps/cli@2.11.4` registry metadata](https://registry.npmjs.org/%40tauri-apps%2Fcli/2.11.4), published `2026-06-28T17:58:47.722Z`, integrity `sha512-R8xGtMpwyetawSqm9kYOuMmEqkhUbvcUy8n0aNXIxollKBLESUu5f4Fx+64hgASYm1H+jSWq6jCW6zqTnH6hqQ==`, registry `gitHead` [`59585e1aac2d2e3503aa1caececf3568dce51a47`](https://github.com/tauri-apps/tauri/commit/59585e1aac2d2e3503aa1caececf3568dce51a47); [`@tauri-apps/api@2.11.1` registry metadata](https://registry.npmjs.org/%40tauri-apps%2Fapi/2.11.1), published `2026-06-17T13:41:27.442Z`, integrity `sha512-M2FPuYND2m+wh5hfW9ZpSdxMPdEJovPBWwoHJmwUpysTYNHaOkVFN419m/K0LIgjb/7KU2vBgsUepJWugQCvAA==`.
- Upstream release evidence: [`tauri-cli-v2.11.4`](https://github.com/tauri-apps/tauri/releases/tag/tauri-cli-v2.11.4) points to commit [`8909f221d1515955fc843808032bdc5d62209c96`](https://github.com/tauri-apps/tauri/commit/8909f221d1515955fc843808032bdc5d62209c96); [`@tauri-apps/api-v2.11.1`](https://github.com/tauri-apps/tauri/releases/tag/%40tauri-apps%2Fapi-v2.11.1) points to commit [`6f6ab1207bb3923c2721fbc67d2fdb1c8deb0c7a`](https://github.com/tauri-apps/tauri/commit/6f6ab1207bb3923c2721fbc67d2fdb1c8deb0c7a).
- Fixed license evidence: [MIT at CLI package `gitHead`](https://github.com/tauri-apps/tauri/blob/59585e1aac2d2e3503aa1caececf3568dce51a47/LICENSE_MIT) and [Apache-2.0 at the same commit](https://github.com/tauri-apps/tauri/blob/59585e1aac2d2e3503aa1caececf3568dce51a47/LICENSE_APACHE-2.0); [MIT at the API release commit](https://github.com/tauri-apps/tauri/blob/6f6ab1207bb3923c2721fbc67d2fdb1c8deb0c7a/LICENSE_MIT) and [Apache-2.0 at the same commit](https://github.com/tauri-apps/tauri/blob/6f6ab1207bb3923c2721fbc67d2fdb1c8deb0c7a/LICENSE_APACHE-2.0).
- Reuse controls: pin exact npm versions and `Cargo.lock`; review Tauri permissions, CSP, filesystem, deep links, updater signing, shell sidecars, and plugin capabilities. The CLI registry `gitHead` and CLI release-tag commit differ, so the package integrity and recorded `gitHead` are the artifact proof; this document does not infer that the tag commit is the artifact commit.

### shadcn/ui

- Exact artifact: [`shadcn@4.13.0` registry metadata](https://registry.npmjs.org/shadcn/4.13.0), published `2026-07-03T12:29:02.707Z`, integrity `sha512-5fuJ4jI/GcPeA/iTL4cJivCZuYQGXz/N3bIzyd+Gd/FM6xUCy2MxGG+LaDQuw2cjNy9zGPSFPTEmI048UwPTZA==`.
- Upstream release evidence: [`shadcn@4.13.0`](https://github.com/shadcn-ui/ui/releases/tag/shadcn%404.13.0), tag object resolves to commit [`d0fae528221011f75a8c64a917073904c2847493`](https://github.com/shadcn-ui/ui/commit/d0fae528221011f75a8c64a917073904c2847493), tagged `2026-07-03T12:29:03Z`.
- Fixed license evidence: [MIT license at the release commit](https://github.com/shadcn-ui/ui/blob/d0fae528221011f75a8c64a917073904c2847493/LICENSE.md). The exact registry tarball also contains `package/LICENSE.md`.
- Reuse controls: record each generated component's CLI version and upstream provenance in a local manifest; preserve notices; audit accessibility, focus, keyboard support, and transitive Radix/Tailwind licenses before release.

### TanStack Table

- Exact artifact: [`@tanstack/react-table@8.21.3` registry metadata](https://registry.npmjs.org/%40tanstack%2Freact-table/8.21.3), published `2025-04-14T20:20:18.966Z`, integrity `sha512-5nNMTSETP4ykGegmVkhjcS8tTLW6Vl4axfEGQN3v0zdHYbK4UfoqfPChclTrJ4EoK9QynqAu9oUf8VEmrpZ5Ww==`.
- Upstream release evidence: [`v8.21.3`](https://github.com/TanStack/table/releases/tag/v8.21.3), annotated tag resolves to commit [`f4dc742b7b8bf01bb7dd10ee7d2f238400befcc0`](https://github.com/TanStack/table/commit/f4dc742b7b8bf01bb7dd10ee7d2f238400befcc0), tagged `2025-04-14T20:20:36Z`.
- Fixed license evidence: [MIT license at the tagged commit](https://github.com/TanStack/table/blob/f4dc742b7b8bf01bb7dd10ee7d2f238400befcc0/LICENSE).
- Reuse controls: use server pagination and virtualization for large data sets; do not load large source/evidence tables entirely into client memory.

### Apache ECharts

- Exact artifact: [`echarts@6.1.0` registry metadata](https://registry.npmjs.org/echarts/6.1.0), published `2026-05-19T17:52:11.076Z`, integrity `sha512-q0yaFPggC9FUdsWH4blavRWFmxdrIodbkoKNAjJudAI6CA9gNPxHtV2RcZNEepZVlk4yvBYkOkbk6HIVpIyHZA==`, registry `gitHead` [`c5a48f5f97d23e5379720870b8444cd05b50ffb4`](https://github.com/apache/echarts/commit/c5a48f5f97d23e5379720870b8444cd05b50ffb4).
- Upstream release evidence: [`6.1.0`](https://github.com/apache/echarts/releases/tag/6.1.0), published `2026-05-19T17:38:29Z`; the tag resolves to the same commit above.
- Fixed license evidence: [Apache-2.0 license and bundled notice text at the artifact commit](https://github.com/apache/echarts/blob/c5a48f5f97d23e5379720870b8444cd05b50ffb4/LICENSE).
- Reuse controls: preserve Apache notices in release packaging; sanitize labels/tooltips, disable untrusted HTML paths, and downsample large data sets.

### Tiptap

- Exact artifacts: [`@tiptap/core@3.27.4` registry metadata](https://registry.npmjs.org/%40tiptap%2Fcore/3.27.4), published `2026-07-13T14:46:03.965Z`, integrity `sha512-8W/GwlEn0JwNdpyVfTWcXwHYUpj9BWwO++YxtizmgjJzlwigSh7/xLVJMwVykuQHQ2fCq5rkUvmBRtpHOMLUQA==`; [`@tiptap/react@3.27.4` registry metadata](https://registry.npmjs.org/%40tiptap%2Freact/3.27.4), published `2026-07-13T14:46:36.925Z`, integrity `sha512-rTY1V9Y1jzwmo5ItRi3v2Og/mbcYsr9AjUvGoqpXzR9Z31WhXYphw0y05aYzryh0MHXYzkiE+gbGvrbg+cjwEg==`.
- Version-bound license evidence: the immutable [`core` tarball](https://registry.npmjs.org/%40tiptap/core/-/core-3.27.4.tgz) and [`react` tarball](https://registry.npmjs.org/%40tiptap/react/-/react-3.27.4.tgz) each contain `package/LICENSE.md` beginning with `MIT License`; the registry metadata records `license: MIT` and the integrity values above cover those files.
- Upstream source tag/commit: **Needs verification.** At this verification time the registry metadata had no `gitHead`, and an exact `3.27.4` tag was not returned by the upstream [tag refs](https://github.com/ueberdosis/tiptap/tags). Do not substitute a floating branch license URL or claim a source commit match until upstream provenance is available.
- Reuse controls: exact-pin core, React, and extensions; prohibit unreviewed Pro extensions; sanitize pasted HTML, links, embeds, and exported Markdown/PDF.

### LangGraph

- Exact artifact: [`langgraph==1.2.9` PyPI metadata](https://pypi.org/pypi/langgraph/1.2.9/json), sdist upload `2026-07-10T01:30:14.985653Z`, SHA-256 `385f87bc1802c35af7e0aa479278ecba8582d103515eb48256cb2ddcd42d0bd4`.
- Upstream release evidence: [`1.2.9`](https://github.com/langchain-ai/langgraph/releases/tag/1.2.9), published `2026-07-10T01:30:24Z`, points to commit [`95af6a00718588e7b7ce17310e8006d267896a77`](https://github.com/langchain-ai/langgraph/commit/95af6a00718588e7b7ce17310e8006d267896a77).
- Fixed license evidence: [MIT license at the release commit](https://github.com/langchain-ai/langgraph/blob/95af6a00718588e7b7ce17310e8006d267896a77/LICENSE); the versioned PyPI sdist also contains `langgraph-1.2.9/LICENSE`.
- Reuse controls: fixed graph/schema versions; read-only tools; schema validation, idempotency, prompt-injection defenses, traceability, and persisted human gates.

### Langfuse

- Exact JS SDK artifact: [`langfuse@3.38.20` registry metadata](https://registry.npmjs.org/langfuse/3.38.20), published `2026-04-01T08:11:19.028Z`, integrity `sha512-MAmBAASSzJtmK1O9HQegA1mFsQhT8Yf+OJRGvE7FXkyv3g/eiBE0glLD0Ohg3pkxhoPdggM5SejK7ue9ctlaMA==`, registry `gitHead` [`88f742a137dc84728284aa72eb33f824627a6e38`](https://github.com/langfuse/langfuse-js/commit/88f742a137dc84728284aa72eb33f824627a6e38).
- Exact Python SDK artifact: [`langfuse==4.14.0` PyPI metadata](https://pypi.org/pypi/langfuse/4.14.0/json), sdist upload `2026-07-10T11:33:39.153848Z`, SHA-256 `31b875c8d09eee39c558584b9424bbd5ed014965c5944c4528a37947ae4b7787`; upstream tag [`v4.14.0`](https://github.com/langfuse/langfuse-python/tree/v4.14.0) resolves to commit [`a02fc7c2195a81a6f75e084795f86857876b1c90`](https://github.com/langfuse/langfuse-python/commit/a02fc7c2195a81a6f75e084795f86857876b1c90).
- Fixed license evidence: [JS SDK MIT license at its package `gitHead`](https://github.com/langfuse/langfuse-js/blob/88f742a137dc84728284aa72eb33f824627a6e38/LICENSE); [Python SDK MIT license at `v4.14.0`](https://github.com/langfuse/langfuse-python/blob/a02fc7c2195a81a6f75e084795f86857876b1c90/LICENSE); [server OSS/EE boundary at fixed source commit `613d465bd2e3e351abbe56931279b1a98ff5d8af`](https://github.com/langfuse/langfuse/blob/613d465bd2e3e351abbe56931279b1a98ff5d8af/LICENSE).
- Self-host server runtime: **Needs verification.** No Langfuse server release or image digest is selected in Phase 0. Before deployment, pin a server release/image digest and re-check the license scope, EE exclusion, notices, security advisories, and configuration at that exact artifact.
- Reuse controls: do not send secrets, private raw content, or unredacted PII to traces; pin SDKs and any future self-host image separately; keep EE paths/features isolated until separately licensed.

## Reference And Blocked License Evidence

These are fixed source snapshots, not dependency selections. They were checked at `2026-07-15T07:45:20Z` (UTC); their statuses in the decision matrix remain unchanged.

| Project | Fixed official license evidence | Status implication |
|---|---|---|
| DeerFlow | [MIT license at `b68e1c686a0cb5a3780089d27354354533451d8e`](https://github.com/bytedance/deer-flow/blob/b68e1c686a0cb5a3780089d27354354533451d8e/LICENSE) | Reference only; chat-first/super-agent assumptions and tool execution are not Glint's Phase 0 model. |
| Agent Reach | [MIT license at `e825f6740d24c6c315c3b0dc41907e6c87ff39a5`](https://github.com/Panniantong/Agent-Reach/blob/e825f6740d24c6c315c3b0dc41907e6c87ff39a5/LICENSE) | Candidate adapter only; distribution, transitive dependency, credential, platform ToS, and security checks remain Needs verification. |
| TrendRadar | [GPL-3.0 license at `1f178da10e6680e5b652b0dec781e675fe73cf31`](https://github.com/sansan0/TrendRadar/blob/1f178da10e6680e5b652b0dec781e675fe73cf31/LICENSE) | Blocked for code reuse. |
| BettaFish | [custom restricted license at `40327d75b60faaf347bc578f93714b5394079d03`](https://github.com/666ghj/BettaFish/blob/40327d75b60faaf347bc578f93714b5394079d03/LICENSE) | Blocked for code reuse; commercial use requires written permission. |

## Pinning And Notice Policy

| Ecosystem | Policy |
|---|---|
| npm/pnpm | Use exact versions in `package.json`, commit the lockfile, and verify registry integrity during install. Dependabot/Renovate changes require a grouped minor/patch or separate major dependency PR. |
| Python | Use exact pins in a lockfile generated from constrained inputs. Do not deploy from an unconstrained `requirements.txt`; record PyPI sdist/wheel SHA-256 in the resolved lock. |
| Rust | Commit `Cargo.lock` for the Tauri app and review RustSec advisories on every upgrade. |
| Docker | Pin image tags and immutable digests for Postgres, Redis, MinIO, Langfuse, and local development services. |
| Referenced repositories | Before importing code or configuration, pin a commit SHA and record the license verification timestamp and fixed source URL. |

1. Preserve MIT and Apache notices in release artifacts where required.
2. Generate and manually review `THIRD_PARTY_NOTICES.md` from lockfiles once implementation begins; include vendored shadcn/ui provenance.
3. Do not import GPL or custom-restricted code into `apps/`, `services/`, `packages/`, `infra/`, or tests.
4. Treat third-party screenshots, docs text, example datasets, and prompts as copyrighted material unless an explicit reuse license applies.

## Immediate Follow-Ups

1. Resolve Tiptap's exact source commit/tag provenance before any source-level inspection or vendoring beyond the approved package dependency path.
2. Select and verify a Langfuse server release/image digest before self-host deployment; the SDK evidence does not authorize an unpinned server runtime.
3. Keep DeerFlow reference-only; keep TrendRadar and BettaFish blocked for all code reuse.
4. Before Phase 4+, verify Agent Reach distribution, transitive CLI dependencies, platform ToS, credential handling, timeouts, output isolation, and health checks.
