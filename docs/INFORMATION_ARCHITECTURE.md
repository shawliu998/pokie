# Glint 信息架构

> 本文定义 Phase 0 的用户语言、导航、对象归属和三栏行为。MVP 页面必须对应真实能力；Later 能力只记录，不在导航中占位。

## 1. 架构原则

1. 使用 PM 的任务语言组织产品：**Inbox / Investigations / Decisions**。
2. `Research` 是系统执行能力，`Investigation` 是用户围绕决策问题开展的工作对象。
3. `Decision Brief` 是唯一决策级对象；`PRD Research Input` 是其受控导出视图。
4. `Watchlists` 与 `Sources` 不再竞争一级导航，统一进入 **Monitoring**。
5. Chat、Reports、Explore、Evaluations 不在 MVP 一级信息架构中。
6. 三栏只承担 Navigation / List / Detail；筛选不是第四栏。

## 2. 统一术语

| UI 术语 | 领域对象 | 定义 | 不使用的替代叫法 |
|---|---|---|---|
| Inbox | Signal queue | 等待 PM 处理的可解释变化 | Signals Dashboard、Today |
| Signal | Signal | 系统检测到、但尚未等同于产品结论的变化 | Alert、Issue、Insight |
| Investigation | Investigation | 围绕一个 Decision Question 的持续调查容器 | Research（作为用户对象） |
| Research run | ResearchRun | Investigation 内一次有范围、预算和状态的系统执行 | Agent session、Thread |
| Decision | ProductDecisionBrief | 可审核、可版本化的产品决策简报 | Report、Insight 文档 |
| Monitoring | Watchlist + SourceConnection | 定义监控目标与数据覆盖 | Watchlists / Sources 两个一级入口 |
| Evidence | Evidence | 从不可变 ContentVersion 中提取、带立场和元数据的证据 | AI 引用摘要 |
| Claim | Claim | 可被 Evidence 支持或反对的最小结论 | Fact（未经验证时） |
| PRD Research Input | Export view | 绑定 Brief 版本的受控导出 | 独立 Report |

`Insight` 仅作为用户研究语义；工程层统一为 `InvestigationSynthesisVersion`，在 Brief 中呈现为 origin-labelled Synthesis：Phase 1 deterministic，Phase 3 model output 才显示 AI。它不作为导航标签、独立 owner 或内容库。

## 3. MVP 页面地图

```text
Workspace
├─ Work
│  ├─ Inbox
│  │  ├─ Signal list
│  │  └─ Signal detail
│  ├─ Investigations
│  │  ├─ Investigation list
│  │  └─ Investigation detail
│  │     ├─ Overview
│  │     ├─ Evidence
│  │     ├─ Claims
│  │     ├─ Synthesis
│  │     └─ Runs
│  └─ Decisions
│     ├─ Decision Brief list
│     └─ Decision Brief detail
│        ├─ Brief
│        ├─ Sources
│        └─ Version history
└─ Manage
   └─ Monitoring
      ├─ Watchlists
      │  ├─ Watchlist list
      │  └─ Watchlist detail
      └─ Sources
         ├─ Source list
         └─ Source detail
```

### 3.1 不进入 MVP 导航的能力

| 能力 | 处理方式 | 原因 |
|---|---|---|
| PRD Research Input | 从 Decision Brief 的 Export 动作打开受控 Preview | 不是独立对象 |
| Research Runs | Investigation 的 `Runs` 视图 | 不是 PM 的最终任务对象 |
| Evidence viewer | 从 Signal、Claim 或 Brief 引用在 Detail / overlay 打开；独立窗口 Later | 保留来源上下文 |
| Settings | Workspace 菜单中的系统入口 | 不与日常任务竞争 |
| Team / Evaluations / Audit Log | Later，不展示入口 | MVP 未承诺对应能力 |
| Today / Explore / Reports | Later，不展示入口 | 避免空壳与平行系统 |
| Contextual AI / Chat | Later，不展示固定面板 | 产品不是 Chat-first |

## 4. 导航模型

### 4.1 Sidebar

Sidebar 只包含稳定目的地：

```text
[Workspace switcher]

WORK
  Inbox                 [unreviewed count]
  Investigations        [needs input count]
  Decisions             [draft count]

MANAGE
  Monitoring            [degraded source dot]

[Sync / data freshness]
[Workspace menu]
```

Sidebar counts/status come from the workspace-scoped `GET /v1/navigation-summary` aggregate with a freshness timestamp, never from the visible cursor page. A phase-gated destination has no row, deep link, command or badge until activated.

规则：

- 徽标只显示可行动计数，如未处理、Needs input、Draft；不显示总对象数。
- Source degraded 使用状态点与文字，不仅依赖颜色。
- Workspace 菜单承载设置、主题、快捷键和退出；未实现的团队管理不出现。
- 启动默认恢复上次 Workspace 和页面；首次启动进入 Inbox onboarding。

### 4.2 URL / Route 语义

即使 Mac 客户端不暴露 URL，也应保持稳定路由语义以支持 Deep Link 和多窗口：

```text
/w/:workspaceId/inbox?signal=:signalId
/w/:workspaceId/investigations/:investigationId/:tab
/w/:workspaceId/decisions/:briefId
/w/:workspaceId/monitoring/watchlists/:watchlistId
/w/:workspaceId/monitoring/sources/:sourceId
```

列表选择写入路由，筛选与排序写入 query state；面板宽度与最近页面属于本地偏好，不写入共享对象。

## 5. 对象关系与创建入口

```text
Watchlist ──uses──> Sources
    │
    └──detects──> Signal
                     │
                     └──starts──> Investigation
                                      ├──contains──> Research Runs
                                      ├──organizes──> Evidence
                                      └──reviews──> Claims
                                                       │
                                                       └──grounds──> InvestigationSynthesisVersion
                                                                           │
                                                                           └──grounds exactly one──> Decision Brief
                                                                                                      │
                                                                                                      └──exports──> PRD Research Input
```

创建规则：

- Watchlist 从 Monitoring 创建；MVP 使用结构化表单。
- Source 从 Watchlist setup 或 Monitoring / Sources 创建。
- Investigation 默认从 Signal 创建，以继承范围和证据；从 Investigations 直接新建属于 Later。
- Decision Brief 仅从同一 Investigation 的一个 verified InvestigationSynthesisVersion 创建；Claim/Evidence 引用只能是该 synthesis provenance 的冻结子集。
- PRD Research Input 仅从指定 Brief 版本导出。

这些限制让纵向链路可追踪，也避免出现无来源的独立 Report。

## 6. 页面与三栏映射

| 目的地 | 左栏 Navigation | 中栏 List / Queue | 右栏 Detail |
|---|---|---|---|
| Inbox | 全局 Sidebar | Signal 列表 | 发生了什么、Why detected、样本、动作 |
| Investigations | 全局 Sidebar | Investigation 列表 | Overview / Evidence / Claims / Synthesis / Runs |
| Decisions | 全局 Sidebar | Brief 列表 | Brief 编辑与来源检查 |
| Monitoring / Watchlists | 全局 Sidebar | Watchlist 列表 | 规则、范围、Source 覆盖 |
| Monitoring / Sources | 全局 Sidebar | Source 列表 | 健康、新鲜度、运行与错误 |

### 6.1 宽度与适配

- Sidebar：216–232 px，默认 224 px。
- List：340–440 px，默认 380 px。
- Detail：剩余空间，建议最小 520 px。
- `1000–1350 px`：完整三栏，Detail 内次级信息折叠。
- `<1000 px`：保留 Sidebar + List；Detail 以覆盖式页面打开，`Esc` / Back 返回列表。
- `>1350 px`：Detail 可展开 Evidence drawer，但不常驻第四个 Context Agent 面板。

分栏宽度按 Workspace 记忆，Sidebar 可折叠；任何断点都不同时显示 Sidebar、Filter rail、List、Detail 四个并列栏。

## 7. 三栏与筛选冲突的处理

### 7.1 决策

筛选属于当前 List 的控制层，不是全局导航，也不是永久左栏。MVP 采用：

1. List header 显示搜索、排序和 1–3 个高频 quick filters；
2. `Filter` / `⌘⇧F` 打开覆盖在中栏之上的临时 filter sheet；
3. Apply 后 sheet 关闭，已应用条件以可移除 chips 留在 List header；
4. Clear all 始终可见；
5. 当前筛选和排序写入路由 / 恢复状态；
6. 用户自定义 Saved Views 属于 Later，不在 Sidebar 先占位置。

这保证筛选足够强，同时不把三栏工作台变成四栏，也不压缩 Detail 的证据阅读空间。

### 7.2 MVP 可用筛选

| 页面 | Quick filters | Advanced filters |
|---|---|---|
| Inbox | Status、Watchlist、Detected | Entity、Topic、Source type、Date、Priority |
| Investigations | Status、Updated | Watchlist、Has needs input、Decision state |
| Decisions | Status、Updated | Watchlist、Decision state、Has stale evidence |
| Watchlists | Status | Runtime、Source coverage |
| Sources | Health、Runtime | Source type、Authentication state |

不提供尚无可靠数据的 Sentiment、User segment 或复杂自定义查询筛选。

## 8. 各页面信息优先级

### 8.1 Inbox

**List 行**：Signal title、变化摘要、Detection Confidence、独立来源数、数据新鲜度、状态；只有 Impact/Urgency 都已确认且非 Unknown 时才显示 P0–P3，任一 Unknown 显示 `信息不足 · 未排序`。

**Detail 首屏**：

1. What changed
2. Why detected
3. Data quality / limitations
4. Business Impact 与 Urgency 的确认状态
5. Start Investigation / Keep monitoring / Dismiss

趋势、样本、去重与原始数据位于首屏下方。Signal 不直接显示 AI Recommendation。

### 8.2 Investigations

**List 行**：Decision Question、来源 Signal、状态、当前步骤、Evidence 数、Needs input / failure。

**Detail tabs**：

- Overview：目标、范围、当前步骤、预算、限制；
- Evidence：支持 / 反对 / 中性、来源与独立组；
- Claims：状态、置信依据、支持 / 反对 Evidence；
- Synthesis：同一 Investigation 内的中间综合审核；verified 后才能创建 Brief；
- Runs：结构化业务时间线；高级 Trace 折叠显示。

### 8.3 Decisions

**List 行**：Decision Question、Brief 状态、证据新鲜度、PM Judgment 状态、最近更新。

**Detail**：按 Decision Brief 固定结构编辑。每个内容块显示 `Fact`、origin-labelled `Synthesis`、`PM judgment` 或 `Recommendation` 标签；deterministic output 不得标 AI。右侧来源 drawer 只在需要核验时展开。

### 8.4 Monitoring

Monitoring 顶部使用 `Watchlists | Sources` 两个 tabs，不在 Sidebar 中重复。

- Watchlist detail：Goal、Decision questions、Entities、Topics、Include / Exclude、Sources、Baseline、Detection rules、Runtime。
- Source detail：Type、Cloud / Local / Imported、Scope、Last success、Freshness、Health、Recent runs、Actionable error。

## 9. 状态模型

### 9.1 Signal

```text
New
├─> Triaged ─> Investigating ─> Explained
├─> Monitoring
└─> Dismissed
```

- `Triaged`：Impact / Urgency 已确认或用户明确选择后续动作。
- `Investigating`：至少一个关联 Investigation 正在运行。
- `Explained`：Investigation 已产生可审核 Claims；不代表已作产品决策。

### 9.2 Investigation

```text
Draft → Active → Reviewing → Completed
          ├─> Needs input → Active / Reviewing
          └──────────────> Closed insufficient
Draft / Active / Needs input / Reviewing → Cancelled
```

`Queued / Running / Failed` 只属于 Research Run。某次 Run 失败时 Investigation 保持 Active 或 Needs input，可创建新 Run，不能覆盖旧 Run。`Closed insufficient` 是 Reviewing 的结果状态，不伪装成 Completed；用户可补充范围、继续监控或关闭。

### 9.3 Research Run

```text
Queued → Running → Completed
            ├─> Waiting for input → Running
            ├─> Failed
            └─> Cancelled
```

改变 scope、budget 或 immutable manifest 时创建新 Run / attempt；只有同一 manifest 与 checkpoint 才能 Resume。

### 9.4 Decision Brief

```text
Draft → Decision-ready → Decided
  └───────────────> Archived

任何状态都可能被标记：Evidence stale
```

- `Decision-ready`：完整性门槛通过，可进入产品评审。
- `Decided`：PM 已记录决定、理由和 Next checkpoint。
- Evidence 更新不会静默改写 Brief，只标记 stale 并允许创建新版本。

## 10. 页面状态与真实能力

只为 MVP 已承诺能力设计以下状态：

| 页面 | 状态 | 必须提供的恢复动作 |
|---|---|---|
| 全局 | Loading / offline cached read-only / fatal error | Retry、查看缓存时间 |
| Inbox | First run / empty / no matches / partial source degraded / load error | Set up Monitoring、Clear filters、Open source、Retry |
| Investigations | Empty / draft / active / needs input / reviewing / closed insufficient / completed / cancelled；Run failed 作为内嵌运行状态 | Return to Inbox、Provide input、Start new Run、Revise scope |
| Decisions | Empty / draft / incomplete / decision-ready / decided / stale evidence / export error | Open Investigation、Complete missing block、Review updates、Retry export |
| Monitoring | No Watchlist / source auth required / degraded / stale / imported CSV invalid | Create Watchlist、Reconnect、View error、Re-import |

MVP 不设计五角色差异化页面、多人 edit conflict、Slack send failure、PDF export failure或自动发布审批；但真实 workspace/RLS 仍要求通用 Authorization / Session expired 恢复页，不能把安全失败伪装成 Empty。

## 11. 全局查找与命令

- `⌘P`：搜索 Signal、Investigation、Decision、Watchlist；MVP 不搜索未索引的原始全文。
- `⌘K`：只展示当前可执行命令，不展示 Later 动作。
- `⌘N`：在 Monitoring 中新建 Watchlist；其他页面不以模糊菜单猜测对象。
- `J / K`：中栏上下移动；`Enter` 打开；`Esc` 关闭临时 sheet / drawer 或返回列表。
- `R`：在选中 Signal 上 Start Investigation；无选中或不可执行时不显示可用态。

## 12. Later IA 演进条件

只有满足明确条件才增加入口：

| 候选入口 | 增加条件 |
|---|---|
| Today | 存在跨 2 个以上项目的真实待办，且用户每周至少 3 次跨模块切换 |
| Evaluations | 有可持续数据集与至少 3 个可行动指标，不是空图表 |
| Team | 多人评论 / 指派 / 审批已真实实现 |
| Explore | 主动分析任务不能通过 Inbox filters + Investigation scope 完成 |
| Outputs / Reports | 出现 Decision Brief 之外至少 2 种被高频独立管理的交付物 |
| Contextual AI | 上下文问答在研究审核中被验证能降低时间，且不会弱化证据边界 |

## 13. MVP、Later、Non-goals 边界

### MVP IA

- Sidebar 仅显示 Inbox、Investigations、Decisions、Monitoring；
- Investigation 必须由 Signal 发起；
- Research Run、Evidence Viewer、PRD Research Input 只作为父对象内的从属视图；
- Filter sheet、当前筛选恢复和基本全局搜索；
- Settings 只通过 Workspace menu 进入。

### Later IA

- Today、Explore、Team、Evaluations、Saved Views；
- 无 Signal 的 Investigation；
- 多人协作与外部输出管理；
- Contextual AI；
- 独立 Outputs / Reports 仅在出现多个真实交付物后评估。

### Non-goals

- Chat 作为默认主页或一级导航；
- Watchlists、Sources、Reports、Insights 同时占据多个平行一级入口；
- 把 PRD Research Input 建成可独立编辑、与 Brief 分叉的对象；
- 给未实现能力设置 Coming Soon 页面；
- 用永久 Filter rail 把三栏扩成四栏。

## 14. 总控裁决（2026-07-15）

1. 工程层使用 `InvestigationSynthesisVersion` 表示 Investigation 内中间综合，不保留 `Insight` 独立导航占位。
2. MVP 不允许无 Signal 直接创建 Investigation，以保护可追溯纵向链路。
3. `Decided` 保留为领域状态，但首个生产切片 UI 只承诺 `Decision-ready` + Markdown export。
4. Saved Views 为 Later；MVP 仅恢复最后一次筛选。
5. 离线只读；Brief 离线编辑、sync queue 与冲突解决整体 Later。
