# Glint Phase 0 UI Specification

> 目标：为 Phase 1 Seed/Imported CSV 最薄真实闭环及 Phase 2 GitHub/RSS 扩展提供可直接实现的界面规范。本文可以把后续表面做到 design complete，但生产构建只显示当前阶段已经接通的入口与状态；Later 不制作可点击占位。

## 1. 设计目标

Glint 应像一款专业、克制、高密度的 Mac 工作软件。默认界面帮助 PM 处理任务，而不是展示“AI 能力”：

- 启动进入 Inbox，而不是 Chat 或 Dashboard；
- 先展示发生了什么、为什么入箱、有哪些限制；
- 默认使用业务语言，技术 Trace 按需展开；
- 列表与详情保持上下文，键盘操作与鼠标等价；
- 状态依赖文字、图标和结构，不仅依赖颜色；
- 视觉层级区分事实来源与作者责任。

参考原则可借鉴 Linear 的密度、Feedly 的监控组织和 macOS Mail / Finder 的分栏行为，但不复制品牌、图标或完整布局。

## 2. MVP 可见表面

下表是完整 MVP 的可见表面上限，不等于 Phase 1 同时上线全部页面。Phase 1 只构建已接通的 Inbox → Investigation → Decision Brief 路径和最小 Monitoring 导入/状态面；Phase 2 才激活 GitHub/RSS source-health 能力，Phase 3 才激活 LangGraph 产生的研究执行体验。未接通的表面不进入侧栏、Command Palette、深链或权限可达范围。

| 表面 | MVP 能力 | 不出现的入口 |
|---|---|---|
| Main window | Inbox、Investigations、Decisions、Monitoring | Today、Explore、Reports、Team、Evaluations |
| Source Viewer | 原文版本、引用高亮、Evidence 元数据与审核 | 对原文自由 Chat |
| Decision Brief view | 主窗口打开 Brief、来源 drawer、受控导出 | 独立多窗口、完整 Report Center |
| Command Palette | 当前可执行的导航与对象动作 | Later 命令、自动化 |
| Settings | Workspace 基本信息、Theme、Shortcuts、cache info | 未实现的复杂权限 / Prompt 管理 |

Quick Capture、Menu Bar 快捷工作流、Context Agent、PDF editor 属于 Later，不在 MVP Shell 预留可点击按钮。

## 3. 全局窗口与布局

### 3.1 Main window

```text
┌────────────────────────────────────────────────────────────────────┐
│ Traffic lights  Workspace / Project      Search   ⌘K   Data status │  42 px
├───────────────┬──────────────────────┬─────────────────────────────┤
│ Navigation    │ List / Queue         │ Detail                      │
│ 224 px        │ 380 px               │ flexible, min 520 px        │
│               │                      │                             │
│ Inbox         │ list header          │ object header               │
│ Investigations│ quick filters        │ primary content             │
│ Decisions     │ list rows            │ evidence / actions          │
│               │                      │                             │
│ Monitoring    │                      │                             │
│               │                      │                             │
│ data status   │                      │                             │
└───────────────┴──────────────────────┴─────────────────────────────┘
```

尺寸规则：

- Toolbar：42 px；拖拽区域避开 Traffic Lights 与可点击控件。
- Sidebar：216–232 px，默认 224 px，可折叠。
- List：340–440 px，默认 380 px，可拖拽。
- Detail：剩余宽度，最小 520 px；正文最佳阅读宽度 680–840 px。
- 默认最小窗口：960 × 640；低于 1000 px 时 Detail 作为覆盖式页面打开。
- 1000–1350 px 显示三栏；大于 1350 px 允许在 Detail 内打开 320–400 px Evidence drawer。
- 不提供常驻第四栏 Context Agent。
- 按 Workspace 保存窗口尺寸、分栏宽度、最后页面、筛选和选中对象。

### 3.2 Toolbar

从左至右：

1. Traffic Lights 保留区；
2. Sidebar toggle；
3. Workspace / Project breadcrumb；
4. 全局搜索按钮（显示 `⌘P`）；
5. Command Palette（显示 `⌘K`）；
6. Data status：`Current`、`Syncing`、`Offline · cached 10:42`、`Source degraded`。

Data status 可点击时只打开已实现的同步 / Source 状态摘要，不显示虚假通知中心。

### 3.3 Sidebar

```text
WORK
  Inbox             4
  Investigations    1
  Decisions         2

MANAGE
  Monitoring        Degraded
```

- 行高 30 px；图标 16 px；标签 13 px。
- 当前项使用 surface + 强调文字 / 左侧 2 px indicator，不能只用颜色。
- 徽标为可行动计数：Unreviewed、Needs input、Draft；最大显示 `99+`。
- `Monitoring` 的异常徽标显示 `Degraded` 或 warning 图标，不显示所有 Source 数量。
- 徽标只读取 workspace-scoped `GET /v1/navigation-summary` 的精确聚合与 computed_at，不能从当前 cursor page 猜总数；当前阶段未激活的目的地不请求也不渲染徽标。
- 底部 Workspace menu 包含 Settings、Theme、Keyboard shortcuts。

## 4. 视觉系统

### 4.1 Grid 与尺寸

- 基础网格：4 px。
- 常规控件高度：28 / 32 px；主按钮 32 px。
- Sidebar 行：30 px。
- Dense table 行：36 px。
- Signal 行：76–92 px，默认 84 px。
- List header：44 px；含 chips 时最多增至 76 px。
- Detail header：64–80 px。
- Section 间距：24 px；相关字段间距：8–12 px。
- Border：1 px。
- Radius：控件 4 px、容器 6 px、Modal 10 px。
- 长列表不使用阴影；Popover / Modal 只用轻量 elevation。

### 4.2 字体

使用系统字体栈：

```css
-apple-system, BlinkMacSystemFont, "SF Pro Text", "PingFang SC",
"Helvetica Neue", Arial, sans-serif
```

| 样式 | 大小 / 行高 | 字重 |
|---|---|---|
| Page title | 19 / 26 | 600 |
| Object title | 17 / 24 | 600 |
| Section title | 14 / 20 | 600 |
| Body | 13 / 20 | 400 |
| Dense row | 12.5 / 18 | 400 |
| Metadata | 11.5 / 16 | 400 |
| Label | 11.5 / 16 | 500 |
| Monospace | 11.5 / 17 | 400 |

正文允许系统字体缩放；列表密度可在 Settings 中选择 Comfortable / Compact 属于 Later，MVP 固定默认密度。

### 4.3 语义颜色

必须使用 token，不在组件内写业务色：

- `background`
- `surface`
- `surface-elevated`
- `sidebar`
- `border`
- `border-strong`
- `text-primary`
- `text-secondary`
- `text-tertiary`
- `accent`
- `positive`
- `warning`
- `destructive`
- `info`
- `focus-ring`

Light / Dark / System 均需覆盖。Detection Confidence 和状态必须同时配合文字或图标。

### 4.4 内容来源标签

Decision Brief 使用四个稳定标签：

| 类型 | 标签文案 | 图标语义 | 色彩原则 |
|---|---|---|---|
| Fact | Fact | 引用 / document | 中性，避免把事实涂成“绿色正确” |
| Synthesis | `Deterministic synthesis` / `AI synthesis` / `{origin}-assisted · edited by {name}` | processor；仅 model origin 可用 spark | info 色，仅作来源识别，不暗示正确性 |
| PM Judgment | PM judgment | person / signed | accent，强调责任 |
| Recommendation | Recommendation | arrow / proposal | warning 或中性，状态另行表示 |

标签在块标题左侧；块背景只使用微弱 tint。Recommendation 的 Accepted / Rejected 必须用文字和图标，不能仅靠绿 / 红。

## 5. 共享组件

### 5.1 List header

组成：

- 页面名与可行动数量；
- 当前列表内搜索；
- 1–3 个 Quick filter；
- `Filter` 按钮与已应用数量；
- Sort menu；
- 可选主操作（仅 Monitoring 的 `New Watchlist`）。

列表搜索只过滤当前对象集合；全局搜索使用 `⌘P`。

### 5.2 Filter sheet

筛选不是永久第四栏。

- `Filter` 或 `⌘⇧F` 在中栏上方打开临时 sheet，宽度等于中栏。
- Sheet 覆盖列表但保留 List header，支持键盘导航。
- 底部固定 `Clear all`、`Cancel`、`Apply`。
- Apply 后关闭，条件以 chips 显示在 List header 下方。
- chips 超过一行时折叠为 `+N filters`，不无限增加 List header。
- 点击页面目的地保留各自最后一次筛选；用户自定义 Saved Views 为 Later。
- `<1000 px` 时 sheet 覆盖 List + Detail 可见区域，但不覆盖 Sidebar。

### 5.3 Status badge

格式为 `icon + label`；11.5 px。用于 New、Running、Needs input、Decision-ready、Stale、Degraded 等离散状态。

禁止把 Detection Confidence、Business Impact、Urgency 和 Priority 都做成同样的彩色 badge；评分组件见第 7 节。

### 5.4 Empty / Error panel

只包含：

- 一句状态说明；
- 一句原因 / 边界；
- 一个主恢复动作；
- 必要时一个次操作。

禁止使用装饰性大插画、虚构数字或多个 Coming Soon 卡片。

### 5.5 Source reference

显示：Source type icon、title / identifier、published time、ContentVersion、引用编号。Hover / Focus 展示最小预览；Enter 打开 Source Viewer。

### 5.6 Confirm dialog

用于：

- Start 有预算的 Research Run；
- Cancel run；
- Dismiss 批量 Signal；
- 导出一个 readiness-reviewed DecisionBriefVersion；未验证内容没有强制绕过动作；
- Copy / Export PRD Research Input。

Dialog 必须说明影响、是否可撤销、创建的版本或记录；默认焦点不放在 destructive action。

## 6. Inbox

### 6.1 List

默认排序：`New first → Detection Confidence → freshness`。

Signal row：

以下 GitHub/RSS 内容是 Phase 2 visual reference；Phase 1 使用同一布局但必须显示 `Seed` 或 `Imported dataset · snapshot {time}`，不得伪装成持续采集。

```text
[New] 权限摩擦相关反馈持续上升                 Detected: High
      Claude Code · Permissions
      +186% vs 28d baseline · 42 independent sources
      GitHub + RSS · updated 12m ago                     P2
```

显示规则：

- 标题最多 2 行；
- 变化值必须同时显示比较窗口，不能只写 `+186%`；
- 独立来源优先于原始 mention 数；
- Detection Confidence 显示 `Detected: High / Medium / Low`；
- Priority 仅在 Impact 与 Urgency 都已确认且非 Unknown 时显示 P0–P3；未确认显示 `Needs triage`，任一 Unknown 显示 `Unranked · insufficient input`；
- Unread 使用文字 / dot 与 VoiceOver label；选中行不依赖背景色唯一表达。

### 6.2 Detail 首屏

顺序固定：

1. Header：title、Watchlist、status、freshness；
2. **What changed**：一段确定性变化描述；
3. **Why detected**：3–5 条触发原因；
4. **Data quality & limitations**；
5. **Triage**：Business Impact、Urgency、派生 Priority；
6. Actions：`Start Investigation`、`Keep monitoring`、`Dismiss`。

首屏文案示例：

> 过去 7 天，权限相关负面反馈相较过去 28 天基线上升 186%。42 个独立来源来自 GitHub 与 RSS；增长不是单一帖子驱动。

Why detected 条目示例：

- Current window：143 mentions / 42 independent sources；
- Baseline：过去 28 天的日中位数；
- Cross-source：GitHub 与 RSS 同时增长；
- Duplicate control：149 items 归为 53 independent groups；
- Limitation：RSS 覆盖偏向英文开发者内容。

下方分区：

- Trend：默认图 + 文本摘要 + Data table；
- Samples：Representative / Opposing / Excluded；
- Detection details：阈值、数据健康、冷却；
- Activity：用户 triage 记录。

### 6.3 Triage 评分组件

四个维度不能合并为一个 Severity：

#### Detection Confidence

- 只读；
- 主显示分档和解释；
- 内部分数只在展开的 Detection details 中展示，并注明“用于排序，不是事实正确率”；
- Data degraded 时强制显示 `Confidence limited by source health`。

#### Business Impact

- 建议显示为 `Rule suggested: Medium` 或（仅 Phase 3）`AI suggested: Medium`，并展示 suggestion_version 与依据；
- PM 选择 High / Medium / Low / Unknown；
- 未确认时不生成 Priority。

#### Urgency

- PM 选择 Now / This week / Monitor / Unknown；
- 系统可根据事件时限给出 Suggested，但不能自动确认。

#### Priority

- 系统仅根据两个已确认且非 Unknown 的 Impact + Urgency 派生 P0–P3；
- 任一已确认值为 Unknown 时显示 `信息不足 · 未排序`，Priority 保持 null；这不是 `待确认`，用户可稍后修订 assessment；
- Hover / focus 显示规则；
- MVP 不允许直接覆盖 Priority；PM 需修改 Impact 或 Urgency，系统按版本化矩阵重算并保留审计历史。

## 7. Investigation

### 7.1 List

行内容：

- Decision Question；
- 来源 Signal / Watchlist；
- 状态与当前步骤；
- Evidence count（独立组优先）；
- 更新或等待时长；
- Needs input / Failed 必须高于普通 Running 排序。

### 7.2 Plan preview

从 Signal 点击 Start Investigation 后，以 Detail 内页面打开，不使用小 Modal。字段：

- Decision Question（必填、PM 确认）；
- Goal / expected decision；
- Time window；
- Sources；
- Subquestions；
- Existing evidence；
- Stop conditions；
- Estimated duration / cost range；
- Coverage risks。

主操作：`Run Investigation`。次操作：`Save draft`、`Back to Signal`。未显示的 Source 不能通过自由文本获得授权。

### 7.3 Investigation detail

Header：

- Decision Question；
- status；
- origin Signal；
- cost used / estimated；
- primary contextual action。

Tabs：

1. Overview
2. Evidence
3. Claims
4. Synthesis
5. Runs

#### Overview

显示业务时间线：

```text
✓ Define question
✓ Retrieve evidence          141 items
✓ Deduplicate                53 independent groups
✓ Build candidate claims     4 proposed
● Review counter-evidence    Running
○ Human review
○ Create decision brief
```

高级信息（model、Prompt version、Trace ID、token）放入每个步骤的 `Technical details` disclosure，不默认展开。

#### Evidence

- 顶部分段：Supporting / Opposing / Neutral / Rejected；
- 每行显示 quote、source、published time、independent group、relevance；
- 右侧动作：Valid / Weak / Reject；每次动作追加 exact-EvidenceReview，不原地改 Evidence；
- 数值 score 可在 metadata 展开，不使用虚假精确度占据主层级；
- `No counter-evidence found` 显示搜索范围与 Limitations，不显示成功勾。

#### Claims

Claim card 结构：

- Claim text；
- Hypothesis / Needs review / Verified / Rejected；
- Supporting N / Opposing N；
- Confidence band + inputs；
- sample / diversity / limitations；
- `Verify`、`Revise`、`Reject`、`Find more`；Verify 预览并冻结 ClaimEvidence/EvidenceReview snapshot digest。

Claim 不是聊天消息；不显示 Agent 头像或角色对话。

#### Synthesis

这是 Investigation 内的审核区，不是独立导航或内容库。它显示当前 InvestigationSynthesisVersion、generation_method/generator_version、纳入的 verified ClaimVersions、支持/反对覆盖、Limitations 与 provenance digest。Phase 1 必须显示 `Deterministic synthesis`，不得显示 AI；Phase 3 model output 才显示 `AI synthesis` 和 model/prompt refs。Owner PM 可 `Verify`、`Revise`、`Reject`；只有一个同 Investigation 的 verified synthesis 才能启用 `Create Decision Brief`。Regenerate 仅 Phase 3。

#### Runs

显示 Run 列表与事件时间线；失败节点有 `Retry failed step`。SSE 断开时显示 reconnecting，不把 Run 标为 failed。

### 7.4 Needs input panel

位于 Detail 顶部、Timeline 当前步骤上方：

- What is needed；
- Why it blocks progress；
- 2–4 个结构化选项及成本 / 覆盖影响；
- Confirm 按钮；
- 可选 Cancel investigation。

禁止仅提供一个空白聊天框。

## 8. Decisions

### 8.1 List

默认排序：Needs action → Updated。

行内容：

- Decision Question；
- Draft / Decision-ready / Decided；
- Evidence current / stale；
- PM Judgment complete / missing；
- Watchlist、最近更新。

不显示“报告字数”“AI 生成进度”等无决策意义指标。

### 8.2 Decision Brief detail

Header：

- Decision Question；
- status；
- Brief version；
- Evidence freshness；
- `Mark Decision-ready`；`Record decision` 仅在对应 Later capability 激活后出现，Phase 1 不渲染；
- `Export` menu。

正文固定节：

1. Decision Question；
2. What Changed；
3. Evidence Summary；
4. Counter-evidence and Limitations；
5. Product Implications；
6. Recommendation Options；
7. Decision & Next Checkpoint。

每个块显示来源标签与 provenance。交互：

| 块类型 | 可用动作 |
|---|---|
| Fact | Open sources、Open claim、Flag correction |
| Synthesis | Accept、Edit、View provenance；`Regenerate` 仅 Phase 3 model origin 激活后出现 |
| PM Judgment | Write / Edit、Confirm |
| Recommendation | Accept、Modify、Reject、Add risk |

Synthesis 经 PM 编辑后保留原 generation_method：deterministic 显示 `Deterministic synthesis · edited by {name}`，model 显示 `AI-assisted · edited by {name}`。Recommendation 被接受后仍保留 Recommendation 类型；只有 PM 在 Decision 字段记录，才是 Decision。

以上编辑动作仅对当前 Draft 生效。Decision-ready/Decided version 只读；用户选择编辑时先确认 `Start revision`，服务器以 exact base version 和一个 verified synthesis 创建新的 Draft，旧 readiness/freshness/export 记录保持不变。

### 8.3 Sources drawer

- 从引用或 `Sources` 打开；
- 320–400 px，存在于 Detail 内，不新建全局第四栏；
- 列出当前块关联 Claims / Evidence；
- 点击来源打开 Source Viewer；
- `<1350 px` 作为 overlay drawer。

### 8.4 Decision-ready check

点击主操作后显示 checklist：

- Question confirmed；
- Verified facts with sources；
- Counter-evidence or documented search limitation；
- Limitations present；
- PM Judgment authored；
- Recommendation status resolved；
- Citations valid。

未通过项直接链接到对应块。禁止只禁用按钮而不解释。

### 8.5 PRD Research Input Preview

从 Export menu 打开独立 preview sheet：

- 顶部显示 `From Decision Brief v{n}`、状态、更新时间；
- 左侧为导出内容，右侧为允许包含的 section toggles；
- 不允许在 Preview 中直接编辑；
- Preview / Export 仅对 readiness-reviewed exact version 启用；Unverified 内容会阻塞 readiness，不提供绕过；
- selection toggles 只允许 Facts、confirmed PM Judgment、accepted Recommendation 与 citations；Synthesis、内部 Run/token 信息永不进入 PRD Research Input；
- latest freshness 为 `evidence_stale` 时 Preview / Export 阻塞，并提供 Review update / Start revision；
- 主操作 `Copy Markdown`；次操作 `Export .md`；
- 成功后 toast 包含版本，不出现“Publish”措辞。

## 9. Monitoring

### 9.1 页面结构

Detail 顶部使用 tabs：`Watchlists | Sources`。切换 tab 保留各自选中对象和筛选。

### 9.2 Watchlist detail

字段分区：

1. Goal & Decision questions；
2. Entities & aliases；
3. Topics；
4. Include / exclude；
5. Sources；
6. Detection window & baseline；
7. Minimum sample / cooldown；
8. Runtime & latest collection。

MVP 使用结构化表单，不提供“用自然语言创建”入口。Phase 1 只渲染 Imported；Phase 2 起 Cloud / Imported 明确显示：

- `Cloud monitoring · continues when this Mac is off`
- `Imported dataset · snapshot from {time}`

若未来实现 Local Source，需显示只在客户端运行时采集；MVP 不展示未实现的 Local connector 选项。

### 9.3 Source list

Phase 1 列表只包含 Imported Dataset 及其 ImportSession/finalize health；Cloud health、Authentication required、Disable/Reconnect 从 Phase 2 connector 激活后出现。

列：

- Name / type；
- Health：Healthy / Degraded / Authentication required / Disabled；
- Runtime：Cloud / Imported；
- Freshness；
- Last successful run；
- Items；
- actionable error。

Phase 1 导入向导必须按同一合同展示以下步骤，不得把 draft session 称为 manifest：

1. `Parsed locally`：只展示文件名、大小、parser/schema、选定列/行和 local manifest digest；Mac 路径与文件正文不进入 API。
2. `Review upload scope`：明确目标 Workspace、scope、对象大小上限、有效期，以及 `Model egress: Not authorized`；确认后追加 TransferConsentRecord。
3. `Uploading` / `Verifying upload`：Uploading 是 client transport substate（服务端仍为 consented）；服务端重新解析 effective consent，并校验 exact object key、大小、media type 与 digest。
4. `Finalizing`：验证 schema 并原子创建内容与 terminal ImportManifest；成功显示 snapshot 时间、item count 和 manifest ID。
5. `Failed`：显示可重试性。只有相同 digest/scope/有效 consent 的 retryable failure 可重试 finalize；其他情况使用 `Start new import`。`Cancel import` 对未完成 session 可用且不产生 manifest。

Source/Watchlist 选择的是具有 terminal current_import_manifest_id 的 Imported Dataset SourceConnection；ResearchRun scope 在启动时冻结该具体 manifest ID。draft、consented、uploaded、validating、failed、cancelled session 均不得显示成可研究数据源。非 retryable failure 的 `Start new import` 先明确确认并 cancel 旧 session，再创建新的唯一 active session。

### 9.4 Source detail

显示：

- Scope 与权限；
- 数据是否上传；
- Last success / freshness；
- Recent runs；
- rate limit（仅来源真实提供时）；
- error category 与恢复动作；
- Disable / Reconnect。

不得用“成功率 99.9%”之类无真实数据的占位指标。

## 10. Source Viewer

首个生产切片在主窗口 Detail / overlay 打开；独立 Source Viewer 窗口属于 Later：

```text
┌──────────────────────────────────────┬─────────────────────────┐
│ Original content                     │ Evidence metadata       │
│                                      │ stance: supports        │
│ [quoted range highlighted]           │ claim: #2               │
│ surrounding context                  │ independent group: 17   │
│                                      │ content version: v3     │
│                                      │ [Valid] [Weak] [Reject] │
└──────────────────────────────────────┴─────────────────────────┘
```

要求：

- 原文与 Evidence metadata 同屏；
- 引用高亮有文字标记，支持 VoiceOver；
- ContentVersion、采集时间、发布时间、原始链接可见；
- 原始内容删除时显示快照可用性与引用状态，不伪造链接；
- 外链打开需使用系统浏览器并提示离开 Glint（可在设置中调整，Later）。

## 11. MVP 状态矩阵

状态仅覆盖已承诺能力。

### 11.1 全局

| 状态 | 表现 | 动作 |
|---|---|---|
| Loading | Shell 先出现；list / detail 使用结构骨架，避免整屏 spinner | 无 |
| Syncing | Toolbar data status；不阻塞缓存阅读 | View status |
| Offline | Persistent banner + cached timestamp；写操作 disabled 并解释 | Retry connection |
| Fatal error | 保留 Window chrome；显示错误类别和诊断 ID | Retry / Copy diagnostics |

### 11.2 Inbox

| 状态 | 核心文案 | 主动作 |
|---|---|---|
| First run | 先定义要持续回答的问题 | Set up Monitoring |
| Collecting baseline | 正在建立基线，暂不能稳定检测变化 | View Watchlist |
| Empty | 当前没有达到阈值的新 Signal | View Monitoring |
| No matches | 没有符合当前筛选的 Signal | Clear filters |
| Source degraded | 部分来源不可用，排序与 Detection 可能受影响 | Open source |
| Load error | 无法加载 Inbox；保留已缓存列表时标记 stale | Retry |

### 11.3 Investigations

| 状态 | 表现 | 动作 |
|---|---|---|
| Empty | 从值得处理的 Signal 开始 | Go to Inbox |
| Draft | Plan preview | Start run / Save draft |
| Active | 最新 Run timeline + elapsed + cost | Review / Start new run |
| Needs input | Structured blocking panel；显示 Run reason | Provide input / Start revised run |
| Reviewing | Evidence / ClaimVersion 审核进度 | Verify / Revise / Find more |
| Run partial failure | 成功结果保留、限制自动加入 | Retry failed task / Continue review |
| Run failed | Investigation 仍为 Active / Needs input；旧 Plan/events 保留 | Start new run / Edit scope |
| Run cancelled | 旧 Run 保留，不自动取消 Investigation | Start new run / Close Investigation |
| Closed insufficient | 明确缺口，禁止 Decision-ready | Reopen scope / Monitor |
| Completed | verified synthesis 与 Create Brief 前置状态 | Review synthesis / Create / Open Brief |

### 11.4 Decisions

| 状态 | 表现 | 动作 |
|---|---|---|
| Empty | 先完成一个 Investigation | Open Investigations |
| Draft incomplete | Checklist 显示缺失项 | Complete next item |
| Decision-ready | 版本与完整性通过 | Phase 1: Export；Record decision 为 Later 且未激活时不显示 |
| Decided | 决定、理由、checkpoint | View version |
| Evidence stale | exact-version freshness record，不覆盖正文；显示 update diff | Acknowledge freshness / Start revision（创建新 Draft） |
| Export error | 保留 Preview 与选项 | Retry |

### 11.5 Monitoring

| 状态 | 表现 | 动作 |
|---|---|---|
| No Watchlist | 结构化起步说明 | New Watchlist |
| Authentication required | 明确影响范围 | Phase 2 Cloud Source 激活后显示 Reconnect；Phase 1 Imported Dataset 不显示该动作 |
| Degraded | 显示错误类别、最后成功时间 | Retry / View run |
| Stale | 显示新鲜度与受影响 Signal | Run now（若真实支持） |
| CSV invalid | 行 / 字段级错误摘要 | Re-import |

不设计 Permission denied、多人冲突、Slack / Email send、PDF export、自动发布审批等未承诺状态。

## 12. 文案规则

- 用 `Why detected`，不用 `AI thinks this is important`。
- 用 `No counter-evidence found in selected sources`，不用 `No counter-evidence exists`。
- 用 `Detected: High`，不用 `Confidence 92%` 暗示事实正确率。
- 用 `Suggested impact` 与 `Confirmed by {name}` 区分建议和确认。
- 用 `Create Decision Brief`，不用 `Generate Report`。
- 用 `Copy PRD Research Input`，不用 `Publish to PRD`。
- 用明确恢复动作，如 `Reconnect GitHub`，不用 `Something went wrong`。

## 13. 键盘与菜单

### 13.1 全局

| 快捷键 | 动作 |
|---|---|
| `⌘K` | Command Palette |
| `⌘P` | Global search |
| `⌘N` | 在 Monitoring 新建 Watchlist；其他上下文无模糊默认 |
| `⌘,` | Settings |
| `⌘⇧F` | 当前列表 Filter sheet |
| `⌘Enter` | 确认当前主要操作 |
| `Esc` | 关闭 sheet / drawer / overlay detail |

### 13.2 Inbox

| 快捷键 | 动作 |
|---|---|
| `J / K` | 下一 / 上一 Signal |
| `Enter` | 打开 Detail |
| `R` | Start Investigation |
| `E` | 打开 Why detected / Evidence |
| `I` | Dismiss，仍需选择原因 |
| `U` | Mark unread |

菜单项必须根据权限、状态和网络真实可用；disabled 项提供原因，不显示 Later 项。

## 14. Accessibility

- 所有主流程可仅用键盘完成；
- Focus ring 对比度 ≥ 3:1，焦点顺序与视觉顺序一致；
- VoiceOver 对三栏、tabs、status、引用和时间线提供语义；
- 状态不只依赖颜色；
- 支持 Reduce Motion；Run 时间线不使用持续装饰动画；
- 支持系统高对比度；
- 图表提供一句文本结论和 Data table；
- 引用高亮同时有 `Evidence quote starts / ends` 的语义；
- 点击目标至少 28 × 28 px，主要按钮 32 px；
- 动态 SSE 更新使用 polite live region，Needs input 使用 assertive。

## 15. Seed 场景 UI 数据

标准 Seed 数据必须明确标记 `Seed`，覆盖真实状态：

- High Detection：权限摩擦跨 GitHub / RSS 上升；
- Medium Detection：新竞品提及增加但样本较少；
- Low / false positive：单一 GitHub Issue 被大量转载；
- Source degraded：RSS 一次采集失败；
- Investigation Needs input：是否把 CSV 中“团队用户”视作企业用户；
- Claim with counter-evidence：个人开发者认为权限控制已足够；
- Decision Draft：缺 PM Judgment；
- Decision-ready：权限预览 / 配置诊断 Brief；
- Evidence stale：新增反证等待复查。

Seed 数据不可显示为实时生产数据；Toolbar 和对象 metadata 均标注。

## 16. MVP、Later、Non-goals

### MVP UI

- Main window、三栏与响应式覆盖 Detail；
- Inbox、Investigations、Decisions、Monitoring；
- Filter sheet 与基础筛选；
- Signal 四维评分呈现；
- Research Timeline、Evidence / Claims 审核；
- Decision Brief 四类内容；
- Markdown Preview / Copy / `.md`；
- Source Viewer；
- Light / Dark / System、键盘、无障碍与只读离线状态。

### Later UI

- Saved Views、Today、Explore、Team、Evaluations；
- Contextual AI、Quick Capture、Menu Bar；
- 自定义通知与自动化；
- PDF、外部系统同步；
- 完整协作、权限和离线编辑。

### Non-goals

- Chat-first 首页、Agent 对话剧场；
- Dashboard card wall；
- 未实现模块的 Coming Soon 入口；
- 一个颜色 / 分数代表 Signal 全部含义；
- 自动把 rule/model 建议显示为 PM 决定；
- 自制品牌插画、过度渐变、紫色 AI 套壳风格。

## 17. 总控裁决（2026-07-15）

1. 默认最小窗口为 960 px；`<1000 px` 使用 overlay Detail。
2. 首个生产切片在主窗口完成 Decision Brief 与 Source Viewer；独立多窗口为 Later，设计稿可保留但不得形成未接通入口。
3. AI 可为 Business Impact / Urgency 提供 Suggested 值，但必须由 PM 明确确认；Priority 不可直接覆盖。
4. `Decided` 保留领域状态但不进入首个生产切片 UI，流程停在 Decision-ready + Markdown export。
5. Settings 只通过 Workspace menu 提供当前切片必需项，不设 Sidebar 一级入口。
