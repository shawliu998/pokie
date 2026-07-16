# Glint Phase 0 产品简报

> 状态：Phase 0 基线
>
> 首个主用户：负责竞品与用户研究的产品经理
>
> 核心对象：Product Decision Brief
> MVP 标准场景：AI Coding Agent 权限摩擦上升，判断是否将“权限预览 / 配置诊断”纳入下一季度优先级

## 1. 产品定义

Glint 是面向 5–20 人产品团队的 Intelligence Workbench。它持续监控竞品与用户信号，把可疑变化转化为有支持证据、反面证据和限制条件的 Investigation，最终帮助产品经理形成可追溯的 Product Decision Brief（下称 Decision Brief）。

5–20 人描述目标组织，不表示 MVP 同时实现多人协作。首个可运行闭环由一名 Owner PM 独立完成；workspace scope、RLS 与审计主体从第一天存在，邀请、独立 Reviewer 和五角色协作在 Later 激活。

Glint 的价值不是“收集更多内容”，也不是让用户与通用 AI 对话；它要缩短从“外部出现变化”到“团队可以作出产品判断”的距离，并保留判断依据。

MVP 的价值链为：

```text
Monitoring（Watchlist + Sources）
→ Inbox（Explainable Signal）
→ Investigation（Evidence + Claims）
→ Decision（Product Decision Brief）
→ PRD Research Input（受控导出视图）
→ Feedback
```

## 2. 要解决的问题

负责竞品与用户研究的 PM 当前需要在 GitHub、RSS、访谈或 CSV 中手工发现变化，再用表格、文档和聊天工具拼接证据。这个过程有四个结构性问题：

1. **发现晚且噪声大**：热度、转载和单一大账号常被误判成真实趋势。
2. **结论难验证**：摘要没有清楚说明样本、基线、独立来源、反证和数据限制。
3. **研究与决策脱节**：研究产物停留在资料汇总，不能直接回答一个产品决策问题。
4. **出处与作者责任混淆**：事实、AI 综合、PM 判断和建议混写，团队不知道该相信什么、由谁负责。

## 3. 用户与使用情境

### 3.1 MVP 主用户

负责竞品与用户研究的产品经理。其职责包括：

- 维护一个明确业务问题的竞品 / 用户 Watchlist；
- 每周处理新 Signal，判断忽略、继续监控或发起 Investigation；
- 审核支持与反对证据；
- 对产品影响作出自己的判断；
- 将 Decision Brief 用于季度规划、PRD 或评审。

### 3.2 协作角色

研究员、产品负责人、市场成员可在后续参与审核与复用，但不是 MVP 交互和权限设计的前提。MVP 先保证单一 PM 能完成闭环；复杂角色权限、评论与多人审批属于 Later。

### 3.3 标准场景

Watchlist `AI Coding Agents` 正在监控 Cursor、Claude Code、Codex、Windsurf、Zed 的 Permissions、Reliability、Pricing 等话题。系统从 GitHub、RSS 和用户导入的 CSV 中识别到：权限相关负面讨论在过去 7 天相较 28 天基线明显上升，且不是单一帖子或单一作者驱动。

PM 需要回答：

> 是否应将“权限执行预览 / 配置诊断”纳入下一季度产品优先级？

## 4. 产品承诺

Glint 帮助 PM 在一个工作区内完成三件事：

1. **知道为什么这个变化值得看**：Signal 清楚呈现异常依据、数据质量和限制，不用一个模糊 Severity 分数替代解释。
2. **知道结论为什么可信或不可信**：Investigation 把 Evidence、Counter-evidence、Claim 和运行过程组织在一起。
3. **知道接下来由谁作判断**：Decision Brief 明确区分事实、AI 综合、PM 判断和建议，并能以受控视图导出 PRD Research Input。

## 5. 核心对象与责任边界

| 对象 | 用户语言 | 责任 | MVP 是否独立页面 |
|---|---|---|---|
| Watchlist | Monitoring 中的监控规则 | 定义业务问题、实体、话题、来源、基线与触发规则 | 否，位于 Monitoring |
| Source | Monitoring 中的数据源 | 表示连接、运行位置、健康与新鲜度 | 否，位于 Monitoring |
| Signal | Inbox 中的待处理变化 | 解释系统检测到了什么，以及为什么入箱 | 是 |
| Investigation | 围绕决策问题的证据化调查 | 管理计划、Research Runs、Evidence、Claims 和人工复核 | 是 |
| Research Run | Investigation 内的系统执行 | 检索、去重、分析、审查；是技术执行记录，不是一级用户对象 | 否 |
| Decision Brief | Decisions 中的决策记录 | 组织事实、AI 综合、PM 判断、建议与最终决定 | 是 |
| PRD Research Input | Decision Brief 的受控导出视图 | 把选定 Brief 版本映射为 PRD 可复用段落 | 否 |

`Insight` 只保留为用户研究语义；工程 canonical object 为 `InvestigationSynthesisVersion`，表示 Investigation 内形成的中间综合。它没有独立 owner、导航或长期决策生命周期，避免与 Decision Brief 竞争。

## 6. Decision Brief 内容契约

Decision Brief 是唯一的决策级 Source of Truth。每一个内容块必须有 `content_type` 和来源信息，UI 不允许把不同责任的内容合并成同一段无标记文本。

| 内容类型 | 定义 | 可编辑性 | 必须显示 |
|---|---|---|---|
| **Fact / 事实** | 确定性统计或经人工确认、且有 Evidence 支撑的 Claim | 通过回到 Evidence / Claim 修正，Brief 内不直接改写事实 | 引用、样本、时间窗、来源版本 |
| **Synthesis / 综合** | 系统基于已验证 Claims 形成的归纳或解释 | 必须显示生成方式；Phase 1 标 `Deterministic synthesis`，仅 Phase 3 model 产出标 `AI synthesis`；人工编辑后保留 origin 并标编辑者 | generation_method、generator/run 版本；model/prompt 仅适用于模型产出；生成时间 |
| **PM Judgment / PM 判断** | PM 对业务影响、取舍或决策的负责性判断 | 仅由 PM 确认或撰写 | 作者、时间、判断状态 |
| **Recommendation / 建议** | 下一步行动选项，不等于已作决定 | 可接受、修改或拒绝 | 提议来源、预期影响、风险、状态 |

Decision Brief 固定结构：

1. Decision Question（PM 定义）
2. What Changed（Facts + 必要的 origin-labelled Synthesis）
3. Evidence Summary（支持证据、反面证据、样本与覆盖）
4. Limitations（缺失来源、时间范围、潜在偏差）
5. Product Implications（Synthesis 与 PM Judgment 分块呈现，且 Synthesis 显示 deterministic/model origin）
6. Recommendation Options（建议及其接受 / 拒绝状态）
7. Decision & Next Checkpoint（PM Judgment）

### 6.1 PRD Research Input 的受控导出

- 导出对象必须绑定一个 Decision Brief 版本，不能成为独立可编辑文档。
- MVP 提供 `Preview → Copy Markdown / Export .md`；PDF、同步至外部 PRD 工具属于 Later。
- 导出只包含被 PM 选中的 Facts、已确认的 PM Judgment、已接受的 Recommendation 与引用列表。
- 只有通过 exact-version readiness review 的 DecisionBriefVersion 可 Preview / Export；Draft、未审核 Claim 与未验证 synthesis 不提供强制绕过。
- Decision-ready version 只读；任何编辑通过显式 Start revision 创建新的 Draft version，旧 readiness/freshness/export 记录不变。
- 新 Evidence 只追加 exact-version freshness record；`evidence_stale` 阻塞 Preview/Export，直到 PM recheck 或基于 verified synthesis 建立新版本。重新导出永远创建新的 terminal record。

## 7. Signal 评分产品规则

MVP 不向用户显示单一 `Severity 82`。Signal 使用四个含义不同的维度：

| 维度 | 回答的问题 | 生成方式 | Inbox 呈现 |
|---|---|---|---|
| Detection Confidence | 系统是否真的检测到异常？ | 由样本量、相对基线变化、独立来源、跨来源确认、数据健康等确定性输入计算 | High / Medium / Low + 触发原因 |
| Business Impact | 若属实，对产品或业务影响多大？ | 系统可按规则建议；Phase 3 才可由 policy-approved model 建议；PM 必须确认 | 未评估 / H / M / L / Unknown，并标记 suggestion origin 或已确认 |
| Urgency | 需要多快处理？ | 规则可建议，PM 必须确认 | 未评估 / Now / This week / Monitor / Unknown |
| Priority | 团队应先处理什么？ | 仅在 Impact 与 Urgency 都已确认且都不是 Unknown 时按规则派生 | P0–P3；未确认显示“待分级”，任一 Unknown 显示“信息不足 · 未排序” |

原则：

- Detection Confidence 不是事实正确率，也不是 Business Impact。
- 内部连续分数用于排序和校准；主界面只显示分档、原因和数据质量，详细数值放入“Why detected”。
- 新 Signal 默认按 `未处理 → Detection Confidence → 新鲜度` 排序，不能因未经确认的 AI Business Impact 直接升为最高优先级。
- 手动确认或覆盖 Impact / Urgency 必须记录作者、时间和原值。
- `Unknown` 是有效的人类确认结果，但不是可进入 Priority 矩阵的等级；它让 Signal 保持可 triage、Priority 为 null/status=insufficient_input，直到 PM 新建可排序的 assessment revision。

## 8. MVP 黄金路径

```text
打开 Inbox
→ 选择“权限摩擦上升”Signal
→ 查看 Why detected、样本与限制
→ 确认业务问题并 Start Investigation
→ 检查结构化计划、范围与预算
→ 观察运行时间线并处理 Needs input
→ 审核支持 / 反对 Evidence 与 Claims
→ 审核并验证一个 InvestigationSynthesisVersion
→ 生成 Decision Brief Draft
→ PM 填写 Product Implications / Decision
→ 接受、修改或拒绝 Recommendations
→ 标记 Decision-ready
→ Preview 并复制 PRD Research Input
```

详细交互与异常分支见 [USER_FLOWS.md](./USER_FLOWS.md)。

## 9. 激活与价值时刻

### 首次激活时刻

用户完成以下事件才算激活，而不是仅完成注册或连接数据源：

> PM 打开一个 Explainable Signal，查看 Why detected 后，以一个明确 Decision Question 发起首个 Investigation。

事件定义：`investigation_started_from_signal`，且必须包含 `decision_question`、`signal_id` 和已确认的范围。

### 付费价值时刻

> PM 将一个包含可追溯 Facts、Counter-evidence / Limitations 和至少一条 PM Judgment 的 Brief 标记为 Decision-ready，完成受控 Preview，并实际复制 Markdown 或导出 `.md`。

事件定义：`prd_research_input_exported`；只有满足 Brief 完整性门槛才计入。该时刻代表系统结果进入真实产品决策流程，而不只是生成了一份 AI 文本。

## 10. 范围

### 10.1 MVP：必须真实可用

这里的 MVP 是 Phase 1–3 分阶段完成的产品范围，不表示 Phase 1 同时交付全部条目。Phase 1 只上线 Seed/Imported CSV 的真实最薄闭环；Phase 2 激活 GitHub/RSS；Phase 3 才替换为 LangGraph model-assisted ResearchRun。任何阶段只显示已接通入口。

- Mac 桌面主壳：Workspace、Sidebar、三栏、窗口状态、Dark / Light、键盘导航。
- Inbox：Signal 列表、解释性详情、基础筛选、忽略 / 继续监控 / 发起 Investigation。
- Monitoring：Phase 1 为结构化 Watchlist 与 Seed/Imported CSV import health；Phase 2 增加 GitHub/RSS 状态、范围、新鲜度和健康。
- Investigation：Phase 1 为 deterministic ResearchRun 的计划/时间线、Evidence/Counter-evidence、Claim 与 synthesis 审核；Phase 3 激活 model-assisted proposal/Regenerate。
- Decisions：Decision Brief 创建、四类内容来源、人工判断、版本、Decision-ready 状态。
- PRD Research Input：受控 Preview、复制 Markdown、导出 `.md`。
- 最近对象的只读缓存；离线时明确显示数据时间，不承诺完整离线编辑与同步。
- 标准场景的 Seed / Test Corpus 必须显式标记为非生产；Imported/collected data 分别展示真实性与新鲜度，不互相冒充。

### 10.2 Later：有价值但不进入 MVP 页面承诺

- 用户自定义 Saved Views、Today 跨项目聚合、Explore / BI。
- 多人评论、@、复杂指派、审批流、完整 Owner / Admin / Analyst / Contributor / Viewer 权限。
- Reddit、X、小红书、通用网页、Cookie 型本地连接器。
- PDF、Google Docs / Notion / Jira 等外部发布与双向同步。
- 高级 Evaluations、Prompt 管理、团队 Audit Log UI。
- Contextual AI、自然语言建 Watchlist、Quick Capture、Menu Bar 快捷操作。
- 自动通知策略、Slack / Email 分发、多语言与复杂离线同步。

### 10.3 Non-goals：当前产品不做

- 通用聊天机器人或 Chat-first 首页。
- 自动替 PM 作产品决策，或把 AI Recommendation 当作已批准决定。
- 无证据的内容生成、自动对外发布、营销 Campaign 管理。
- 传统 Dashboard Card Wall、全量舆情 BI、社交媒体运营套件。
- 以 Agent 数量为卖点的多 Agent 剧场。
- 在没有真实后端能力时展示 Coming Soon 导航或可点击假入口。

## 11. 成功指标

以下为 Phase 0 产品验证的 provisional targets，必须连同样本量、分母、数据集/原型版本和日期报告；它们不是生产 SLO 或已校准质量保证，首轮 Pilot 后需重估。

| 指标 | Phase 0 provisional target | 说明 |
|---|---:|---|
| Top Signal usefulness | 每个 Watchlist 每周前 5 个中 ≥ 60% 被 PM 选择 Investigate 或 Keep monitoring | 衡量信号价值而非数量 |
| Why detected 理解率 | ≥ 80% 测试用户能在 2 分钟内复述触发原因与主要限制 | 防止黑盒分数 |
| Investigation 完成率 | ≥ 70% 已开始 Investigation 形成可审核 Claims | 排除纯试点运行 |
| Citation correctness | 抽检 ≥ 95% 引用确实支持对应 Fact / Claim | 信任底线 |
| Brief decision-ready rate | ≥ 50% 已完成 Investigation 形成 Decision-ready Brief | 核心漏斗 |
| PRD Input reuse | ≥ 40% Decision-ready Brief 完成 Preview 后被复制或导出 | 付费价值代理指标 |
| Active research time | 相对当前手工流程中位数下降 ≥ 50% | 不用运行等待时间替代人工时间 |

## 12. 产品原则

1. Inbox-first，Chat 只可能是后续上下文操作，不是导航中心。
2. 解释先于分数；结论先于 Agent 运行细节。
3. Evidence 必须可回到不可变来源版本；Claim 必须说明支持、反对与限制。
4. Facts、Synthesis、PM Judgment、Recommendation 不能混写；Synthesis 必须展示 deterministic/model/human-edited origin。
5. 产品页面只展示已承诺能力；Later 不以空入口占位。
6. 全产品架构可扩展，但生产实现只围绕一条真实纵向闭环。
7. 确定性计算交给代码；LLM 负责有边界的综合、解释和建议。
8. 高风险写入与外部发送必须由人确认。

## 13. 关键假设

- PM 每周确有稳定的竞品 / 用户研究任务，而不是临时性一次调研。
- GitHub、RSS、CSV 足以为首个场景产生有区分度的支持与反对证据。
- PM 愿意先处理 Explainable Signal，再发起研究，而不是直接输入任意问题。
- 业务影响与产品优先级必须由 PM 确认，这一额外步骤不会使流程过重。
- Decision Brief 比“独立 Insight 库 + Report Center”更接近真实决策载体。
- 受控 Markdown 导出足以验证 PRD 复用，不需要 MVP 即完成外部系统集成。

验证方法与阈值见 [PRODUCT_VALIDATION_PLAN.md](./PRODUCT_VALIDATION_PLAN.md)。

## 14. 总控裁决（2026-07-15）

1. **产品名**：正式使用 Glint；`Signal Intelligence` 仅视为旧工作名。
2. **MVP 权限边界**：单一 Owner PM 可完成闭环；真实 workspace/RLS/AuditLog 前移，五角色与独立 Reviewer UI 在 Phase 4。
3. **Decision-ready 与已决策分离**：`Decision-ready` 表示材料可进入评审；`Decided` 为单独领域状态，但首个生产切片 UI 停在 Decision-ready + Markdown export。
4. **Signal 分档**：High / Medium / Low 是 heuristic bands；Evaluation owner 在版本化样本上校准前，不展示为概率。
5. **导出格式**：首个切片只承诺 Preview、Copy Markdown 与 `.md`；PDF 和外部 PRD 集成 Later。
6. **离线底线**：MVP 仅承诺最近数据只读缓存；不提供离线领域写入、Brief 编辑或 sync queue。
7. **Investigation 映射**：新增明确 aggregate，拥有 Decision Question、scope、状态和多个 ResearchRuns；Run 只是执行记录。
8. **决策对象收敛**：Decision Brief 是唯一决策级 aggregate；InvestigationSynthesisVersion 是中间综合；PRD Research Input 是绑定一个 DecisionBriefVersion 的 Preview / immutable BriefExport。
