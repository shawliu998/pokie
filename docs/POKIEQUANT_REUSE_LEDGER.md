# PokieQuant Reuse Ledger

Status: evidence-bound reuse and non-reuse record  
Verified: 2026-07-17 (Asia/Shanghai)

This ledger records what is demonstrably present in this repository and its Git
history. A SHA identifies a reviewed revision; it does **not** by itself authorize
copying. Any future external source migration still requires a repository, immutable
revision, file-level mapping, license/notice review, modification record, and security
review. “Unknown” means the evidence was not available locally and must not be filled
in by inference.

## Source boundaries

| Source | Fixed SHA / evidence | Boundary |
| --- | --- | --- |
| PokieQuant current repository | `76c64592c6986a1a094bb1aaab0e21478a60feca` (`HEAD` when this ledger was written) | PokieQuant additions and refactors after the inherited Glint baseline. Its public `origin` is `https://github.com/shawliu998/pokie.git`. |
| Glint inherited history | selected baseline `eb9a4be58c4a16b790d0b7568735c53a3627fe51` (`glint-agent-workspace-baseline`); upstream `refs/heads/main` verified as `161c6075a9e73dbb344f15d58ef41b7c9834380e` | History-preserving, authorized first-party inherited source. The baseline is the actual code lineage for the initial PokieQuant fork; the current upstream-main ref is recorded separately and is not represented as newly copied. |
| Lumi | `cd1ebcb17c53268725495e874b3f5980514781cc` (upstream `refs/heads/main` verified 2026-07-17) | Exact revision inspected in a read-only `/tmp` checkout: `runtime/hermes_runtime/tools.py`, `models.py`, and `machine.py`. The revision has no root `LICENSE`, `COPYING`, or `NOTICE`; license remains unknown. Only independently implemented interface/coordination patterns are generalized; no source is copied verbatim. |
| spark-agent / Spark | `f21158df7631e23f5be4481ea20e63c11e8389b1` (upstream `refs/heads/main` verified 2026-07-17) | Not integrated. The separate local candidate audited in `POKIEQUANT_REFERENCE_AUDIT.md` was at `259ed60847de5771bfb21ceecd066b45016ed9f6`; it is an instruction/memory scaffold, not evidence that the upstream runtime was obtained or copied. |

The repository audit establishes that the Glint baseline was fetched and checked out
with Git history, rather than copied/exported or rewritten. The audit also finds no
root Glint `LICENSE`, `COPYING`, or `NOTICE`; therefore Glint is recorded as inherited
first-party source under repository authority, **not** as an independently verified
open-source license grant.

## File-level ledger

| Status | Source repository | Fixed SHA | Source file(s) | Target file(s) | Reused class/function or seam | Not reused | Modification / evidence | License |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Inherited/refactored | Glint (`glint-upstream`) | baseline `eb9a4be58c4a16b790d0b7568735c53a3627fe51`; upstream main `161c6075a9e73dbb344f15d58ef41b7c9834380e` | `services/worker/app/pipelines/model_research.py` | `services/worker/app/providers/openai_compatible.py`; adjusted `services/worker/app/pipelines/model_research.py`; `services/worker/app/quant_agent/provider.py` | The former `HttpxDeepSeekTransport` behavior was extracted as `OpenAICompatibleConfig`, `HttpxOpenAICompatibleTransport`, and `OpenAICompatibleError`. Both legacy Model Research and Quant providers use that fail-closed transport. | Model Research prompts, evidence/claim pipeline, DeepSeek product contract, and Quant prompts/decision schemas remain separate. No Glint product-intelligence objects were mapped into Quant objects. | Commit `c762b5b88403d7d4266efd638d6593f50f40a1d1` shows the extraction from the in-repository `model_research.py`; it is a current-repository refactor of inherited Glint code, not an external Glint source import. | Unknown for the Glint repository as a standalone OSS project (no root license evidence in the audit); inherited first-party authority only. |
| PokieQuant implementation | PokieQuant current repository | `c762b5b88403d7d4266efd638d6593f50f40a1d1` plus the current Phase 1A documentation slice | In-repository bounded-runtime requirements and Quant tool use | `packages/agent_runtime/__init__.py`; `packages/agent_runtime/registry.py`; `packages/agent_runtime/models.py`; Quant registry consumers | Pydantic-validated `ToolSpec`/`ToolContext`/`ToolRegistry`/`ToolError` and stateless `ModelRequest`/`ModelResponse`/`ModelProvider`/`ModelRouter` primitives. | No external state, persistence, scheduling, provider configuration, or retry behavior. | `c762b5b…` adds the registry; the final documentation slice adds the small model-routing seam after reviewing the pinned Lumi interfaces. | Repository-level PokieQuant license: unknown; no external source copied verbatim. |
| Reviewed interface-pattern generalization — not copied | Lumi (exact revision inspected in read-only `/tmp` checkout) | `cd1ebcb17c53268725495e874b3f5980514781cc` | `runtime/hermes_runtime/tools.py`, `runtime/hermes_runtime/models.py`, `runtime/hermes_runtime/machine.py` | `packages/agent_runtime/registry.py`; `packages/agent_runtime/models.py`; `services/worker/app/quant_agent/runner.py` | Independently generalized closed `ToolRegistry`/`ToolSpec`/`ToolContext`/`ToolError`, `ModelRequest`/`ModelResponse`/`Provider`/`Router` interface concepts, and bounded step-coordination structure. The current implementations replace Lumi's phase coupling and handwritten schema validator with PokieQuant contracts and Pydantic validation. | Lumi `AgentState`, `Phase`, `PHASE_TO_TOOL`, SQLite `EventStore`, learning guardrails, artifacts, all other source files, assets, copy, dependencies, and runtime behavior. | The named files were inspected at the fixed SHA in a read-only checkout. The revision has no root `LICENSE`, `COPYING`, or `NOTICE`; therefore this row permits only interface-pattern generalization and does not authorize source copying or vendoring. | Unknown (no root license/notice evidence at the reviewed revision). |
| Not integrated | spark-agent / Spark | `f21158df7631e23f5be4481ea20e63c11e8389b1` | Unknown upstream runtime paths; the separately audited local scaffold contained only instruction/memory material | None | None. At most, the product has a future `QuantExecutionRuntime` port/seam. | Python/Jupyter sandbox, code execution, artifact hashing, recovery engine, dependencies, and all Spark runtime/source files. | `POKIEQUANT_REFERENCE_AUDIT.md` records the local scaffold at `259ed608…`, no remote/license, and prohibits Phase 0 migration. The verified upstream-main SHA does not change that non-integration decision. | Unknown / no usable license evidence in this worktree. |
| Not obtained / not copied | PokieTicker | Unknown — no repository, immutable commit, file list, or remote supplied/found | None | None | None; only original PokieQuant contracts and synthetic/imported fixtures are permitted. | All PokieTicker source, market adapters, assets, provider data, and dependencies. | `POKIEQUANT_REFERENCE_AUDIT.md` requires a future row with repository, fixed commit, paths, license, modifications, notices, data rights, and security review before any use. | Unknown. |

## Guardrails

- Lumi is deliberately described as independently implemented interface-pattern
  generalization, never as a verbatim or unverified code copy. The fixed revision’s
  selected runtime files were reviewed, but the absent root license/notice evidence
  limits the result to patterns rather than copied or vendored source.
- The shared OpenAI-compatible transport is a **current-repository extraction** from
  the inherited `model_research.py` implementation, as evidenced by commit `c762b5b…`.
  It is not a claimed import from Lumi or Spark.
- Spark is not connected to a PokieQuant execution path. A fixed upstream SHA alone
  does not establish that its runtime, license, or file-level migration was reviewed.
- Do not convert any `unknown`, `not obtained`, or `not copied` cell into an approval
  without adding the required immutable, file-level, and license evidence.

## Evidence consulted

- `docs/POKIEQUANT_REPOSITORY_AUDIT.md` — Glint fork/baseline and history handling.
- `docs/POKIEQUANT_REFERENCE_AUDIT.md` — Glint license boundary, Spark local-candidate
  audit, and PokieTicker prohibition.
- `docs/POKIEQUANT_AUTONOMOUS_AGENT_AUDIT.md` — local extraction and Lumi inspiration
  boundary.
- Git history: `eb9a4be…..HEAD`, especially `c762b5b…` (`refactor(agent): share tool
  registry and model transport`).
