# Glint Phase 0 独立总审查

> 审查日期：2026-07-15
>
> 当前回归范围：在最后一次源文档冻结后重新读取全部 `docs/**/*.md`，含 `README.md` 与 ADR 0005；共 23 个输入文件、5,062 行，本报告自身不计入输入。
>
> 当前回归方式：不继承旧 No-Go、旧状态或旧行号；逐项复核原 17 项及全部 post-fix 新增项，并机械检查 24 个 Markdown、8 个显式 `json` 围栏（Seed 7 个）、115 个 Seed UUID 字符串、27 个 Seed 对象主 ID 与 28 个相对链接。
>
> 当前结论：**Conditional Go（允许进入 Phase 1 实现，但不是生产放行）**。当前 Phase 1 前置 P0/P1 阻塞为 **0**，当前 Open P2 计数为 **0**；原 17 项与 P1-N01、P2-N01、P2-N02、P2-N03 均已 Resolved。由于尚无生产代码、迁移、生成 OpenAPI/client 与实现测试，绝不给无条件 Go。
> Baseline 结论（历史）：**No-Go（不应进入 Phase 1 实现）**；下方原始发现与证据保留为历史快照，不代表当前文件行号或状态。

## Post-fix verification

本节是第三次、稳定快照独立回归；下方 `## Baseline findings (historical)` 保持历史原文。`Resolved` 表示当前权威合同已收敛；`Partially resolved` 表示仍有局部合同歧义；`Open` 表示仍无可执行单一合同。当前没有 `Partially resolved` 或 `Open` 的 P0/P1。

### 原 17 项逐项状态

| ID | 当前状态 | 当前文件与行号 | 回归结论 / 单一裁决 |
|---|---|---|---|
| P0-01 Investigation aggregate | **Resolved** | `DATA_MODEL.md:130-141`; `API_CONTRACTS.md:321-398`; `PROJECT_STRUCTURE.md:109-117`; `ADR/0005-investigation-decision-brief-boundary.md:12-20` | Investigation 是持久用户工作聚合，ResearchRun 只是其中一次有界执行；FK、路由、模块与 ADR 一致。 |
| P0-02 Insight 语义 | **Resolved** | `INFORMATION_ARCHITECTURE.md:28,38-45,215-221`; `DATA_MODEL.md:151-153`; `API_CONTRACTS.md:435,461`; `ADR/0005-investigation-decision-brief-boundary.md:14` | `InvestigationSynthesisVersion` 是 Investigation 内中间综合，无独立 owner、顶层导航/API 或长期决策生命周期。 |
| P0-03 Brief 唯一核心产物 | **Resolved** | `PRODUCT_BRIEF.md:82-110`; `DATA_MODEL.md:154-158`; `API_CONTRACTS.md:433-474`; `ADR/0005-investigation-decision-brief-boundary.md:16` | Decision Brief 是唯一决策级 aggregate；PRD Research Input 只有无状态 Preview 与成功后 terminal BriefExport。 |
| P0-04 不可变版本链 | **Resolved** | `DATA_MODEL.md:95-97,136-158`; `API_CONTRACTS.md:398,461-474`; `ARCHITECTURE.md:239-247`; `ADR/0002-evidence-versioning.md:12` | 单链为 `ContentVersion → Evidence/EvidenceReview → ClaimVersion/ClaimReview → verified SynthesisVersion/SynthesisReview → grounded DecisionBriefVersion → Readiness/Freshness → BriefExport`；direct refs 只能是 synthesis provenance 子集。 |
| P0-05 唯一状态机 | **Resolved** | `DATA_MODEL.md:163-179`; `ARCHITECTURE.md:170-216`; `API_CONTRACTS.md:334,347,420-435`; `INFORMATION_ARCHITECTURE.md:236-284` | Aggregate、execution、review/readiness/freshness projection 与 terminal record 已分层；无第二套 Run/SSE/Brief 状态语义。 |
| P1-01 单 Owner 与多租户基础 | **Resolved** | `PRODUCT_BRIEF.md:10-12,48-50`; `SECURITY_MODEL.md:21-51`; `DATA_MODEL.md:53-62`; `API_CONTRACTS.md:238-255,319` | Phase 1 单 Owner PM 可闭环，同时真实 workspace scope、RLS、授权与 AuditLog 前移；Reviewer 是 duty，五角色行为 Phase 4。 |
| P1-02 Phase 1/2/3 与 MVP 范围 | **Resolved** | `PRODUCT_BRIEF.md:171-179`; `USER_FLOWS.md:15-21,74-81`; `IMPLEMENTATION_PLAN.md:55-119`; `EVALUATION_PLAN.md:13-15` | Phase 1=Seed/Imported CSV + deterministic provider，Phase 2=GitHub/RSS，Phase 3=单个有界 LangGraph；只显示已接通入口。 |
| P1-03 安全、审计、Eval 前移 | **Resolved** | `QUALITY_GATES.md:16-29,51-74`; `EVALUATION_PLAN.md:9-16,73-99`; `SECURITY_MODEL.md:117-129`; `IMPLEMENTATION_PLAN.md:61-67` | Phase 1 要求真实 RLS/授权、AuditLog、幂等、脱敏、安全/Seed eval smoke；模型质量与协作 UI 按阶段后置。 |
| P1-04 Signal 四维 contract | **Resolved** | `DATA_MODEL.md:105-124`; `API_CONTRACTS.md:198,295-317`; `PRODUCT_BRIEF.md:112-129`; `UI_SPEC.md:285-312` | Detection Confidence / Business Impact / Urgency / Priority 分离；suggested/confirmed/derived 明确，Unknown→`priority=null/insufficient_input`，无 direct Priority write。 |
| P1-05 模型工具只读 | **Resolved** | `ADR/0003-bounded-research-graph.md:10-16`; `ARCHITECTURE.md:143-168`; `SECURITY_MODEL.md:71-82`; `PROJECT_STRUCTURE.md:100` | 单 LangGraph 从 Phase 3 启用；模型工具只读，proposal 经 schema/policy/Domain Service，review/transition/export 是图外命令。 |
| P1-06 SSE 单一恢复协议 | **Resolved** | `DATA_MODEL.md:134,143`; `ARCHITECTURE.md:218-229`; `API_CONTRACTS.md:400-431`; `PROJECT_STRUCTURE.md:121-173` | persistence `research_run_id/type/payload_json/occurred_at` 唯一映射为 wire `run_id/event_type/payload/timestamp`；快照、Last-Event-ID、replay、去重、`stream.reset` 为单协议。 |
| P1-07 provisional thresholds | **Resolved** | `PRODUCT_BRIEF.md:201-213`; `QUALITY_GATES.md:31-49`; `EVALUATION_PLAN.md:85-99`; `PRODUCT_VALIDATION_PLAN.md:265-276,402-444,502` | 数字均为带样本/分母/版本/owner/日期的 provisional target 或 stop line，不冒充校准概率、生产 SLO 或保证。 |
| P1-08 Seed 与生产 schema | **Resolved** | `DATA_MODEL.md:202`; `API_CONTRACTS.md:493-495`; `SEED_DATASET_SPEC.md:113-489`; `QUALITY_GATES.md:24,55,63` | 7 个 Seed JSON 可解析；115 个 UUID 字符串有效，27 个对象主 ID 全局唯一；Import、review、synthesis、grounded Brief、readiness/freshness/export 与生产合同同形。 |
| P1-09 离线写队列 | **Resolved** | `API_CONTRACTS.md:487-489`; `ARCHITECTURE.md:19,59`; `USER_FLOWS.md:250-256`; `PRODUCT_BRIEF.md:179,244` | SQLite/bootstrap 只读；离线 mutation、Brief edit/export 禁用；无隐藏 write queue、merge 或 conflict contract。 |
| P2-01 旧 IA 词汇 | **Resolved** | `INFORMATION_ARCHITECTURE.md:5-28,321-353`; `RISK_REGISTER.md:21-37`; `EVALUATION_PLAN.md:53-71` | 权威对象统一为 Signal/Investigation/Decision Brief/InvestigationSynthesisVersion；Insight/Alert 只在反例、研究语义或历史说明中出现。 |
| P2-02 Markdown 标题/锚点 | **Resolved** | 当前全部 `docs/**/*.md` | 24 个 Markdown 各恰有一个 H1、无重复 heading、围栏闭合；8 个显式 `json` 围栏可解析，28 个相对链接均存在。 |

### 最新修复重点核验

| 核验项 | 状态 | 当前证据 / 结论 |
|---|---|---|
| 1. Brief 恰好一个同 Investigation verified synthesis；direct refs 仅 provenance 子集 | **Resolved** | `DATA_MODEL.md:151-161`; `API_CONTRACTS.md:461-474`; `ADR/0005-investigation-decision-brief-boundary.md:16`。服务端校验单数 synthesis、同 Investigation、verified、exact SynthesisReview 与 provenance 子集。 |
| 2. Claim/Synthesis/Readiness exact-version append-only reviews | **Resolved** | `DATA_MODEL.md:136-158,194`; `API_CONTRACTS.md:398,435,461-474`; `SEED_DATASET_SPEC.md:317-489`。Immutable content 不靠原地 status mutation。 |
| 3. BriefExport 仅成功后形成 terminal immutable record并钉 selection/reference/render-output digest | **Resolved** | `DATA_MODEL.md:158,179,194`; `API_CONTRACTS.md:435,458,474`; `SECURITY_MODEL.md:103`。失败只保留幂等命令结果/AuditLog。 |
| 4. Seed 完整 review→verified→grounded brief→readiness→export | **Resolved** | `SEED_DATASET_SPEC.md:282-489`。Claim/Synthesis/ReadinessReview exact-version，direct refs 为 provenance 子集，export selection 排除 Synthesis。 |
| 5. Decisions list、Synthesis UI、atomic triage、Unknown、navigation-summary | **Resolved** | `API_CONTRACTS.md:245-255,295-317,433-474`; `UI_SPEC.md:77-94,285-312,343-501`。 |
| 6. Phase 顺序、Eval 阶段矩阵、Reviewer duty | **Resolved** | `IMPLEMENTATION_PLAN.md:55-131`; `EVALUATION_PLAN.md:9-16`; `SECURITY_MODEL.md:31`; `API_CONTRACTS.md:319,370`。 |
| 7. RunEvent persistence→wire 与 SSE 单协议 | **Resolved** | `DATA_MODEL.md:143`; `ARCHITECTURE.md:218-229`; `API_CONTRACTS.md:400-431`; `PROJECT_STRUCTURE.md:121-173`。 |
| 8. Markdown H1/heading/fence/JSON/relative links | **Resolved** | H1 异常 0、重复 heading 0、未闭合围栏 0、JSON parse error 0、broken relative link 0。 |

### 新增发现

#### P1-N01 — ImportSession → TransferConsentRecord → terminal ImportManifest

- **状态：Resolved。** 当前没有 Import lifecycle 的 Phase 1 前置阻塞。
- **当前证据**：Data/API 定义 mutable row-versioned `ImportSession`、append-only `TransferConsentRecord`、成功后 terminal immutable `ImportManifest`（`DATA_MODEL.md:70-89,169,194-196`; `API_CONTRACTS.md:19-20,40,68-118,257-281`）。其余合同同义（`ARCHITECTURE.md:96-100`; `ADR/0004-local-cloud-source-boundary.md:12-18`; `IMPLEMENTATION_PLAN.md:61-63,150`; `SECURITY_MODEL.md:90-92,124`; `QUALITY_GATES.md:22-24,55,59`; `UI_SPEC.md:543-551`; `USER_FLOWS.md:21,74,88-91`; `PROJECT_STRUCTURE.md:98,109,197`; `SEED_DATASET_SPEC.md:113-201`）。
- **单一裁决**：保持 `SourceConnection(imported_dataset/static_import, credential_ref=null)` → mutable `ImportSession` → append-only `TransferConsentRecord` → terminal immutable `ImportManifest`；不得重新引入 draft/mutable manifest。
- **闭合证明**：每个 SourceConnection 只允许一个非终态 Session；Session 钉 expected source row/current manifest、file/expected-upload/local-manifest digests、parser/schema、selected scope 与 `uploaded_object_key`，且无 Mac path/body。Consent 钉 digests/scope/destination/object key/max bytes/media type/expiry，upload consent 不等于 model egress；`upload-complete` 与 `finalize` 使用同一 effective-consent resolver，session state 不是授权。专用 `ImportFinalizationJob` 是唯一可接收固定 session/finalize command 的 worker：它服务端复核 object-store key/size/type/digest，parse/normalize，并原子创建可见 ContentVersion、恰好一个 manifest 与 CAS current pointer；所有 downstream dedupe/detection/research 只接 terminal manifest/version，禁止二次 normalize。失败/取消零 manifest/可见 content；有 grant 的 cancel 原子追加 revoke/supersedes、清 staging 并 Audit；相同 pins 的 retryable failure 才可 retry，否则 new session；If-Match/row-version 解决 finalize/cancel race。UI 只选择具有 terminal current pointer 的 SourceConnection，ResearchRun scope 冻结具体 manifest ID。

#### P2-N01 — IA page map 与 Stage D synthesis prerequisite

- **状态：Resolved。** `INFORMATION_ARCHITECTURE.md:38-45,152,215-221` 已列 Synthesis；`PRODUCT_VALIDATION_PLAN.md:208-238` 明测未 verified synthesis 不可创建 Brief。

#### P2-N02 — README 状态同步

- **状态：Resolved。** `README.md:3-6` 已写明 Phase 0 independently regressed、Phase 1 为 Conditional Go、Production business code 尚未开始，并以相对链接指向本报告。
- **单一裁决**：README 状态与本报告当前 Conditional Go 一致；不再保留 regression pending 文案。

#### P2-N03 — USER_FLOWS review 产物措辞

- **状态：Resolved。** `USER_FLOWS.md:37-38` 已把 Evidence/Claim 产物写为 append-only exact-version review records 与 derived projection。

#### 回归新增机械观察 — Seed 对象主 ID 语义唯一

- **状态：Resolved。** `SEED_DATASET_SPEC.md:115-489` 的 27 个语义对象/块主 ID 全局唯一（其中 23 个对象 UUID 亦各自唯一）；115 次 Seed UUID 出现均机械有效。ClaimReview、SynthesisReview、DecisionBriefReadinessReview 的 snapshots/FK 已同步；Import 的 object key、三类 digest、source pointer/CAS、consent/session refs 与时间顺序断言全部通过。引用处重复 UUID 是正常 FK，主 ID 无跨语义复用。

### 仍阻塞 Phase 1 的精确问题

**无。当前文档快照中的 Phase 1 前置 P0/P1 blocker 数为 0。**

`README.md:5` 明确 production business code 尚未开始；进入 Phase 1 后仍必须以 `QUALITY_GATES.md:16-29,51-75` 与 `IMPLEMENTATION_PLAN.md:76-82` 的 migration/schema、generated OpenAPI/client、unit/contract/integration/E2E/security/eval smoke 和 runtime integrity 作为实现验收条件。

### 当前已通过的关键决策

- 用户语言为 `Inbox / Investigations / Decisions / Monitoring`；三栏为 Navigation/List/Detail，Filter sheet 不形成第四栏，未接通能力无入口。
- Investigation 是 durable aggregate；ResearchRun 是 attempt；InvestigationSynthesisVersion 是无独立 owner/nav/API 的中间结论；Decision Brief 是唯一决策对象。
- 每个 DecisionBriefVersion 恰好绑定一个同 Investigation verified synthesis；direct refs 只能是 frozen provenance 子集；所有 review/freshness/export 钉 exact version。
- Phase 1 单 Owner + 真实 workspace/RLS/Audit；Phase 2 GitHub/RSS；Phase 3 单有界 LangGraph。模型工具只读，proposal 只经 Domain Service。
- Signal 四维、RunEvent persistence/wire、SSE replay/reset、幂等/并发、离线只读、provisional thresholds 与 REUSE 三维资格均收敛。
- Phase 1 Imported CSV 使用唯一三对象生命周期；只有专用 ImportFinalizationJob 接收 session/finalize command，downstream 只接 terminal manifest/version；Seed Import/decision chain 与生产 schema 同形且机械有效。

### 可延后问题

- Phase 2 GitHub/RSS；Phase 3 LangGraph/model quality/Tiptap/Langfuse SDK；Phase 4 五角色、Reviewer assignment UI、协作与 Eval/Audit UI。
- Tiptap source provenance、Langfuse server image/release、Agent Reach distribution/ToS/credential/sidecar 核验；仅在对应 source/runtime 路径启用前阻塞。
- 校准后的 Signal/Claim 概率、生产 SLO、完整离线写入、多格式/外部发布；当前继续使用 provisional/heuristic/只读边界。

### 建议的 canonical vocabulary

| 层 | Canonical vocabulary | 单一边界 |
|---|---|---|
| UI destinations | `Inbox` / `Investigations` / `Decisions` / `Monitoring` | Watchlists/Sources 仅为 Monitoring 内 views。 |
| Work / execution | `Investigation` / `ResearchRun` / `RunEvent` | Investigation 持久；Run 是 attempt；wire `run_id` 由 DB `research_run_id` 唯一映射。 |
| Import | `SourceConnection(imported_dataset/static_import)` → mutable `ImportSession` → append-only `TransferConsentRecord` → terminal immutable `ImportManifest` | Session 协调、consent 授权、manifest 表示唯一成功结果；专用 finalizer 是唯一可接 session 的 worker，所有 downstream 只接 terminal manifest/version。 |
| Evidence | immutable `ContentVersion` → immutable `Evidence` + append-only `EvidenceReview` | review projection 不写回 Evidence。 |
| Claim | `Claim` + immutable `ClaimVersion`/`ClaimEvidence` + append-only `ClaimReview` | verify 钉 ClaimEvidence/EvidenceReview snapshot/digest。 |
| Intermediate synthesis | `InvestigationSynthesisVersion` + `SynthesisReview` | origin 为 deterministic/model；不使用独立 Insight。 |
| Decision | `DecisionBrief` + immutable `DecisionBriefVersion` + Readiness/Freshness records | 一个版本恰好一个 verified synthesis；freshness 与 readiness 正交。 |
| Output | UI `PRD Research Input`; technical `BriefExport` | Preview 无状态；BriefExport 是成功后的 terminal immutable record。 |
| Signal | Detection Confidence / Business Impact / Urgency / derived Priority | suggestion 带 origin/version；confirmation 为人类；Unknown→null/insufficient_input。 |
| Actor | `WorkspaceMember.role` + Reviewer duty/assignment | Reviewer 不是第六角色。 |

### 推荐统一状态机

以 `DATA_MODEL.md:163-179` 为 domain enum/projection 源，以 `API_CONTRACTS.md:19-20` 的 If-Match/row-version 处理可变 aggregate 竞争；UI 只映射显示文案：

| Aggregate / projection | States / transitions |
|---|---|
| ImportSession | `draft → consented → uploaded → validating → finalized`; validation 可到 `failed`，仅相同 pins + 有效 consent 的 retryable failure 可回 `validating`；`draft/consented/uploaded/validating/failed → cancelled`。`finalized/cancelled` terminal；专用 finalizer 在有效 consent 下原子创建一个 immutable ImportManifest/visible content 并 CAS source pointer；有 grant 的 cancel 先追加 revoke，row-version 决定唯一终态。 |
| Signal | `new → triaged → investigating → explained`; 可到 `monitoring/dismissed`；无 `converted`。 |
| Investigation | `draft → active → reviewing → completed`; `active ↔ needs_input`; `reviewing → closed_insufficient`; 非终态可 `cancelled`。 |
| ResearchRun | `queued → running → completed`; `running ↔ waiting_for_input`; `running → failed/cancelled`。 |
| Evidence review projection | `proposed → valid/weak/rejected`，由 append-only EvidenceReview 派生。 |
| ClaimVersion review projection | `proposed → needs_review → verified/rejected`; 新版本使旧版本 `superseded`，不改旧内容。 |
| SynthesisVersion review projection | `draft → needs_review → verified/rejected/superseded`。 |
| DecisionBrief current aggregate | `draft → decision_ready → decided/archived`；`start_revision` 创建新 current Draft，旧 ready version 不降级。 |
| DecisionBriefVersion freshness | `current / evidence_stale`，由 append-only FreshnessRecord 派生，与 readiness 正交。 |
| BriefExport | **无生命周期状态**；仅成功后创建 terminal immutable record，失败只属于 command/AuditLog。 |

### 当前最终 Go / Conditional Go / No-Go

**当前裁决：Conditional Go。** 当前稳定快照没有 Phase 1 前置 P0/P1，且当前 Open P2 为 0；P1-N01 已通过跨 Data/API/Architecture/ADR/Implementation/Security/Quality/UI/User Flow/Project Structure/Seed 的可执行合同与机械 fixture 回归，P2-N02 的 README 状态也已与本裁决对齐。条件是 Phase 1 实现必须通过迁移、schema/generated client、contract/integration/E2E/security/eval smoke 与 runtime integrity；这些生产实现证据尚不存在，因此本裁决不是且不能升级为无条件 Go。

## Baseline findings (historical)

以下第 1–12 节是初始审查时的 baseline 结论、冲突说明、裁决与文件清单；它们保留用于比较，不代表本次回归状态。原始 baseline 共 17 项（P0 5、P1 10、P2 2）。

## 1. 结论先行

Phase 0 已经形成一套较清楚的产品语言和 UI 原则；最新 `ARCHITECTURE.md` 也已转向 `Investigation → Product Decision Brief → version-bound export`。但数据模型、API、项目模块、实现计划和质量门仍保留 `ResearchRun → long-lived Insight → generic Deliverable`，因此工程合同整体仍是两套产品。该差异不是命名问题，而是聚合边界、版本链、状态机、路由和权限范围的结构性冲突。

本次共记录 **17 项发现：P0 5 项、P1 10 项、P2 2 项**。在 5 项 P0 全部裁决并同步到架构、数据模型、API 与质量门前，不满足 `IMPLEMENTATION_PLAN.md:46-51` 所述“合同稳定后再进入 walking skeleton”的自身退出条件。

最严重的三类问题是：

1. `Investigation` 是产品一级对象，却在架构、数据模型、API 和模块树中整体缺失。
2. `Insight`、`Product Decision Brief`、`PRD Research Input` 的生命周期被工程文档重新定义，破坏“Decision Brief 是唯一核心产物”的产品裁决。
3. `Claim` 与 `Brief` 缺少可执行的不可变版本链，并与多套互不兼容的状态机叠加，无法证明引用、恢复和导出绑定到同一历史事实。

## 2. 严重度定义

| 等级 | 定义 | Phase 1 影响 |
|---|---|---|
| P0 | 核心聚合、唯一产物、版本链或状态合同相互排斥；继续实现必然产生两套模型或返工 | 阻塞 |
| P1 | 范围、安全、运行时、API 行为或验证门槛未对齐；可在编码前通过单一裁决收敛 | 必须在相应切片开工前解决 |
| P2 | 术语、Markdown 结构或维护性问题，不改变当前核心领域边界 | 可延后，但应纳入文档清理 |

## 3. P0 发现

### P0-01 — `Investigation` 聚合在工程合同中缺失

- **证据**：产品把 Investigation 定义为包含计划、多个 Research Runs、Evidence、Claims 与人工复核的一级对象（`PRODUCT_BRIEF.md:68-78`），并明确把工程映射列为待裁决项（`PRODUCT_BRIEF.md:228-237`）；IA 区分 Investigation 容器和 Research Run 执行（`INFORMATION_ARCHITECTURE.md:16-26`、`INFORMATION_ARCHITECTURE.md:115-138`）。最新架构已加入 Investigation 模块和首批对象（`ARCHITECTURE.md:69-83`、`ARCHITECTURE.md:238-242`），但 ER 图仍从 Signal 直接连到 ResearchRun（`DATA_MODEL.md:21-35`），ResearchRun 直接拥有 Evidence/Claim（`DATA_MODEL.md:100-110`）；API 仍只有 `/research-runs`（`API_CONTRACTS.md:231-264`）；项目树也没有 investigations 模块（`PROJECT_STRUCTURE.md:21-35`、`PROJECT_STRUCTURE.md:102-116`）。
- **冲突**：用户路由、列表、草稿范围、多个 Run、Evidence/Claim 汇总和最终 Brief 来源都没有权威聚合 ID。若用 ResearchRun 代替，会丢失“一个 Investigation 可多次运行、失败后新建 Run 而不改写旧 Run”的语义。
- **单一裁决**：新增 `Investigation` aggregate。MVP 中它必须由一个 Signal 发起，拥有 `decision_question`、scope/version、状态、Evidence/Claim 汇总与 `1..n ResearchRun`；ResearchRun 仅表示一次有界执行，所有 Run/Event/Claim/Evidence/Brief 创建命令必须带 `investigation_id`。
- **应修改文件**：`ARCHITECTURE.md`、`DATA_MODEL.md`、`API_CONTRACTS.md`、`PROJECT_STRUCTURE.md`、`IMPLEMENTATION_PLAN.md`、`QUALITY_GATES.md`、`ADR/0003-bounded-research-graph.md`。

### P0-02 — `Insight` 被同时定义为中间结论和长期决策对象

- **证据**：产品将 Insight 限定为 Investigation 内的综合结论，不作为一级产物（`PRODUCT_BRIEF.md:73-82`）；IA 同样限定其为后端领域概念或 Brief 中的 AI Synthesis（`INFORMATION_ARCHITECTURE.md:16-28`）。最新架构已明确 Insight 是 intermediate synthesis（`ARCHITECTURE.md:5-9`、`ARCHITECTURE.md:102-117`、`ARCHITECTURE.md:141-164`），但仍保留独立 Insight/InsightReview 对象和 review 状态（`ARCHITECTURE.md:80-83`、`ARCHITECTURE.md:186-204`）；数据模型更明确称它为 “Long-lived decision object”（`DATA_MODEL.md:114-125`）；API 暴露独立 Insight CRUD/review（`API_CONTRACTS.md:323-340`）；实现计划要求研究员验证 Insight 后再转成 Brief（`IMPLEMENTATION_PLAN.md:97-114`、`IMPLEMENTATION_PLAN.md:143-147`）。
- **冲突**：同一份研究会出现“已验证 Insight”和“Decision Brief”两个可长期审核、版本化、被视为结论的对象，直接制造产品文档明确禁止的竞争性 Source of Truth。
- **单一裁决**：`Insight` 只保留为 Investigation 所属的中间综合快照，推荐工程名 `InvestigationSynthesisVersion`；它可以有来源版本和人工采用记录，但不能拥有独立导航、独立长期决策状态、独立 Owner 或 `Accepted/Actioned/Monitoring` 生命周期。长期决策对象只有 Product Decision Brief。
- **应修改文件**：`ARCHITECTURE.md`、`DATA_MODEL.md`、`API_CONTRACTS.md`、`PROJECT_STRUCTURE.md`、`IMPLEMENTATION_PLAN.md`、`QUALITY_GATES.md`、`SECURITY_MODEL.md`、`EVALUATION_PLAN.md`、`SEED_DATASET_SPEC.md`、`ADR/0002-evidence-versioning.md`、`ADR/0003-bounded-research-graph.md`。

### P0-03 — Product Decision Brief 与 PRD Research Input 被错误合并为 generic Deliverable

- **证据**：产品规定 Decision Brief 是唯一决策级 Source of Truth（`PRODUCT_BRIEF.md:80-100`），PRD Research Input 只能是绑定 Brief 版本、不可独立编辑的受控导出（`PRODUCT_BRIEF.md:101-107`）；IA 重复该裁决（`INFORMATION_ARCHITECTURE.md:7-12`、`INFORMATION_ARCHITECTURE.md:61-70`、`INFORMATION_ARCHITECTURE.md:132-140`）。最新架构已采用 DecisionBrief/DecisionBriefVersion/BriefExport 并声明版本绑定导出（`ARCHITECTURE.md:5-9`、`ARCHITECTURE.md:225-234`），但数据模型的 `Deliverable` 仍同时包含 Product Decision Brief / PRD Research Input（`DATA_MODEL.md:114-125`），API 从 Insight 创建 “Product Decision Brief / PRD Research Input” 并允许通用 Deliverable 编辑（`API_CONTRACTS.md:323-354`），项目模块也把两者并列放入 Deliverables（`PROJECT_STRUCTURE.md:112-116`），实现计划把二者写成同一个固定输出（`IMPLEMENTATION_PLAN.md:7-14`）。
- **冲突**：PRD Research Input 因此可以获得自己的 draft/body/version，与 Brief 分叉；Decision Brief 则退化为通用 Deliverable 类型，无法承载产品定义的固定块、PM Judgment、Decision-ready 与 Decided 语义。
- **单一裁决**：建立专用 `ProductDecisionBrief` aggregate、`BriefVersion` 与 typed blocks；PRD Research Input 不建可编辑内容对象，只建 `PRDResearchInputExport` 不可变记录，绑定一个 `brief_version_id`、块选择、格式、操作者和时间。Preview 是临时投影，不是持久化文档。
- **应修改文件**：`ARCHITECTURE.md`、`DATA_MODEL.md`、`API_CONTRACTS.md`、`PROJECT_STRUCTURE.md`、`IMPLEMENTATION_PLAN.md`、`QUALITY_GATES.md`、`SEED_DATASET_SPEC.md`。

### P0-04 — Evidence 不可变已定义，但 Claim/Brief 的版本链不完整

- **证据**：ADR 要求 Evidence 绑定不可变 ContentVersion，并声称 Claim/Insight/Deliverable 保留版本快照（`ADR/0002-evidence-versioning.md:6-16`）；用户流程规定 Revise Claim 会创建新版本（`USER_FLOWS.md:159-166`）。数据模型只有可变 `Claim.text/status/row_version`，没有 `ClaimVersion`，ClaimEvidence 只指向 Claim（`DATA_MODEL.md:100-112`）；DeliverableVersion 仅以通用 JSON 声称保存引用（`DATA_MODEL.md:114-125`）。API 的 Claim 表示和审核只接受 `claim_id`/row version（`API_CONTRACTS.md:138-169`、`API_CONTRACTS.md:266-288`），创建 Deliverable 时仍只提交 `claim_ids`/`evidence_ids`（`API_CONTRACTS.md:342-354`）。
- **冲突**：Claim 文本修订后，旧 Brief/导出可能仍指向同一 Claim ID 却解释成新文本；row_version 是并发控制，不是不可变领域版本。现有合同不能重放“当时哪一版 Claim 支撑哪一版 Brief”。
- **单一裁决**：新增不可变 `ClaimVersion`；`ClaimEvidence` 绑定 `claim_version_id` 和 `evidence_id`；`BriefVersion` 的每个 Fact/AI Synthesis 块必须钉住 `claim_version_id`、`evidence_id`、最终 `content_version_id`。修改 Claim 或 Brief 均创建新版本；row_version 仅用于 aggregate 并发控制。
- **应修改文件**：`ADR/0002-evidence-versioning.md`、`ARCHITECTURE.md`、`DATA_MODEL.md`、`API_CONTRACTS.md`、`QUALITY_GATES.md`、`SEED_DATASET_SPEC.md`。

### P0-05 — 产品、架构与 API 使用互不兼容的状态机

- **证据**：IA 的 Signal、Investigation、Brief 状态分别见 `INFORMATION_ARCHITECTURE.md:230-265`；UI 的 Investigation/Decision 状态见 `UI_SPEC.md:587-610`。最新架构虽已删除 Signal `Converted` 并加入 DecisionBrief，但仍把 `Queued/Running/Failed` 同时放进 Investigation，又为 ResearchRun 定义同类执行状态，并保留独立 Insight/BriefExport 状态（`ARCHITECTURE.md:168-204`）。用户流程同样把 Run 失败写成 Investigation `Failed`，Resume 则创建新 Run（`USER_FLOWS.md:192-210`）。API 未公布完整枚举，只说“server-defined”，同时仍围绕 ResearchRun/Insight/Deliverable 提供命令（`API_CONTRACTS.md:218-240`、`API_CONTRACTS.md:323-354`）。
- **冲突**：同一个 UI 状态无法唯一映射到一个领域状态；Run 的失败会错误终止或改写 Investigation；Brief 的 Decision-ready/Decided 与 Deliverable 的 Export 审批状态没有对应关系；API 合同无法生成稳定客户端枚举和 transition tests。
- **单一裁决**：采用本报告第 10 节的统一状态机；Investigation、ResearchRun、ClaimVersion、Brief、Export 分开建模，`evidence_stale` 作为 Brief 正交标记，导出状态不得代替决策状态。所有枚举、允许迁移、命令前置条件和 RunEvent 必须由同一合同生成。
- **应修改文件**：`INFORMATION_ARCHITECTURE.md`、`USER_FLOWS.md`、`UI_SPEC.md`、`ARCHITECTURE.md`、`DATA_MODEL.md`、`API_CONTRACTS.md`、`PROJECT_STRUCTURE.md`、`QUALITY_GATES.md`。

## 4. P1 发现

### P1-01 — 单一 PM MVP 与完整五角色协作/RBAC 被混在同一阶段

- **证据**：产品明确 MVP 先保证单一 PM，复杂权限、评论、审批 Later（`PRODUCT_BRIEF.md:34-49`、`PRODUCT_BRIEF.md:175-183`）；IA 不设计 Team/Audit Log 或 permission denied 页面（`INFORMATION_ARCHITECTURE.md:61-70`、`INFORMATION_ARCHITECTURE.md:267-279`）。数据模型已固定 Owner/Admin/Analyst/Contributor/Viewer（`DATA_MODEL.md:38-47`），Security 定义完整权限矩阵（`SECURITY_MODEL.md:21-43`），API 暴露 assignments 且用 Analyst+ 约束主流程（`API_CONTRACTS.md:171-185`、`API_CONTRACTS.md:204-216`、`API_CONTRACTS.md:231-242`），质量门要求所有角色与 permission denied 状态（`QUALITY_GATES.md:48-70`），而实现计划又把角色/协作放到 Phase 4（`IMPLEMENTATION_PLAN.md:116-132`）。
- **冲突**：多租户隔离基础与多人协作产品能力没有分层，Phase 1 无法判断要实现单用户、完整 RBAC，还是只保留未来字段。
- **单一裁决**：Phase 1 保留真实 workspace/tenant 隔离、RLS、单一 `owner/operator` membership 和审计主体；不实现 assignments、评论、审批 UI 或五角色行为矩阵。五角色 enum 可作为不可达的未来 schema 预留，不能进入 MVP API/验收；Phase 4 再激活迁移和 UI。
- **应修改文件**：`PRODUCT_BRIEF.md`（关闭待拍板项）、`ARCHITECTURE.md`、`DATA_MODEL.md`、`API_CONTRACTS.md`、`SECURITY_MODEL.md`、`QUALITY_GATES.md`、`IMPLEMENTATION_PLAN.md`、`INFORMATION_ARCHITECTURE.md`、`UI_SPEC.md`。

### P1-02 — Phase 1 同时被称为“真实最薄切片”“完整 Shell”和“placeholder research”

- **证据**：UI 规范面向 Phase 1 Mac UI Shell，并定义全部 MVP 表面（`UI_SPEC.md:1-28`）；架构允许展示完整核心导航，但只有一条切片有真实行为，同时要求只实现切片所需对象（`ARCHITECTURE.md:5-11`、`ARCHITECTURE.md:238-248`）；实现计划又说 Phase 1 不是完整 Shell，却包含 “research placeholder” 到 Brief（`IMPLEMENTATION_PLAN.md:53-78`），真实 GitHub/RSS 在 Phase 2、真实 LangGraph Research/Brief 在 Phase 3（`IMPLEMENTATION_PLAN.md:79-115`）。Local Source UI 明确不展示（`UI_SPEC.md:494-512`），但 API 已描述 Local Source/上传流程（`API_CONTRACTS.md:187-202`）。
- **冲突**：若完整导航先出现，会违反“无假入口”；若 placeholder 也被称为 real vertical loop，会混淆 design complete、data authentic 与 runtime complete。
- **单一裁决**：Phase 1 是**标记为 Seed/CSV 的可运行合同骨架**，但 Investigation、版本链、Brief 与恢复路径必须是真实领域行为；只显示已经接通的入口。完整 UI 可 design complete，但未接通页面不得进入可点击构建。Local Source 仅保留 ADR/schema seam，不进入 MVP OpenAPI 可调用面或 UI。
- **应修改文件**：`IMPLEMENTATION_PLAN.md`、`ARCHITECTURE.md`、`UI_SPEC.md`、`PRODUCT_BRIEF.md`、`API_CONTRACTS.md`、`PROJECT_STRUCTURE.md`。

### P1-03 — 安全、审计和 Eval 的前移原则正确，但阶段归属仍冲突

- **证据**：Security 明确安全是 walking skeleton 发布要求（`SECURITY_MODEL.md:3-8`），并要求真实数据 pilot 前完成授权、版本、注入、SSRF、Evidence 完整性验证（`SECURITY_MODEL.md:113-125`）；Quality 让 security/eval 从 Phase 1 生效（`QUALITY_GATES.md:16-29`）。架构首批对象包含 PromptVersion、EvaluationDataset/Run、AuditLog，并说 permissions/audit 必须真实（`ARCHITECTURE.md:238-242`），但实现计划把 Langfuse/full eval 放 Phase 3，把 audit log 放 Phase 4（`IMPLEMENTATION_PLAN.md:97-127`）。
- **冲突**：若按 Implementation Plan 字面执行，Phase 1/2 的真实来源和写命令先于可审计安全控制；若按 Security/Quality 执行，Phase 1 范围又明显扩大。
- **单一裁决**：Phase 1 必须包含最小后端 AuditLog、RLS/authorization、idempotency、secret redaction、固定 seed eval 与注入测试；Phase 3 只增加完整质量 eval/trace；Phase 4 只增加 Audit/Evaluation 的团队 UI 和复杂权限，不得延后底层控制。
- **应修改文件**：`IMPLEMENTATION_PLAN.md`、`QUALITY_GATES.md`、`SECURITY_MODEL.md`、`ARCHITECTURE.md`、`PROJECT_STRUCTURE.md`、`RISK_REGISTER.md`。

### P1-04 — Signal 四维存在责任和派生规则冲突

- **证据**：产品规定 Detection 只描述检测，Impact/Urgency 必须 PM 确认，Priority 仅在两者确认后派生（`PRODUCT_BRIEF.md:109-125`）；IA/UI 重复“未确认不显示 Priority”（`INFORMATION_ARCHITECTURE.md:190-204`、`UI_SPEC.md:280-306`），但 UI 又允许 PM 覆盖 Priority（`UI_SPEC.md:302-306`）。架构让 Urgency 使用 time decay/alert policy，让 Priority 再混入 assignment/SLA（`ARCHITECTURE.md:128-139`）；API 示例没有 suggested/confirmed/actor 字段却直接返回 Impact、Urgency、P2，并允许 priority override（`API_CONTRACTS.md:90-136`、`API_CONTRACTS.md:218-229`）。
- **冲突**：客户端无法区分 AI 建议与 PM 确认；单 PM MVP 又被 assignment/SLA 影响；Priority 可被直接覆盖后不再是透明派生维度。
- **单一裁决**：Detection 只读且由 detector 产生；Impact/Urgency 各有 `suggested_level` 与 `confirmed_level/confirmed_by/confirmed_at`；任一未确认时 Priority 为 `null/pending`；MVP Priority 只由已确认 Impact+Urgency 和版本化矩阵派生，不允许直接 override，也不纳入 assignment/SLA。
- **应修改文件**：`PRODUCT_BRIEF.md`、`UI_SPEC.md`、`ARCHITECTURE.md`、`DATA_MODEL.md`、`API_CONTRACTS.md`、`QUALITY_GATES.md`。

### P1-05 — Agent 工具“只读”没有被写成不可绕过的合同

- **证据**：ADR/架构正确限定单个有界 LangGraph、LLM 只产 proposal、Domain Service 持久化（`ADR/0003-bounded-research-graph.md:6-16`、`ARCHITECTURE.md:141-166`）；Project Structure 也要求领域服务拥有写入（`PROJECT_STRUCTURE.md:90-100`）。但 Security 把 `write proposal` 与 “human-approved external export” 都列成 tool capability（`SECURITY_MODEL.md:69-80`），并笼统称 LLM/tool/worker 可创建 proposal（`SECURITY_MODEL.md:45-49`）。
- **冲突**：这允许实现者把 proposal persistence 或 export 包装成 Agent 可调用写工具；“有人类批准”不等于 Agent 工具只读，也会绕开普通 REST command 的幂等/状态前置条件。
- **单一裁决**：Research Graph 暴露给模型的工具只允许读取已授权、已钉版本的内容与确定性计算；proposal 是节点输出数据，不是写工具。只有 worker orchestration 调用 Domain Service proposal command；review、状态迁移、导出均是图外 REST/Domain commands，并要求人类 actor、幂等键和版本前置条件。
- **应修改文件**：`SECURITY_MODEL.md`、`ARCHITECTURE.md`、`ADR/0003-bounded-research-graph.md`、`PROJECT_STRUCTURE.md`、`API_CONTRACTS.md`。

### P1-06 — SSE 恢复主方向一致，但快照、过期游标和事件目录不一致

- **证据**：架构规定先 GET snapshot，再以 Last-Event-ID 连接并回放；过期游标发 `stream.reset`（`ARCHITECTURE.md:206-217`）。API 却说每次连接先发 `run.snapshot`，同时又回放持久事件（`API_CONTRACTS.md:290-321`）；公共错误表称 `STREAM_CURSOR_EXPIRED` 是 snapshot endpoint 的 410（`API_CONTRACTS.md:24-40`），与 SSE 的 `stream.reset` 不同。Project Structure 的路径缺 `/v1`，事件目录少 `run.cancelled`，也未列 `stream.reset`（`PROJECT_STRUCTURE.md:119-157`）；Data Model 只定义 RunEvent 表形状（`DATA_MODEL.md:100-110`）。
- **冲突**：客户端无法知道 snapshot 是有序持久事件还是连接握手；游标过期有两种互斥恢复协议；契约测试和生成客户端会基于不同事件枚举。
- **单一裁决**：唯一协议为：先 GET authoritative snapshot；SSE 只回放 `sequence > cursor_sequence` 的持久 RunEvent；未知/过期 Last-Event-ID 以一个无业务 sequence 的 `stream.reset` 控制事件携带 snapshot URL 后关闭。统一 `/v1/research-runs/{id}/events`、完整业务/控制事件枚举，并规定 heartbeat/snapshot/reset 不占业务 sequence。
- **应修改文件**：`ARCHITECTURE.md`、`API_CONTRACTS.md`、`PROJECT_STRUCTURE.md`、`DATA_MODEL.md`、`UI_SPEC.md`、`QUALITY_GATES.md`。

### P1-07 — 质量阈值既被声明“尚未校准”，又出现互相冲突的硬数字

- **证据**：Evaluation Plan 明确 Phase 0 不应伪造阈值，质量阈值应在标注 pilot 后设置（`EVALUATION_PLAN.md:78-90`）。Quality Gates 却给出 Citation ≥0.95、Unsupported Claim ≤0.02、Counter-evidence ≥0.80、Injection 100%（`QUALITY_GATES.md:31-46`）；Product Validation 使用 Citation ≥95%、Unsupported Claim ≤5%，Stop 阈值又是 <90%/>10%（`PRODUCT_VALIDATION_PLAN.md:259-270`、`PRODUCT_VALIDATION_PLAN.md:396-438`）；Product Brief 还把多项漏斗目标写入 MVP（`PRODUCT_BRIEF.md:194-204`）。
- **冲突**：Unsupported Claim 同时有 2% 和 5% 两个“通过目标”；经验性质量/性能目标与不可违反的安全不变量未分层。虽然各文档都警告分档不是概率，但这些数字仍会被误读为已校准承诺。
- **单一裁决**：只把 workspace isolation、授权写入、secret 泄漏、Evidence→ContentVersion 完整性等定义为 100% 安全不变量；其余数字统一标记为 `Phase 0 hypothesis/provisional target`，给出数据集、样本量、分母、owner 和校准日期。Pilot 前不得称 release guarantee；同一指标只能有一个通过线，另设独立 stop line。
- **应修改文件**：`EVALUATION_PLAN.md`、`QUALITY_GATES.md`、`PRODUCT_VALIDATION_PLAN.md`、`PRODUCT_BRIEF.md`、`SEED_DATASET_SPEC.md`。

### P1-08 — Seed fixture 声称复用生产 schema，实际却定义了第二套模型

- **证据**：Seed 规定所有 ID 使用 `seed_` 前缀，并在 ContentItem 内存正文，Claim 使用 `confidence: 0.74` 和 evidence ID arrays（`SEED_DATASET_SPEC.md:7-14`、`SEED_DATASET_SPEC.md:97-149`）。Data Model 规定 ID 为 UUID、正文属于不可变 ContentVersion、Claim 使用 deterministic inputs/level、关系由 ClaimEvidence 表示（`DATA_MODEL.md:3-7`、`DATA_MODEL.md:66-78`、`DATA_MODEL.md:100-112`）；API 同样使用 UUID、ContentVersion 和 typed evidence links（`API_CONTRACTS.md:5-9`、`API_CONTRACTS.md:68-88`、`API_CONTRACTS.md:138-169`）。Seed 文档末尾又声称与生产 schema 相同（`DATA_MODEL.md:146-148`）。
- **冲突**：Phase 1 可以在 seed 路径通过、真实路径失败；`seed_` ID 甚至不能通过 UUID contract；Seed Claim 的裸 0.74 还违反未校准数值呈现原则。
- **单一裁决**：Seed 使用生产 UUID/Pydantic/数据库 schema；真实性由 `data_authenticity=seed`、seed workspace/source 和可见标签表达，不编码在 ID 类型里。正文必须建立 ContentVersion，Claim 必须建立 ClaimVersion/ClaimEvidence，数值输入只存内部并标 `uncalibrated`。
- **应修改文件**：`SEED_DATASET_SPEC.md`、`DATA_MODEL.md`、`API_CONTRACTS.md`、`QUALITY_GATES.md`。

### P1-09 — MVP 离线只读与离线 drafts/sync operations 互相冲突

- **证据**：产品、IA、流程和 UI 均只承诺最近对象离线只读，明确禁用 Brief edit/export（`PRODUCT_BRIEF.md:164-173`、`INFORMATION_ARCHITECTURE.md:267-279`、`USER_FLOWS.md:241-247`、`UI_SPEC.md:567-574`）。最新架构也已改为 read-only local cache 并排除 MVP offline editing（`ARCHITECTURE.md:13-20`、`ARCHITECTURE.md:55-65`），但 Data Model 仍把 SQLite 用于 local drafts/synchronization operations（`DATA_MODEL.md:3-7`），API 仍提供 `/sync/operations` 和冲突结果（`API_CONTRACTS.md:356-368`）。
- **冲突**：一旦存在离线 draft/sync command，就必须设计冲突、授权过期、版本合并与恢复；这正是产品明确 Later 的能力。
- **单一裁决**：MVP SQLite 只缓存只读 projection、窗口偏好和未提交的本地表单 UI state；离线时不接受领域 mutation，不建立 `/sync/operations`。完整 offline draft queue/conflict resolution 整体延期，不能以隐藏 API 形式提前进入 Phase 1。
- **应修改文件**：`ARCHITECTURE.md`、`DATA_MODEL.md`、`API_CONTRACTS.md`、`PROJECT_STRUCTURE.md`、`PRODUCT_BRIEF.md`、`USER_FLOWS.md`、`UI_SPEC.md`。

## 5. P2 发现

### P2-01 — 辅助文档仍使用旧 IA 词汇

- **证据**：Risk Register 的 R-002 mitigation 把 Signals/Watchlists/Research/Insights/Sources/Brief 称为 primary loop（`RISK_REGISTER.md:19-24`），与 canonical `Inbox / Investigations / Decisions / Monitoring`（`INFORMATION_ARCHITECTURE.md:5-28`）相反；Evaluation Plan 继续使用 Alert Precision/Recall 和 Insight Acceptance（`EVALUATION_PLAN.md:9-21`、`EVALUATION_PLAN.md:44-60`）。
- **冲突**：不会改变代码合同，但会让风险和评测继续围绕已废弃对象命名。
- **单一裁决**：统一用 Signal、Investigation、Decision Brief；需要统计术语时使用 `Signal precision/recall`，Insight 仅写作 `Investigation synthesis`。
- **应修改文件**：`RISK_REGISTER.md`、`EVALUATION_PLAN.md`、`QUALITY_GATES.md`。

### P2-02 — 验证计划的标题层级产生重复锚点

- **证据**：Stage A–E 下的“方法”均与 Stage 标题同为 H3（例如 `PRODUCT_VALIDATION_PLAN.md:111-117`、`PRODUCT_VALIDATION_PLAN.md:138-144`、`PRODUCT_VALIDATION_PLAN.md:173-179`、`PRODUCT_VALIDATION_PLAN.md:206-212`、`PRODUCT_VALIDATION_PLAN.md:245-249`）；“方法”“任务”“通过阈值”分别生成重复 Markdown anchor。
- **冲突**：目录/深链不稳定，子节层级错误；正文含义不受影响。
- **单一裁决**：Stage 保持 H3，其内部 Method/Tasks/Thresholds 降为 H4，并为重复标题加 Stage 前缀或唯一 anchor。
- **应修改文件**：`PRODUCT_VALIDATION_PLAN.md`。

## 6. 已通过的关键决策

1. **产品一级语言已在产品/设计文档收敛**：Inbox / Investigations / Decisions / Monitoring；Research Run 是 Investigation 内的技术执行（`PRODUCT_BRIEF.md:66-78`、`INFORMATION_ARCHITECTURE.md:5-28`、`UI_SPEC.md:18-28`）。
2. **UI 三栏规则通过**：Navigation / List / Detail 清楚，Filter sheet/chips 不形成第四栏，Evidence drawer 仅在 Detail 内或 overlay（`INFORMATION_ARCHITECTURE.md:142-176`、`UI_SPEC.md:30-60`、`UI_SPEC.md:166-197`、`UI_SPEC.md:455-461`）。
3. **无假入口原则通过**：Later/Non-goals 不应出现在导航、命令或 Coming Soon 页面（`PRODUCT_BRIEF.md:185-193`、`INFORMATION_ARCHITECTURE.md:61-71`、`UI_SPEC.md:18-28`）。P1-02 要求实现阶段继续遵守。
4. **Evidence → immutable ContentVersion 通过**：ADR、数据模型、API、Source Viewer 和安全测试方向一致（`ADR/0002-evidence-versioning.md:6-16`、`DATA_MODEL.md:66-78`、`API_CONTRACTS.md:68-88`、`UI_SPEC.md:540-561`、`SECURITY_MODEL.md:113-125`）。缺口仅在 Claim/Brief 后续版本链。
5. **单个有界 LangGraph 通过**：固定图、固定 schema、persisted human gates、禁止多 Agent/任意工具/直接提交领域数据的方向一致（`ARCHITECTURE.md:141-166`、`ADR/0003-bounded-research-graph.md:6-16`）。P1-05 只要求把“Agent 工具只读”写死。
6. **Domain Service 与 proposal 边界通过**：Agent/LLM 输出为 proposal，授权、schema、source policy、audit 后才持久化（`ARCHITECTURE.md:153-166`、`PROJECT_STRUCTURE.md:90-100`、`SECURITY_MODEL.md:101-105`）。
7. **RunEvent、幂等和乐观并发的基本方向通过**：append-only RunEvent、run 内 sequence、event_id 去重、命令 Idempotency-Key、If-Match/row version 已被同时写入架构/API/数据模型（`ARCHITECTURE.md:206-223`、`API_CONTRACTS.md:11-22`、`DATA_MODEL.md:100-110`）。P1-06 是协议细节未收口。
8. **Design / production code / data authenticity / runtime integrity 四种完成态通过**：定义清楚且 Quality Gates 重复确认（`IMPLEMENTATION_PLAN.md:134-142`、`QUALITY_GATES.md:5-14`）。
9. **分数不是已校准概率通过**：Signal 和 Claim 的 Low/Medium/High 被明确标为 heuristic/uncalibrated，UI 禁止展示虚假概率（`ARCHITECTURE.md:128-139`、`DATA_MODEL.md:80-112`、`EVALUATION_PLAN.md:38-43`、`UI_SPEC.md:624-632`）。
10. **Cloud / Local / Imported 边界通过**：三者的运行位置、凭证与上传同意边界一致（`ARCHITECTURE.md:88-100`、`ADR/0004-local-cloud-source-boundary.md:6-16`、`SECURITY_MODEL.md:90-99`）。是否进入 MVP API 由 P1-02 裁决。
11. **Markdown 基础完整性通过**：21 个输入文件均恰有一个 H1；代码围栏成对；4 个本地相对 Markdown 链接均解析到现有文件。唯一结构问题见 P2-02。

## 7. 阻塞 Phase 1 的问题

以下五项必须全部关闭，不能以实现时再决定替代：

1. 新增并锁定 Investigation aggregate 与 API 路由。
2. 将 Insight 降为 Investigation 内中间综合，不再是长期决策对象。
3. 将 Product Decision Brief 建为唯一专用 aggregate；PRD Research Input 改为 BriefVersion 绑定的不可变导出记录。
4. 补齐 ContentVersion → Evidence → ClaimVersion → BriefVersion → Export 的不可变引用链。
5. 采用一套统一状态机，并从同一 schema 生成 API enum、RunEvent、客户端状态与 transition tests。

P1-01、P1-02、P1-03、P1-08 也应在 Phase 1 第一个代码变更前关闭，因为它们决定权限、可见入口、必需安全控制和 seed contract；其余 P1 可按对应切片开工门解决，但不得晚于相关实现。

## 8. 可延后问题

以下事项不阻塞 Phase 1 的最薄真实切片，前提是文档明确保持 Later 且不出现入口：

- 产品名与旧工作名的最终命名（`PRODUCT_BRIEF.md:228-234`）。
- `Decided` 是否在首个 UI 切片可操作；领域状态可以先定义，Phase 1 UI 可停在 Decision-ready + Markdown export。
- 多窗口 Decision Brief、完整 Settings 页面和 UI 密度偏好。
- 完整离线编辑、sync queue 与冲突解决。
- Local/cookie connector、Agent Reach、社交平台与任意网页抓取。
- PDF、Google Docs/Notion/Jira、Slack/Email 与自动发布。
- Saved Views、Today、Explore、Contextual AI、Evaluations dashboard。
- 五角色协作、评论、指派、多人审批和 Audit Log UI；底层 workspace isolation 与最小 AuditLog 不能延后。
- 经验性 Signal/Claim calibration；校准前继续使用解释性 heuristic band。
- P2 的辅助术语与重复标题清理。

## 9. 建议的 canonical vocabulary

| Canonical term | 类型/归属 | 单一定义 | 禁止替代/混用 |
|---|---|---|---|
| Inbox | UI queue | 等待 PM 处理的 Signal 列表 | Signals Dashboard、Today |
| Monitoring | UI destination | Watchlist 与 SourceConnection 的管理入口 | Watchlists/Sources 两个一级入口 |
| Watchlist | Aggregate | 版本化监控问题、范围、来源、基线和检测规则 | Project dashboard |
| Signal | Aggregate | detector 发现、尚未成为产品结论的可解释变化 | Alert、Issue、Insight |
| Investigation | Aggregate | 围绕一个 Decision Question 的持续证据工作容器 | Research、Run、Thread |
| ResearchRun | Execution record | Investigation 内一次使用固定 manifest/预算/图版本的执行 | Investigation、Agent session |
| RunEvent | Append-only event | 一个 ResearchRun 内按 sequence 排序、可回放的领域执行事件 | LangGraph internal event |
| ContentItem | Logical identity | 外部内容的逻辑身份，可有多个版本 | 可引用原文快照 |
| ContentVersion | Immutable version | 可引用、可复现的不可变内容版本 | mutable ContentItem body |
| Evidence | Domain record | 钉住一个 ContentVersion 及 quote range/digest、立场和审核状态 | AI 摘要、裸 URL |
| Claim / ClaimVersion | Aggregate + immutable version | 可被 Evidence 支持/反对的最小结论及其不可变修订版本 | 未审核 Fact |
| Investigation synthesis | Intermediate version | Investigation 内基于已选 ClaimVersion 的中间综合；可供 Brief 采用 | 独立 Insight 库、Decision |
| Product Decision Brief | Sole decision aggregate | 唯一决策级、可版本化产物，包含 Fact/AI Synthesis/PM Judgment/Recommendation | generic Deliverable、Report、Insight |
| BriefVersion | Immutable version | 一个 Brief 的不可变内容与引用快照 | row_version |
| PRD Research Input | Export view | 从一个 BriefVersion 投影出的受控 Preview | 独立可编辑文档 |
| PRDResearchInputExport | Immutable audit record | 实际 Copy/Export 的版本、块选择、格式、actor/time 记录 | Deliverable draft |
| Decision-ready | Brief state | 完整性门通过，可进入评审 | 已决定、已导出 |
| Decided | Brief state | PM 已记录决定、理由和 checkpoint | Accepted recommendation |
| Detection Confidence | Signal dimension | detector 对“变化是否真实且非采集/重复噪声”的 heuristic band | 事实正确率、Impact |
| Business Impact | Signal dimension | PM 对“若属实影响多大”的确认评估 | detector confidence |
| Urgency | Signal dimension | PM 对“多快处理”的确认评估 | Priority |
| Priority | Derived dimension | 已确认 Impact + Urgency 经版本化矩阵派生的队列等级 | 概率、Severity、直接 AI 评分 |

## 10. 推荐统一状态机

### 10.1 Signal

```text
new → triaged → investigating → explained
  ├──────────────→ monitoring
  └──────────────→ dismissed
triaged/explained → monitoring | dismissed
monitoring → new            # 新的独立变化打破 cooldown 时创建新事件/重新入箱
```

裁决：删除 `converted`；Brief 创建不改变 Signal 为另一种产品对象。`detection_confidence` 是 detector 输出；Impact/Urgency 确认与 Priority 派生记录为版本化 assessment/audit，不另造 Signal 状态。

### 10.2 Investigation

```text
draft → active → reviewing → completed
          │          └────→ closed_insufficient
          └→ needs_input → active | reviewing
draft | active | needs_input | reviewing → cancelled
```

裁决：Investigation 不使用 `queued/running/failed`，这些属于 ResearchRun。一个 Run 失败后 Investigation 保持 active/needs_input，用户可创建新 Run；Evidence insufficient 是 `closed_insufficient` 或 reviewing outcome，不伪装成 completed。

### 10.3 ResearchRun

```text
queued → running → completed
            ├──→ waiting_for_input → running
            ├──→ failed
            └──→ cancelled
```

`waiting_for_input.reason` 使用闭合枚举：`scope_clarification`、`plan_change`、`budget_change`、`claim_review`、`source_policy`。每次 resume 继续同一 manifest/checkpoint；范围、预算或 manifest 改变时创建新 attempt/Run，不改写旧 Run。

### 10.4 Evidence 与 ClaimVersion

```text
Evidence: proposed → valid | weak | rejected
ClaimVersion: proposed → needs_review → verified | rejected
ClaimVersion: verified → superseded       # 仅由新版本替代，旧版本不改写
```

裁决：Revise 永远创建新 ClaimVersion；BriefVersion 只能把 verified ClaimVersion 映射为 Fact，未验证内容若被强制包含必须保持 Unverified 类型和警告。

### 10.5 Product Decision Brief

```text
draft → decision_ready → decided → archived
  └──────────────────────────────→ archived
```

`evidence_stale` 是任何非 archived BriefVersion 上的正交 freshness flag，不是主状态。对 decision-ready/decided 内容的修改创建新 BriefVersion，并让新版本从 draft 重新通过完整性门；旧版本和旧导出保持不变。

### 10.6 PRD Research Input

Preview 是 BriefVersion 的无状态投影；实际 Copy/Export 直接创建不可变 `PRDResearchInputExport`。它不需要 `Draft/Reviewed/ApprovedForExport/Exported` 内容状态机；高风险外部发送若未来加入，应建独立 `ExportCommand` 审批状态，而不是改变 Brief 状态。

### 10.7 SSE 与命令边界

- REST command 是唯一状态迁移入口，要求 `Idempotency-Key`、actor、expected version/If-Match。
- Domain Service 在同一事务提交状态和 RunEvent，再通过 outbox/tailer 发布。
- SSE 只读、至少一次；客户端按 event_id 去重，只应用更大的 run sequence。
- heartbeat、`stream.reset` 等控制帧不占业务 sequence；RunEvent 本身不可改写。

## 11. 推荐 Phase 顺序

| Phase | 唯一目标 | 必须先有 | 明确不含 |
|---|---|---|---|
| Phase 0 | 锁定本报告 P0/P1 合同与风险证据 | canonical vocabulary、聚合/版本/状态/API、许可证据 | 生产业务代码 |
| Phase 1 | 单 PM、Seed/CSV、真实领域合同的 walking skeleton | tenant isolation、最小 AuditLog、安全/eval smoke、Investigation→Brief→Markdown | 完整 Shell、Local connector、五角色协作、placeholder 入口 |
| Phase 2 | GitHub/RSS 持续采集与 explainable Signal | source contract、ContentVersion、幂等/恢复、Signal 四维合同 | 完整 LLM research |
| Phase 3 | 单个有界 LangGraph、Evidence/Claim 审核与 Decision Brief 质量 | read-only tools、ClaimVersion、eval dataset、citation gates | 多 Agent、自动发布 |
| Phase 4 | 协作、更多来源与输出扩展 | 核心 pilot 通过、许可/ToS/security review | 破坏现有聚合的平行对象模型 |

## 12. 最终 Go / Conditional Go / No-Go

**最终裁决：No-Go。**

该结论只针对进入 Phase 1 实现，不否定继续做文档裁决、原型和验证准备。理由是 P0-01 至 P0-05 让核心对象、版本链和状态合同尚不可同时实现；此时开始 scaffolding 或生成 API/client schema，会把旧 `Insight/Deliverable` 模型固化并制造高成本迁移。

重新审查的最低条件：

1. 5 项 P0 在所有受影响文档中采用同一裁决；
2. ER 图、模块图、OpenAPI 资源、状态枚举和质量门使用同一 canonical vocabulary；
3. Seed fixtures 能通过生产 schema；
4. Phase 1 明确为单 PM、无假入口、带最小安全/审计/eval 的真实合同骨架；
5. REUSE Approved 项具备可复核、版本绑定的官方证据。

达到以上条件后，可转为 **Conditional Go**，条件是 Phase 1 contract/integration/E2E/security/eval smoke 全部通过；在此之前不建议进入生产实现。
