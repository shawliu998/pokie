# Glint Jobs to Be Done

> 范围：Phase 0；主用户为负责竞品与用户研究的产品经理。本文描述用户要完成的进步，不把“使用 AI”“查看 Dashboard”或“生成报告”当作 Job。

## 1. 核心 Job

### Job statement

> 当我发现竞品或用户反馈可能正在发生重要变化、但信息分散且真实性不明时，我想快速判断变化是否真实、影响哪些产品决策，并形成一份团队可追溯和可复用的 Decision Brief，这样我能有依据地决定是否把问题纳入下一季度优先级，而不是被噪声或一段 AI 摘要推动。

### 标准场景表达

> 当 AI Coding Agent 的权限摩擦相关讨论突然上升时，我想确认它是否是跨来源、持续且与目标用户相关的真实问题，评估“权限预览 / 配置诊断”是否值得进入下一季度优先级，并把证据与我的判断带进 PRD。

## 2. Job 的三个维度

### 2.1 Functional job

- 持续监控明确的竞品、用户群与产品话题。
- 从内容噪声中识别值得处理的变化。
- 理解 Signal 的检测依据、数据质量与限制。
- 把一个 Signal 转换为有范围、预算和停止条件的 Investigation。
- 审核支持证据、反对证据和 Claims。
- 将研究结论转换为唯一、可版本化的 Product Decision Brief。
- 将 Brief 的受控内容复用为 PRD Research Input。
- 在新证据出现时判断旧决策是否需要更新。

### 2.2 Emotional job

- 在产品评审前对“为什么相信这个结论”有底气。
- 不因遗漏重要竞品变化而焦虑。
- 面对 AI 生成内容时保持掌控，而不是承担黑盒输出的责任。
- 能在证据不足时坦然得出“现在不应决策”，而不是被迫产出确定性结论。

### 2.3 Social job

- 向产品负责人、设计与工程团队展示严谨、可复核的判断过程。
- 让团队清楚哪些是事实、哪些是 AI 综合、哪些是 PM 自己的取舍。
- 让 PRD 中的研究输入看起来不是“网上看到的一些反馈”或无来源的 AI 文案。

## 3. 当前替代方案

| 阶段 | 常见替代方案 | 用户获得的价值 | 主要缺口 |
|---|---|---|---|
| 监控 | GitHub notifications、RSS reader、社区浏览、竞品 newsletter | 覆盖原始内容 | 噪声高、没有统一基线与独立来源判断 |
| 归集 | Notion、飞书文档、Google Sheets、书签 | 手工控制、易分享 | 复制粘贴、去重困难、来源版本丢失 |
| 综合 | ChatGPT / Claude、内部聊天 | 快速摘要 | 容易混淆事实与推断，反证与限制不足 |
| 决策 | PRD、季度规划表、评审会议 | 进入正式流程 | 研究依据散落，变更后难追踪 |
| 更新 | 定期重新搜索、同事提醒 | 灵活 | 依赖记忆，旧判断不会被系统性复查 |

Glint 不是替代完整 PRD 工具，而是补齐“从持续信号到可追溯决策输入”的断层。

## 4. Job map

### 4.1 Define：定义要持续回答的问题

用户需要：

- 把“关注 AI Coding Agents”改写为具体业务目标和 Decision questions；
- 指定实体、别名、Topics、包含 / 排除条件；
- 选择 GitHub、RSS、CSV 的范围与运行位置；
- 理解当前来源覆盖能回答什么、不能回答什么。

期望结果：

- 不需要数据工程知识即可检查监控规则；
- 用户可预见什么会进入 Inbox；
- 系统不会把来源不足包装成完整覆盖。

MVP 对应：Monitoring / Watchlist + Sources。

### 4.2 Detect：发现值得看的变化

用户需要：

- 每次打开产品都能先看到待处理 Signal，而非空白 Chat 或指标墙；
- 快速分辨真实异常、重复转载、单一作者热点和数据回补；
- 知道 Detection Confidence 的原因，而不是只看到 Severity 分数；
- 在 1–2 分钟内决定 Investigate、Keep monitoring 或 Dismiss。

期望结果：

- 前列 Signal 中真正值得处理的比例足够高；
- 低样本、来源异常或关键词歧义明确暴露；
- 未确认的 AI Business Impact 不操纵优先级。

MVP 对应：Inbox。

### 4.3 Frame：把变化变成决策问题

用户需要：

- 从 Signal 继承上下文，但把它改写成可回答的 Decision Question；
- 明确时间窗、目标用户、来源、成本与停止条件；
- 在 Run 之前确认 Business Impact 与 Urgency；
- 知道研究可能无法得出确定结论。

期望结果：

- Investigation 有清楚边界，不退化成“帮我深入研究”；
- 用户能预测增加来源或扩大范围的成本；
- Signal 与最终 Decision Brief 可双向追溯。

MVP 对应：Start Investigation / Plan preview。

### 4.4 Gather：收集并组织证据

用户需要：

- 并行检索 GitHub、RSS 与导入 CSV；
- 去除精确重复和近似转载，同时保留独立表达；
- 看到每一步的输入输出数量、失败和重试；
- 在需要语义判断或成本变化时介入。

期望结果：

- 不把“内容条数”错误当作“独立证据数”；
- 部分失败不抹掉已完成工作；
- 运行状态用业务时间线表达，不要求理解 Agent graph。

MVP 对应：Investigation / Runs。

### 4.5 Verify：验证 Evidence 与 Claims

用户需要：

- 从引用回到不可变原文版本和上下文；
- 检查 Evidence 是支持、反对还是中性；
- 看到样本、来源多样性、置信度输入与 Limitations；
- 修改或拒绝不成立的 Claim；
- 在没有找到反证时知道搜索覆盖的边界。

期望结果：

- Claim 的引用确实支撑它；
- 相关性不会被写成因果；
- AI 不会用流畅表达掩盖证据不足。

MVP 对应：Investigation / Evidence + Claims。

### 4.6 Decide：形成负责性的产品判断

用户需要：

- 把已验证事实与 AI 综合分开阅读；
- 自己确认 Business Impact、取舍与 Decision；
- 对 Recommendation 接受、修改或拒绝；
- 在证据不足时记录“不进入优先级”或“继续监控”。

期望结果：

- 团队知道每段内容由谁负责；
- Recommendation 不被误解成已批准动作；
- Decision-ready 有清楚完整性门槛。

MVP 对应：Decisions / Product Decision Brief。

### 4.7 Reuse：进入现有产品流程

用户需要：

- 在不重新复制整理的情况下生成 PRD Research Input；
- 只导出选定 Brief 版本中允许的内容；
- 保留引用、限制、版本与 PM Judgment；
- 不让旧导出被后续生成内容静默覆盖。

期望结果：

- 研究结果可直接进入 PRD 或季度评审；
- 导出内容仍可追溯回 Glint；
- 用户感受到节省的不是写作时间，而是验证与重组时间。

MVP 对应：PRD Research Input Preview / Markdown export。

### 4.8 Revisit：用新证据复查旧判断

用户需要：

- 知道哪些 Brief 的 Evidence 已更新或变旧；
- 对比新支持、反证和数据窗口变化；
- 决定创建新版本或确认无需变更。

期望结果：

- 决策记录不会被静默重写；
- 团队能解释“当时为什么这样决定”；
- 重要旧判断不会因无人记得而永久失效。

MVP 仅承诺 stale 标记与版本；自动复查策略属于 Later。

## 5. 关键期望结果与优先级

评分：Importance 1–5；当前 Satisfaction 1–5。Opportunity 仅作为 Phase 0 假设，必须通过访谈验证。

| Outcome statement | Importance | 当前 Satisfaction（假设） | MVP 优先级 |
|---|---:|---:|---|
| 最小化判断一个变化是否值得研究所需的主动时间 | 5 | 2 | Must |
| 最小化被重复转载、单一作者或数据故障误导的概率 | 5 | 2 | Must |
| 最小化从结论定位到原文上下文的时间 | 5 | 2 | Must |
| 最大化 Claim 同时覆盖支持与反对证据的概率 | 5 | 1 | Must |
| 最小化团队混淆事实、AI 综合、PM 判断与建议的概率 | 5 | 1 | Must |
| 最小化从完成研究到形成 PRD 可用输入的重复整理 | 4 | 2 | Must |
| 最大化在证据不足时暴露限制的清晰度 | 5 | 2 | Must |
| 最小化理解 Research Run 状态所需的技术知识 | 4 | 2 | Must |
| 最小化旧 Brief 因新证据出现而无感过期的概率 | 4 | 1 | Should |
| 最大化跨团队内容发布和多格式输出数量 | 2 | 3 | Later |

## 6. Forces of progress

### 6.1 Push：推动用户离开现状

- 每周浏览来源花费数小时，仍担心漏掉真正重要的变化。
- 高声量内容经常只是转载或单一账号，不足以支持产品优先级。
- 研究结论在评审中被追问来源、反证和样本，PM 临时补材料。
- AI 摘要很快，但 PM 不愿为不透明结论负责。

### 6.2 Pull：吸引用户采用 Glint

- Inbox 直接提供可解释 Signal，而非原始内容流。
- Evidence、Claim 与 Brief 之间可追溯。
- Decision Brief 明确作者责任并能直接导出 PRD Research Input。
- 新 Evidence 会提示旧判断需要复查。

### 6.3 Anxiety：采用焦虑

- 数据源覆盖是否足以代表用户真实问题？
- 公司访谈 CSV 是否会被上传或用于模型训练？
- AI 是否会虚构引用或把相关性写成因果？
- 系统是否制造更多需要处理的提醒？
- 将结果粘进 PRD 后，来源是否还能被团队打开？

产品回应必须是可见边界、来源版本、隐私范围、解释和人工确认，而不是营销承诺。

### 6.4 Habit：现有惯性

- PM 已经熟悉浏览器标签页 + Notion / Sheets。
- 临时把链接丢进团队聊天的切换成本低。
- 季度研究并非每天发生，连接和配置新工具的收益会被推迟。
- 现有 PRD 模板已经固定，团队不愿迁移主文档工具。

因此 MVP 必须把首次设置压缩到一个 Watchlist，并用 Markdown 进入现有 PRD，而不是要求团队迁移完整文档系统。

## 7. 场景化 Job stories

### 7.1 处理高潜力 Signal

当 Inbox 告诉我“权限负面反馈增长”时，我想看到基线、独立来源、跨来源确认和限制，这样我能判断它是真实变化还是噪声。

验收：用户能在 2 分钟内正确复述触发原因，并指出至少一个限制。

### 7.2 避免单一热帖误导

当一个 GitHub Issue 被大量转载时，我想知道内容量与独立作者 / 独立来源的差别，这样我不会因为虚假热点发起昂贵研究。

验收：single-author / duplicate penalty 被显式说明，用户能 Dismiss 并选择准确原因。

### 7.3 审核反面证据

当 AI 提出“权限不可预测是主要采用障碍”的 Claim 时，我想同时看到反对证据和覆盖缺口，这样我能决定验证、修改还是拒绝。

验收：用户能从 Claim 定位支持与反对 Evidence，并发现一个故意植入的弱引用。

### 7.4 记录 PM 判断

当研究完成时，我想把事实和 AI 综合作为输入、但由我写下产品影响和取舍，这样团队知道最终判断由谁负责。

验收：用户不会把 AI Recommendation 误认成已批准 Decision。

### 7.5 复用到 PRD

当 Brief 通过完整性检查时，我想预览并复制一个受控 PRD Research Input，这样我不需要重新拼接摘要、引用和限制。

验收：用户无需手工重新查找来源即可完成导出，导出绑定 Brief 版本。

## 8. MVP、Later、Non-goals 的 Job 边界

### MVP Jobs

- 定义一个结构化 Monitoring 范围；
- 处理可解释 Signal；
- 从 Signal 发起限定范围 Investigation；
- 审核 Evidence、Counter-evidence 与 Claim；
- 创建并确认 Decision Brief；
- 受控导出 PRD Research Input；
- 对 Signal 与 Evidence 质量提供最小反馈。

### Later Jobs

- 跨项目 Today 待办管理；
- 无 Signal 的主动探索研究；
- 多人分工、评论、审批和管理层分享；
- 多语言、更多来源与复杂通知；
- 内容 / 市场输出、PDF 和外部工具同步；
- 高级 Evaluation 和 Prompt 治理；
- 完整离线工作与冲突解决。

### Non-goals

- 与通用 AI 自由聊天以替代产品研究；
- 自动决定路线图或自动修改 PRD；
- 自动发布对外内容；
- 用更多 Dashboard、Agent 或报告数量证明价值；
- 覆盖所有互联网平台后再交付价值。

## 9. 激活与付费价值对应的 Job

### 首次激活

用户完成 Detect → Frame 的第一次跨越：

> 理解一个 Signal 的入箱原因，并以明确 Decision Question 发起 Investigation。

这说明用户不只把 Glint 当阅读器，而是愿意让它进入真实研究工作。

### 付费价值

用户完成 Decide → Reuse：

> 把包含 Facts、Counter-evidence / Limitations 和 PM Judgment 的 Decision-ready Brief，以受控 PRD Research Input 复用。

这说明 Glint 已替代部分手工验证与整理工作，并影响真实产品流程。

## 10. 待验证假设

1. PM 的最大痛点是证据验证与重组，而不仅是信息发现。
2. “Signal-first”比“直接问研究问题”更符合持续研究场景。
3. 用户愿意为可信度确认 Impact / Urgency，而不会认为是额外录入。
4. 四类内容来源标签能提升责任清晰度，不会造成编辑器过载。
5. “未发现反证 + 搜索范围”对用户比一个高置信分更有帮助。
6. Markdown 导出足以进入多数团队的 PRD 工作流。
7. 复查 stale Brief 是高频价值，还是只在少数重大主题上需要。

具体验证样本、任务和通过阈值见 [PRODUCT_VALIDATION_PLAN.md](./PRODUCT_VALIDATION_PLAN.md)。
