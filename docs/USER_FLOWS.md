# Glint 用户流程

> 本文以首个主用户“负责竞品与用户研究的 PM”为中心，所有 MVP 流程都服务于一条真实纵向闭环。术语与对象以 [INFORMATION_ARCHITECTURE.md](./INFORMATION_ARCHITECTURE.md) 为准。

## 1. 流程设计原则

1. 默认从 Inbox 的 Signal 开始，不从空白 Chat 或空白文档开始。
2. 每个主操作都让用户知道输入、系统行为、输出和可撤销 / 恢复方式。
3. Research Run 不暴露成 Agent 对话；普通模式显示业务步骤和输入输出数。
4. AI 可以提出综合和建议，不能代替 PM 确认 Business Impact、PM Judgment 和最终决定。
5. 任何导出都必须绑定 Decision Brief 版本与来源。

## 2. 黄金路径：权限摩擦 Signal → PRD Research Input

对象与人工审核链从 Phase 1 起真实可执行：Phase 1 使用明确标记的 Seed 或 finalized Imported CSV 与 deterministic ResearchRun；Phase 2 才以 GitHub/RSS 连续采集替换输入边；Phase 3 才以 LangGraph 替换 run provider。后续阶段不得改变下列聚合、审核和导出步骤。

### 2.1 前置条件

- Workspace 已存在。
- `AI Coding Agents` Watchlist 已启用，监控 Permissions 话题。
- Phase 1：一个 Seed/Imported Dataset 已完成 ImportSession → exact consent → verified upload → terminal ImportManifest；Phase 2+：可改为至少一个 Healthy GitHub/RSS Cloud Source。
- Inbox 已产生 `AI Coding Agent 权限摩擦上升` Signal。

### 2.2 主流程

| 步骤 | 用户行为 | 系统反馈 / 约束 | 产生的对象或事件 |
|---:|---|---|---|
| 1 | 启动 Glint | 恢复上次 Workspace，默认进入 Inbox；列表选中首个未处理 Signal | `inbox_viewed` |
| 2 | 打开权限摩擦 Signal | 首屏显示过去 7 天变化、28 天基线、独立来源、跨来源确认与数据限制 | `signal_opened` |
| 3 | 展开 Why detected 与样本 | 显示 Detection Confidence 原因；不把它写成 Business Impact | `signal_explanation_viewed` |
| 4 | 确认 Impact 与 Urgency | 一个原子 triage 命令同时记录两项人工判断、派生 Priority（任一 Unknown 则未排序）并写审计 | Signal `New → Triaged` |
| 5 | 选择 `Start Investigation` | 打开计划预览，不立刻运行 | 创建 Investigation draft |
| 6 | 编辑 Decision Question | 默认填入“是否将权限预览 / 配置诊断纳入下一季度优先级？”；PM 确认范围、来源、时间窗、预算 | `investigation_scope_confirmed` |
| 7 | 点击 Run | Investigation 进入 Active；新 Research Run 进入 Queued / Running；Signal 进入 Investigating | **首次激活事件** `investigation_started_from_signal` |
| 8 | 查看业务时间线 | 显示 Retrieve、Deduplicate、Build claims、Review counter-evidence 等步骤和输入输出计数 | Research Run events |
| 9 | 如出现 Needs input，补充范围 | 同一 manifest/checkpoint 可恢复；扩大时间窗、加入 CSV、改变预算/范围时创建新 Run，旧 Run 保持不变 | Run 恢复或新 attempt |
| 10 | 审核 Evidence | 逐条打开不可变来源版本；Valid / Weak / Reject 会追加 EvidenceReview，不修改 Evidence；检查独立来源组 | exact-Evidence review records |
| 11 | 审核 Claims | 对支持 / 反对证据、样本、限制与置信依据选择 Verify、Revise、Reject、Find more；Verify 冻结 ClaimEvidence/EvidenceReview IDs 与 digest | ClaimReview + derived projection |
| 12 | 审核中间综合 | 在 Investigation 的 Synthesis tab 检查纳入的 verified Claims、反证与限制；Verify/Revise/Reject | immutable SynthesisReview |
| 13 | 选择 `Create Decision Brief` | 仅当存在一个同 Investigation 的 verified InvestigationSynthesisVersion 时启用 | Decision Brief Draft grounded by exactly one synthesis version |
| 14 | 审阅 Brief | 用户逐块识别 Fact、origin-labelled Synthesis、PM Judgment、Recommendation；Phase 1 deterministic 不标 AI；直接 Claim/Evidence 引用必须属于该 synthesis provenance | `brief_review_started` |
| 15 | 填写 PM Judgment | PM 本人写明产品影响、取舍和是否进入优先级评审；系统可供参考但不得预填或冒充 PM 作者 | PM Judgment block with actor |
| 16 | 处理 Recommendation | 接受、修改或拒绝“权限预览”“配置诊断”等建议，补充预期影响和风险 | Recommendation status |
| 17 | 标记 `Decision-ready` | 系统校验 synthesis、Facts、Counter-evidence / Limitations、PM Judgment、引用完整性并写 exact-version review | immutable DecisionBriefReadinessReview |
| 18 | 选择 `Export → PRD Research Input` | 展示受控 Preview、selection manifest、Brief 版本和 reference digest | Export preview |
| 19 | Copy Markdown / Export `.md` | 成功后创建 terminal immutable BriefExport；失败只记录命令/AuditLog，不改变 Brief | **付费价值事件** `prd_research_input_exported` |

### 2.3 完整性门槛

`Mark Decision-ready` 只有在以下条件均满足时可用：

- Decision Question 由 PM 确认；
- 当前 DecisionBriefVersion 恰好绑定一个同 Investigation 的 verified InvestigationSynthesisVersion；
- 至少一条 Fact / Verified Claim 有可打开的 Evidence；
- 存在 Counter-evidence，或明确记录 `未发现反证` 的搜索范围与限制；
- Limitations 非空；
- 至少一条 PM Judgment 有作者；
- 所有 Recommendation 有 Proposed / Accepted / Rejected 状态；
- 引用检查通过，来源版本未删除或明确标记不可用。

## 3. 首次设置：Monitoring → 首个可用 Inbox

### 3.1 流程

1. 首次进入 Inbox，看到单一空状态：`先定义要持续回答的问题`。
2. 点击 `Set up Monitoring`，进入 Watchlist 结构化表单。
3. 输入：
   - Name：AI Coding Agents
   - Goal：识别采用障碍、迁移原因与竞品机会
   - Decision questions：哪些摩擦值得进入下一季度优先级？
   - Entities：Cursor、Claude Code、Codex、Windsurf、Zed
   - Topics：Permissions、Reliability、Pricing
   - Baseline：当前 7 天 vs 过去 28 天
4. Phase 1 在 Mac 本地解析/校验 CSV，创建不含路径/正文的 ImportSession，预览并确认 exact-scope upload consent，完成 server-verified upload，再 finalize 为 terminal ImportManifest；Phase 2 才可连接 GitHub / RSS。
5. 系统展示采集范围、Cloud / Imported 属性、权限与隐私说明；用户确认后才运行。
6. Watchlist detail 显示 `Collecting initial baseline`，同时解释尚不能产生稳定 Signal 的原因。
7. 数据量满足最小阈值后，Inbox 开始显示 Signal；若无变化则保持正常 Empty，而非制造 Demo Signal。

### 3.2 分支与恢复

GitHub/RSS 分支自 Phase 2 起适用；CSV 分支自 Phase 1 起适用。

| 条件 | 系统行为 | 用户动作 |
|---|---|---|
| GitHub 认证失败 | Source 标记 `Authentication required`，不假装正在采集 | Reconnect / 改用 RSS |
| RSS URL 无法解析 | 显示具体 URL 与错误类别 | Edit URL / Remove |
| CSV Schema 不合格 | 显示行号、字段和可下载模板 | Fix and re-import |
| Upload consent 过期/撤销 | upload-complete/finalize 均拒绝，不产生 ImportManifest；cancel 追加 exact revoke 并清理 staging | Cancel / Review scope / Start new import |
| Upload object key/size/type/digest 不匹配 | session 标记 Failed，隔离并清理对象且不产生可见 content/manifest | Cancel / Start new import |
| Finalize 暂时失败且输入未变 | session 标记 retryable，仍不可供 worker/Watchlist 使用 | Retry finalize / Cancel |
| 同一 Imported Source 已有未完成 session | 拒绝第二个 session，防止较旧 finalize 覆盖 current manifest | Resume / Cancel existing import |
| 仅一个来源可用 | 允许继续，但标记覆盖限制；不宣称 Cross-source confirmation | Add source / Accept limitation |
| 基线数据不足 | Watchlist 显示预计可检测时间和当前计数 | Wait / Import history |

完成 Watchlist 或连接 Source 不是激活；只有用户从真实 / 明确标记的 Seed Signal 发起 Investigation 才记为激活。

## 4. Inbox 处理流程

### 4.1 三种主决策

```text
Signal opened
├─ Start Investigation → Triaged → Investigating
├─ Keep monitoring     → Monitoring
└─ Dismiss             → Dismissed + reason
```

#### Start Investigation

- 适合：变化可信，且可能影响产品判断。
- 必须先确认 Decision Question、范围与预算。
- Impact / Urgency 未确认时，在计划预览中补齐。

#### Keep monitoring

- 适合：当前样本弱、影响不确定或时机未到。
- MVP 只记录选择与冷却时间，不提供复杂自定义自动化。
- 新的独立来源或显著变化可重新入箱，并解释为何打破冷却。

#### Dismiss

- 必选原因：duplicate、single-author spike、irrelevant、known issue、bad data、other。
- `bad data` 会链接到 Monitoring / Source；不自动删除原始内容。
- 反馈用于评测与后续校准，用户可以从当前会话 Undo。

### 4.2 批量处理

MVP 不提供批量 Start Investigation。可对多个 Signal 批量标记 Read / Dismiss，但 Dismiss 必须有同一适用原因且在确认框显示数量；合并 Signal 属于 Later。

## 5. Investigation 运行与人工介入

### 5.1 计划预览

在 Run 前显示：

- Decision Question；
- 子问题；
- 数据源与时间范围；
- 当前已有 Evidence；
- 预计耗时与成本区间；
- 停止条件；
- 已知覆盖风险。

用户可改范围，但不能用自由文本让 Run 获得未授权工具或数据源。

### 5.2 Needs input

触发示例：

- “企业用户”缺少可识别定义；
- CSV 列语义不明；
- 扩大数据源会增加成本；
- Counter-evidence 覆盖不足，需要 PM 决定是否延长时间窗。

流程：

1. Timeline 停在明确步骤，Sidebar 徽标 +1。
2. Detail 顶部显示问题、原因、可选项及影响。
3. 用户选择并确认；系统创建新事件，不覆盖原计划。
4. Run 从 checkpoint 恢复；失败任务不全量重跑。

### 5.3 Evidence 审核

1. 从 Claim 或 Evidence list 打开 Source Viewer。
2. 系统定位引用高亮并显示 ContentVersion、时间、来源、独立组。
3. 用户选择 `Valid`、`Weak` 或 `Reject`，可写简短原因。
4. 若拒绝后 Claim 失去最小支持，Claim 自动回到 `Needs review`，但不自动删除。

### 5.4 Claim 审核

| 动作 | 结果 |
|---|---|
| Verify | Claim 可进入 Brief 的 Fact / Evidence Summary |
| Revise | 创建新版本，保留旧文本与证据映射 |
| Reject | 不进入默认 Brief，保留审计记录 |
| Find more | 创建限定范围的补充 Run，并显示额外成本 |

## 6. 证据不足与没有反证

### 6.1 Evidence insufficient

系统不能用流畅文案掩盖证据不足。Review 结果显示：

- 缺少哪些来源 / 用户群；
- 当前样本和独立来源数；
- 哪些 Claim 不可成立；
- 可选动作：`Expand scope`、`Import evidence`、`Keep monitoring`、`Close without decision`。

此状态不能创建 Decision-ready Brief。用户可以保存 Investigation 结论为“当前不足以决策”，但它不计为付费价值事件。

### 6.2 No counter-evidence found

“未找到反证”不等于“没有反证”。系统必须记录：

- 使用过的查询；
- 来源和时间窗；
- 排除条件；
- 覆盖限制。

PM 可接受该限制继续，也可选择 Find more。Brief 中显示为 Limitation，而不是正向 Fact。

## 7. Research Run 失败、取消与恢复

### 7.1 部分失败

- Timeline 标记具体失败 Source / task 和已成功结果。
- 若剩余结果仍满足停止条件，可进入 Review，但 Brief 中自动加入覆盖限制。
- 用户可 `Retry failed step`，不重新执行成功任务。

### 7.2 全部失败

- Research Run 状态 `Failed`，保留 Plan、事件和已有 Evidence；Investigation 保持 `Active` 或进入 `Needs input`。
- 主操作为 Start new run；次操作为 Edit scope / Return to Signal。
- 不自动生成空洞 Brief。

### 7.3 Cancel

- 点击 Cancel 先说明可保留的结果和不可逆成本。
- 当前 Research Run 进入 `Cancelled`；已有 Evidence 可查看，Investigation 仍可继续，默认不可凭未审核结果创建 Brief。
- 若用户继续，创建新 Run，旧 Run 不改写；只有显式 Close Investigation 才让 Investigation 进入 `Cancelled`。

## 8. Decision Brief 审核与导出

### 8.1 四类内容交互

| 类型 | 用户可做什么 | 禁止行为 |
|---|---|---|
| Fact | 打开引用、回到 Claim、标记需要修正 | 在 Brief 中直接改数字或删来源后保留 Fact 标签 |
| Synthesis | Phase 1: Edit、Accept、View provenance；Phase 3 model origin 才增加 Regenerate | 隐藏 generation_method/generator_version；把 deterministic output 标成 AI；人工编辑后仍标成未编辑机器输出 |
| PM Judgment | Write、Edit、Confirm | AI 静默代填为 PM Judgment |
| Recommendation | Accept、Modify、Reject | 默认视为已决定或自动执行 |

### 8.2 导出流程

1. 用户选择 `Export → PRD Research Input`。
2. Preview 按固定映射展示：Context、selected Facts/Evidence、由 PM 确认的 Implications/Judgment、Accepted actions、Risks / limitations、Citations。
3. 系统强制排除 Synthesis blocks、Rejected/unverified Claim、未接受 Recommendation、内部 Run / token 信息。
4. 用户只能切换“包含哪些已允许块”，不能在 Preview 内改写正文。
5. 若需修改，返回 Brief；Preview 自动绑定新版本。
6. Copy Markdown / Export `.md` 后记录 Brief version、导出时间与操作者。

### 8.3 Evidence stale

当新 Signal / Evidence 可能影响已存在 Brief：

1. 系统追加 exact-version DecisionBriefFreshnessRecord(status=evidence_stale)；Brief list/detail 显示 `Evidence updated`，不静默改写。
2. 用户查看 diff：新增支持、反证、数据窗口变化。
3. 选择 `Review and create new version` 时调用显式 revision command，以旧 ready version 为 base、一个 verified synthesis 为 ground，创建新的 Draft；`Acknowledge, no change` 只追加 freshness assessment，不改旧正文/ready review。
4. 已导出的 PRD Input 保留原 Brief 版本；新版本需重新导出。

## 9. 离线与数据新鲜度

MVP 只承诺最近对象的只读缓存：

- 离线进入时显示全局 banner：`Offline · showing data cached at {time}`。
- Inbox、Investigation、Decision 可浏览已缓存内容；Run、Source reconnect、Start Investigation、Brief edit / export 禁用并说明原因。
- 恢复网络后用户主动 Retry 或系统刷新列表；不承诺复杂离线写入合并，因此不设计 edit conflict 流程。

## 10. 键盘黄金路径

```text
J / K      在 Inbox 移动
Enter      打开 Signal
E          打开 Evidence / Why detected
R          Start Investigation
⌘Enter     确认计划或主要动作
Esc        关闭 filter sheet / source drawer / 返回列表
⌘⇧F        当前列表高级筛选
⌘P         搜索对象
⌘K         命令菜单
```

危险或高成本动作（Cancel run、外部导出）不提供单键无确认执行；未验证 Claim 无导出绕过路径。

## 11. 关键埋点

| 事件 | 关键属性 | 用途 |
|---|---|---|
| `signal_opened` | signal、watchlist、detected_band、rank | 评估前列 Signal |
| `signal_explanation_viewed` | sections_viewed、time_to_open | 验证解释可发现性 |
| `signal_triaged` | action、impact、urgency、suggestion_origin/version、human_revision | 评估 rule/model suggestion 与 PM 判断差异 |
| `investigation_started_from_signal` | question、scope、sources、budget | 首次激活与研究意图 |
| `investigation_input_resolved` | reason、choice、pause_time | 发现流程摩擦 |
| `evidence_reviewed` | stance、rating、source_type | 评估证据质量 |
| `claim_reviewed` | action、confidence_band、evidence_count | 评估 Agent 产出 |
| `brief_marked_decision_ready` | completeness、active_time | 核心完成率 |
| `recommendation_dispositioned` | accept / modify / reject、origin | 防止把建议等同决定 |
| `prd_research_input_exported` | brief_version、format、block_count | 付费价值时刻 |

不得记录 API Key、Cookie、私有文件全文或未脱敏用户内容。

## 12. Later 流程

- 无 Signal 的主动 Investigation；
- 多 Signal 合并 Investigation；
- Reviewer 指派、评论、审批、外部分享；
- PDF 与第三方 PRD 系统双向同步；
- Quick Capture / Menu Bar；
- Contextual AI 对 Evidence 提问；
- 自定义自动化和通知；
- 完整离线编辑与冲突解决。

以上流程在真实能力实现前不应出现可点击入口。

## 13. MVP、Later、Non-goals 流程边界

### MVP 流程

- Monitoring setup → Explainable Signal；
- Signal triage → Start Investigation；
- Plan → Run → Needs input / failure recovery；
- Evidence / Claim review → Decision Brief；
- Decision-ready → PRD Research Input Preview / Markdown export；
- 最近对象的离线只读浏览。

### Later 流程

- 无 Signal 主动研究、多 Signal 合并；
- 多人评论、指派、审批和外部分享；
- PDF / 第三方 PRD 同步；
- Contextual AI、通知、自动化和完整离线编辑。

### Non-goals

- 从空白 Chat 开始核心流程；
- AI 自动确认 Impact、Urgency、PM Judgment 或最终 Decision；
- Evidence insufficient 时强行生成 Decision-ready Brief；
- PRD Research Input 脱离 Brief 独立编辑；
- 未经确认自动发布、删除数据或修改 Monitoring。

## 14. 总控裁决（2026-07-15）

1. Run 前必须由 PM 通过原子 triage 确认 Impact / Urgency；仅当两者非 Unknown 时系统派生 P0–P3，否则明确保持未排序。
2. `Closed insufficient` 不生成 Decision-ready Brief；可保存中间综合与缺口，但不计入决策产物或付费价值。
3. `Decided` 不进入首个生产切片 UI；流程停在 Decision-ready + version-bound PRD export。
4. Markdown `Copy` 是正式导出并创建 BriefExport；同一 BriefVersion 只计一次付费价值事件。
5. 离线只读；Brief 草稿编辑、write queue 与冲突解决 Later。
