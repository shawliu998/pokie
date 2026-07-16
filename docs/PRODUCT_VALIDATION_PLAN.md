# Glint Phase 0 产品验证计划

> 目标：在扩大来源、协作和输出能力前，验证一条真实闭环是否能让负责竞品与用户研究的 PM 更快、更可信地完成产品判断。验证对象不是“用户喜不喜欢 AI”，而是 Signal → Investigation → Decision Brief → PRD Research Input 是否进入真实工作。

除明确的安全不变量外，本文数字均为 Phase 0 产品假设与实验决策线，不是已校准概率、生产 SLO 或质量保证。每次实验必须记录样本量、分母、数据集/原型版本、owner 与日期；同一指标使用一个通过线，并另设更宽松的 Stop / Pivot 线。首轮样本后必须重新校准。

## 1. 验证决策

Phase 0 / MVP 需要回答六个决策问题：

1. 主用户是否每周反复执行竞品与用户研究，而非偶发性一次任务？
2. Explainable Signal 能否比原始内容流更快地帮助 PM 找到值得研究的变化？
3. GitHub、RSS、CSV 的组合能否在首个权限摩擦场景中形成足够的支持与反对 Evidence？
4. 用户能否正确理解 Detection Confidence、Business Impact、Urgency、Priority 的区别？
5. 四类内容边界能否让团队分清 Fact、origin-labelled Synthesis、PM Judgment 与 Recommendation，并识别 deterministic 与 model 来源？
6. Decision Brief 的受控 PRD Research Input 是否真的被带入 PRD / 季度评审，并形成付费意愿？

## 2. 关键假设与优先级

评分：

- Risk：错误时对产品方向的破坏程度，1–5；
- Uncertainty：当前证据缺失程度，1–5；
- Priority = Risk × Uncertainty。

| ID | 假设 | Risk | Uncertainty | Priority |
|---|---|---:|---:|---:|
| H1 | PM 的主要痛点是验证、反证与决策重组，而不只是信息发现 | 5 | 5 | 25 |
| H2 | Signal-first 比直接 Chat / 搜索更适合持续研究入口 | 5 | 4 | 20 |
| H3 | GitHub + RSS + CSV 足以支持首个高价值场景 | 5 | 4 | 20 |
| H4 | 用户能理解四维 Signal 呈现，并愿意确认 Impact / Urgency | 4 | 5 | 20 |
| H5 | Decision Brief 是团队接受的唯一决策对象，PRD Input 只需导出 | 5 | 4 | 20 |
| H6 | 四类内容来源标签提升信任，且不会显著增加编辑负担 | 4 | 4 | 16 |
| H7 | PM 愿意审核 Evidence / Claims，而不是只读最终摘要 | 5 | 3 | 15 |
| H8 | Markdown Preview / Copy 足以进入现有 PRD 工作流 | 4 | 3 | 12 |
| H9 | 新 Evidence 的 stale 提醒是复购价值，而不是低频附属能力 | 3 | 5 | 15 |
| H10 | 团队愿意为“更可信地作决策”而非“更多监控来源”付费 | 5 | 5 | 25 |

优先验证 H1、H2、H3、H4、H5、H10；H9 可在真实 Pilot 中观察。

## 3. 目标样本

### 3.1 招募标准

必须满足：

- 当前角色为 PM、Senior PM、Product Lead，或研究职责占比高的 Product Ops；
- 每月至少进行 2 次竞品 / 用户反馈研究；
- 过去 3 个月至少一次把研究内容带入 PRD、路线图或季度评审；
- 当前使用至少两类来源，例如 GitHub / 社区、RSS / newsletter、访谈 / 工单、表格；
- 所在团队 5–20 人优先；允许少量相邻规模作对照。

排除：

- 主要目标是社交媒体投放或品牌声量 Dashboard；
- 只需要一次性市场报告；
- 没有产品优先级或 PRD 输入责任；
- 只评价 UI、但不愿提供真实工作样本。

### 3.2 样本结构

| 阶段 | 人数 | 结构 |
|---|---:|---|
| Problem interviews | 8–10 | 6 名主画像 PM；2–4 名 Product Lead / 研究协作者 |
| Concept / prototype test | 6 | 4 名主画像；2 名决策评审者 |
| Concierge vertical slice | 4–6 | 提供真实或脱敏数据的主画像 PM |
| Paid pilot | 3 个团队 | 每队 1 名主 PM + 1 名决策相关方 |

样本达到人数不自动代表饱和；连续 3 次访谈不再出现新的核心 Job / objection 才视为问题探索初步饱和。

## 4. 研究材料

### 4.1 标准场景数据包

主题：AI Coding Agent 权限摩擦是否上升，是否把权限预览 / 配置诊断纳入下一季度优先级。

数据包至少包含：

- GitHub issue / discussion；
- RSS / changelog / 技术文章；
- 脱敏 CSV 访谈或支持记录；
- 精确重复、近似转载、单一作者热点；
- 支持 Claim 的 Evidence；
- 反对 Evidence；
- 一个错误引用或超出证据范围的弱 Claim；
- 一个 Degraded Source；
- 一个 `No counter-evidence found` 但覆盖有限的分支；
- 明确的时间窗与 Seed 标签。

数据包需要由研究负责人手工建立 ground truth：

- duplicate group；
- independent source group；
- Evidence stance；
- citation support / not support；
- Claim supported / overstated / unsupported；
- source and time coverage。

### 4.2 真实工作材料

招募时请参与者带来：

- 最近一次竞品 / 用户研究的原始来源；
- 中间表格 / 文档；
- 最终 PRD 或评审输入（可脱敏）；
- 实际花费时间和协作步骤；
- 在评审中被追问的问题。

禁止要求参与者上传未授权的客户数据。CSV 只使用脱敏样本，并在测试前明确处理与删除方式。

## 5. 分阶段验证

### 5.1 Stage A：问题与现状验证

#### Stage A 方法

60 分钟半结构访谈 + artifact walkthrough。不要先展示 Glint。

#### Stage A 任务

1. 让参与者回放最近一次从“发现变化”到“产品决定”的全过程。
2. 标记触发点、使用来源、复制粘贴、验证、反证、评审和最终输出。
3. 计算主动研究时间，不把等待同事或模型运行混入。
4. 询问一次结论被质疑、推翻或过期的具体案例。
5. 最后才展示 1 页概念，记录吸引点与焦虑。

#### Stage A 通过信号

- ≥ 7/10 参与者每月至少两次重复执行该 Job；
- ≥ 6/10 的最高摩擦包含“验证 / 去重 / 反证 / 重组”至少一项；
- ≥ 5/10 曾因来源、样本或责任不清在评审中返工；
- 至少 4 人主动展示现有 Decision / PRD artifact，而非只表达兴趣。

#### Stage A 否决 / 转向

- 若主要痛点只是“没有足够来源”，应先验证 connector / collection 产品，不进入完整 Brief 编辑器。
- 若研究明显是季度性一次任务，持续 Monitoring 不应作为默认入口。
- 若最终产物不是 PRD / 决策记录，而是市场内容，应重新评估主用户。

### 5.2 Stage B：信息架构与术语验证

#### Stage B 方法

Tree test + first-click test + 低保真三栏原型；6 人，45 分钟。

#### Stage B 核心任务

1. “发现一个新变化，先去哪里处理？”期望 Inbox。
2. “查看正在等待你补充范围的研究”期望 Investigations。
3. “找上次是否进入季度优先级的结论”期望 Decisions。
4. “修改 AI Coding Agents 监控范围和 GitHub 来源”期望 Monitoring。
5. “把结论放进 PRD”期望从 Decision Brief Export，而非寻找 Reports。

#### Stage B 命名对照

随机或组间比较：

- Investigations vs Research；
- Decisions vs Insights；
- Monitoring vs Watchlists / Sources 两个入口；
- Product Decision Brief vs PRD Research Input。

#### Stage B 通过阈值

- 一级任务首次点击正确率 ≥ 80%；
- ≥ 5/6 能解释 Investigation 是工作容器、Research Run 是系统执行；
- ≥ 5/6 能指出 PRD Research Input 不是独立可编辑对象；
- 完成 Monitoring 任务不超过 2 次错误导航。

#### Stage B 决策规则

- 若 `Decisions` 被误解为只存最终 Yes / No，可在列表副标题写 `Decision Briefs`，不恢复 `Insights` 一级导航。
- 只有当 ≥ 4/6 主用户明确把“Research”作为日常容器术语，且 Investigations 造成持续误解时，才考虑 UI 采用 `Research`；后端仍保留 Research Run 区分。

### 5.3 Stage C：Signal 解释与排序验证

#### Stage C 方法

使用 8–10 个 Seed Signal 的排序任务；包含真阳性、假阳性、single-author spike、source degraded。

#### Stage C 任务

1. 让用户选出前 3 个应处理 Signal，并口述理由。
2. 查看权限摩擦 Signal，复述发生了什么、为何入箱、最重要限制。
3. 解释 Detection Confidence 与 Business Impact 的区别。
4. 接受或修改 Suggested Impact / Urgency，观察是否理解 Priority 来源。
5. 处理单一热帖假阳性。

#### Stage C 指标与阈值

| 指标 | 通过阈值 |
|---|---:|
| Why detected 理解 | ≥ 5/6 在 2 分钟内正确复述触发原因和至少 1 个限制 |
| 四维区分 | ≥ 5/6 正确解释 Detection / Impact / Urgency / Priority |
| 假阳性识别 | ≥ 5/6 Dismiss single-author spike，且选择合理原因 |
| Triage 时长 | 中位数 ≤ 90 秒 / Signal |
| 未确认建议误用 | 0 人把 Suggested Impact 当作 PM 已确认 |

#### Stage C 设计失败信号

- 用户只看彩色标签而不读原因；
- 将 High Detection 解读成“这一定是真实用户问题”；
- 在 Impact / Urgency 未确认时期待 P0；
- 筛选 sheet 被误解成第四个长期导航栏。

若失败，先改文案、层级和交互，再调整算法分数。

### 5.4 Stage D：Evidence、Claim 与 Brief 可用性

#### Stage D 方法

Moderated task test；使用包含故意弱引用和反证的数据包。6 人，60–75 分钟。

#### Stage D 任务

1. 从 Investigation Timeline 找到当前进度和一个失败来源。
2. 处理 Needs input：是否扩大 CSV 范围。
3. 审核一个 Claim，找到支持与反对 Evidence。
4. 打开原文版本，判断引用是否支撑 Claim。
5. 拒绝故意植入的弱 Evidence 或过度 Claim。
6. 在 Synthesis tab 审核纳入的 verified Claims、反证与限制；先尝试在未 verified 时创建 Brief，确认入口被阻止，再 Verify / Revise / Reject exact synthesis version。
7. 仅从 verified InvestigationSynthesisVersion 创建 Decision Brief，区分四类内容并确认 direct references 没有绕过该 provenance。
8. 写一条 PM Judgment，处理两个 Recommendations。
9. 完成 Decision-ready checklist。
10. Preview 并 Copy PRD Research Input。

#### Stage D 通过阈值

| 指标 | 通过阈值 |
|---|---:|
| 找到支持与反对 Evidence | ≥ 5/6，无主持人提示 |
| 弱引用识别 | ≥ 5/6 正确识别 |
| Synthesis prerequisite | 6/6 无法从未 verified synthesis 创建 Brief；≥ 5/6 能解释阻止原因并完成正确审核 |
| 四类内容识别 | 每人 8 个块中 ≥ 7 个正确分类 |
| Recommendation / Decision 混淆 | 0 人把 Proposed Recommendation 当已决定 |
| Decision-ready 完成 | ≥ 5/6 在 15 分钟内完成 |
| PRD 导出理解 | ≥ 5/6 知道 Preview 不可独立编辑且绑定 Brief version |
| 引用可追溯 | 100% 任务引用能回到 Source Viewer 或明确不可用状态 |

#### Stage D 信任质性信号

参与者应能用自己的话回答：

- “这段是事实还是系统综合？”
- “谁为这一判断负责？”
- “系统没有找到反证，是否等于没有反证？”
- “如果新 Evidence 出现，旧 PRD 内容会不会被静默改掉？”

### 5.5 Stage E：Concierge 真实纵向闭环

#### Stage E 方法

4–6 名 PM，各自选择一个真实但可脱敏的竞品 / 用户主题。团队可在后台人工辅助采集、去重和 Evidence 标注，但前台对象与流程必须遵循产品契约。不得把人工服务冒充自动化能力；研究记录标记 `Concierge-assisted`。

#### Stage E 周期

每位参与者 1 个 Watchlist，运行 2 周：

- Week 0：导入历史材料、建立现状基线；
- Week 1：处理 Inbox、发起至少 1 个 Investigation；
- Week 2：完成 Brief、导出 PRD Input、回访。

#### Stage E 核心指标

下列目标适用于首轮 4–6 人 Concierge 样本，由 Product Research owner 记录，Evaluation owner 复核数据定义；完成首轮后按真实分布校准。

| 漏斗 | 定义 | Phase 0 provisional target |
|---|---|---:|
| Signal usefulness | 前 5 Signal 中被 Investigate 或 Keep monitoring | ≥ 60% |
| Activation | 看 Why detected 后从 Signal 发起 Investigation | ≥ 70% 的已 onboard 用户 |
| Investigation completion | Started → 可审核 Claims | ≥ 70% |
| Brief readiness | Completed investigation → Decision-ready | ≥ 50% |
| Paid value | Decision-ready → PRD preview / export | ≥ 40% |
| Active time reduction | 对比同类历史任务 | 中位数下降 ≥ 50% |
| Citation correctness | 人工抽检 | ≥ 95% |
| Unsupported Claim rate | 人工抽检 | ≤ 5% |

#### Stage E 质性完成标准

- 至少 3/4 完成闭环的 PM 将导出内容放入真实 PRD / 评审材料；
- 至少 3 人表示如果停用，会回到明显更费时或更不可信的流程；
- 至少 2 个 Brief 产生明确的“进入 / 不进入 / 继续监控”产品取舍，而非纯摘要。

### 5.6 Stage F：付费 Pilot

#### Stage F 前提

只有 Stage E 达到 Citation、Brief readiness 与真实复用底线后进入。不要在可信度未过线时用更多来源包装销售。

#### Stage F Offer

以一个真实 Watchlist、GitHub / RSS / CSV、每周可用 Signal、1–2 个 Investigation 和 Decision Brief 为范围的 4 周付费 Pilot。价格由商业负责人设定，验证应使用真实付款、采购意向书或可执行预算承诺，不以“愿意尝试”替代。

#### Stage F 通过阈值

- 3 个符合画像团队中至少 2 个接受付费 Pilot 或给出有时限的采购承诺；
- 付费理由至少一半指向决策可信度、节省验证时间或 PRD 复用，而非“来源多”；
- 至少 1 名非操作者的决策相关方确认 Brief 提升评审效率；
- 不要求 MVP 先增加与核心闭环无关的社交平台或 Dashboard 才愿付费。

## 6. 激活与付费价值测量

### 6.1 首次激活事件

事件：`investigation_started_from_signal`

必须满足：

- 由 Inbox Signal 发起；
- 用户已打开 Why detected；
- Decision Question 非空且由用户确认；
- scope、source、time window 已确认；
- Research Run 实际进入 Queued / Running。

不计入激活：

- 创建 Workspace；
- 创建 Watchlist；
- 连接 Source；
- 打开 Seed Brief；
- 从系统自动生成一个 Investigation draft 但未运行。

### 6.2 付费价值事件

事件：`prd_research_input_exported`

必须满足：

- Brief 状态 Decision-ready 或 Decided；
- 至少一条有引用的 Fact；
- Counter-evidence 或 documented limitation；
- 至少一条 PM Judgment；
- Recommendation 状态已处理；
- 用户实际 Preview 后执行 Copy Markdown / Export `.md`；
- 记录 Brief version。

防作弊：重复复制同一版本只计一次；Seed Brief 不计真实价值漏斗。

## 7. 指标定义与数据质量

### 7.1 关键指标

```text
Top Signal usefulness
= top 5 signals with Investigate or Keep monitoring
  / all reviewed top 5 signals

Investigation completion rate
= investigations reaching human-reviewable claims
  / investigations actually started

Brief decision-ready rate
= decision-ready briefs
  / completed investigations eligible for a brief

PRD Input reuse rate
= unique brief versions previewed and exported
  / decision-ready brief versions
```

### 7.2 质量护栏

- Citation correctness：引用内容是否支持对应 Fact / Claim；
- Unsupported Claim rate：没有足够 Evidence 或超出 Evidence 范围的 Claim；
- Counter-evidence coverage：评测集中的已知反证是否被检索并呈现；
- Duplicate leakage：重复 / 转载被算作多个独立 Evidence 的比例；
- Source health transparency：Source degraded 时 Signal 是否明确降级；
- Human override rate：PM 修改 Suggested Impact / Urgency 的比例及原因；
- Recommendation acceptance / modification / rejection：判断建议质量，但不把高接受率单独当成功。

### 7.3 埋点 QA

- Seed、Concierge、Production 数据必须有 environment / dataset 标记；
- 事件必须包含 object ID、version、timestamp、workspace；
- 不能记录私有正文、Cookie、Token 或原始 CSV 内容；
- 服务端状态与前端事件按 version / idempotency key 去重；
- 定期对照 Audit / domain event，避免前端点击等同业务完成。

## 8. 实验记录模板

每轮研究应记录：

```text
Experiment ID:
Date / owner:
Hypotheses:
Participant criteria:
Artifact / dataset version:
Tasks:
Behavioral observations:
Time-on-task:
Errors / assists:
Quotes (consented, de-identified):
Metric results:
Decision: Pass / Iterate / Stop
Product changes:
Open risks:
```

所有失败均记录为设计或产品假设证据，不用“用户不会用”归因。

## 9. Go / Iterate / Stop 门槛

### Provisional Go：进入真实纵向实现

同时满足：

- H1 问题证据通过；
- IA 首次点击 ≥ 80%；
- Signal 四维理解 ≥ 5/6；
- Citation correctness ≥ 95%（首轮产品验证通过线，不是生产质量保证）；
- Decision Brief 四类内容识别 ≥ 5/6 达标；
- 至少 3 个真实工作样本愿意进入 Concierge。

### Go：扩大来源或协作

只有核心 Pilot 达标后，且扩展请求能明确改善以下之一：

- Top Signal usefulness；
- Counter-evidence coverage；
- Brief reuse；
- 多人评审完成时间。

“看起来产品更完整”不是扩展依据。

### Iterate

- 用户认可问题，但无法理解评分或对象命名；
- Evidence 有价值，但审核负担超过现有工作；
- PRD 导出有价值，但 Brief 结构不匹配评审语言；
- Signal precision 合格，但 recall 不足。

先调整信息层级、默认值、范围与算法，再加新模块。

### Stop / Pivot

满足任一应暂停当前方向：

- 少于 4/10 目标用户有重复持续研究 Job；
- 真实数据下 Top Signal usefulness < 40%，连续两轮无法改善；
- Citation correctness < 90% 或 Unsupported Claim > 10%；
- 用户持续绕过 Evidence / Claim，只把产品当摘要生成器；
- 3 个 Pilot 团队均不愿付费，且原因是核心 Brief 不进入决策流程；
- GitHub / RSS / CSV 无法覆盖任何可付费高价值场景。

## 10. 时间与责任建议

| 周 | 活动 | 主要产出 |
|---|---|---|
| 1 | 招募、artifact interviews、建立 ground truth dataset | Problem evidence、baseline workflow |
| 2 | IA / terminology tests、Signal ranking tests | IA 决策、评分呈现修订 |
| 3 | Evidence / Claim / Brief task tests | UI 与内容契约修订 |
| 4–5 | Concierge vertical slice | 真实漏斗、质量护栏、案例 |
| 6 | Pilot offer / pricing conversation | 付费承诺、范围决策 |

建议责任：

- Product：招募、访谈、行为分析、范围决策；
- Research / Evaluation：ground truth、Citation / Claim 审核；
- Design：原型、可用性测试、UI 修订；
- Engineering / Data：事件、真实来源健康、数据去重；
- Commercial owner：付费 Pilot offer，不由研究员替代销售承诺。

## 11. MVP、Later、Non-goals 的验证边界

### MVP 验证

- 一个 Watchlist；
- GitHub、RSS、CSV；
- Explainable Signal；
- 一个 Signal 发起一个 Investigation；
- Evidence / Counter-evidence / Claim 审核；
- 唯一 Decision Brief；
- Markdown PRD Research Input；
- 最近数据只读离线状态。

### Later 验证

- Today / Saved Views / Explore；
- 多人审批与评论；
- Reddit、X、小红书等来源；
- Contextual AI；
- PDF 与外部系统同步；
- 高级 Evaluations、自动通知；
- 完整离线编辑。

### Non-goals

- 用愿望调查决定功能优先级；
- 用生成文本质量代替引用正确性；
- 用注册 / 连接 Source 当激活；
- 用页面浏览量或 Agent 数量当价值；
- 在未验证核心闭环时测试全量平台覆盖。

## 12. 已裁决项与外部依赖

1. 是否能招募并使用 4–6 名 PM 的真实脱敏工作材料；若不能，Concierge 结果的外部效度会显著下降。
2. Ground truth dataset 由 Product Research 负责标签语义，Evaluation 负责人负责版本、抽样、复核与指标计算。
3. 付费 Pilot 的价格与付款形式；本文只定义必须是真实承诺。
4. `Decided` 不进入首个生产切片验证；该切片到 Decision-ready + version-bound PRD export，领域状态保留供 Later 使用。
5. “Copy Markdown”计为付费价值事件，但同一 BriefVersion 只计一次；Preview 不计。
6. Citation correctness 95% 是首轮产品实验的 provisional Go line，不是生产硬 SLO；低于 90% Stop / Iterate，90%–95% Iterate。
