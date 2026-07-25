# Qurio 面试演示脚本（3–5 分钟版）

**产品名称**：Qurio

**用途**：展示 Qurio 如何把固定公开数据、受界研究契约、A/B/C 候选修复、排名与证据选择、密封 holdout 失败，以及 E0 导出 + History 重开串成一个可验证的研究工作流。

**适用对象**：面试官、投资人、产品评审。
**时长**：主讲 90 秒，完整版 3–5 分钟，附 Q&A 与 presenter notes。

Qurio 是由单一可验证自主研究 Agent 驱动的 AI-native 量化研究工作台；本演示不声称
Agent Builder、回放/纸面交易、经纪商执行或策略盈利能力。

---

## 90 秒主讲版

> 这六张截图来自一次真实的 Qurio 研究会话。界面是历史只读重开，没有重新调用模型或 worker。我只点真实的 UI 元素。

### Node 1：固定数据与研究问题（约 20 秒）

**Presenter clicks**：Data 工作区里已保留的 **Kraken Spot BTCUSD 4h** 数据集行。

> 我先点这里。这是 Qurio 的 Data 工作区，数据来源是 Kraken Spot 公开 K 线。系统丢弃了当前未收盘的那一根，最终保留 **548 根已收盘 bar**。数据集身份固定，后面 A/B/C 三个候选人都绑定同一个不可变数据版本，起点是统一的。

### Node 2：Agent A/B → 候选 C 修复（约 20 秒）

**Presenter clicks**：Decision Ledger / learning trace 区域里“Candidate C 第一次被拒绝、第二次成功”的相邻两行。

> 然后点 Decision Ledger。这里能看到 Agent 先生成 A 和 B，再尝试创建候选 C。第一次 C 因为模板关系不匹配被拒绝；我们没有重跑整段 prompt，而是把被拒绝的输入原样返回，Agent 只改了一个字段就通过了。修复是单一、可审计的，不是模型偷偷重写候选。

### Node 3：排名 ≠ 选择（约 20 秒）

**Presenter clicks**：Analysis 页面里的训练排名，以及“最终选中 B”的说明文字。

> 接着看 Analysis。三名候选人的训练排名是 C/B/A，但 C 在训练期产生了 **0 笔交易**。所以 Qurio 按“最小交易证据”规则把选中对象改成 B，同时保留 C 作为排名参考。排名高不等于能进入 holdout，这是我们做选择时的核心约束。

### Node 4：密封 holdout 失败 → 可执行的 Refine（约 20 秒）

**Presenter clicks**：holdout 指标区域，以及下一步动作按钮 **“Review & refine research”**。

> B 进入密封 holdout 后失败。注意 holdout 总收益和按持有期年化后的收益是两个不同的数字，不能混着说。因为 holdout 失败，系统没有给出上线或推广动作，而是把下一步固定为 **Review & refine research**：先审阅下一轮要改变什么、依据什么、需要什么证据，再进入可编辑的研究设置。失败被显式保留，不会把训练集结果误当成可交付策略。

### Close：E0 导出 + History 重开（约 10 秒）

**Presenter clicks**：E0 导出按钮，再切到 History 列表中同一个 Run 的 reopen 视图。

> 最后点 E0 导出，再点 History 重开。失败结果仍然可以导出为机器可读的证据包；从 History 重新打开同一个 Run，数据集、Run 身份、选中候选、证据路径完全一致。这是真正的只读重开，没有写数据库，也没有重新调用模型。

---

## 3–5 分钟详细版

### 1. 数据：固定且可追踪（30–45 秒）

**画面**：`v1-final-183209-01-data-1440x960.png`
**Presenter clicks**：Data 页 Kraken Spot BTCUSD 4h 行 → 数据集详情面板。

讲稿：

> 这是 Qurio 的 Data 工作区。我不演示本地上传，而是直接展示已保留的 Kraken Spot 公开 BTCUSD 4 小时 K 线。原始响应移除当前未收盘 bar 后，保留 **548 根已收盘 bar**。数据集 ID 固定，本次 Run 中所有候选人都绑定这同一个不可变数据集版本。界面会显示 bar 数与数据状态，不需要去猜数据是否完整。

### 2. 研究契约与候选身份（30–45 秒）

**画面**：`v1-final-183209-02-ledger-repair-1440x960.png` 上部 Plan 区
**Presenter clicks**：已批准的 plan 卡片 → A/B/C 策略身份列表。

讲稿：

> 这是研究契约。模型只有一个受注册的 Research Agent，可用工具集和策略模板是固定的。本次三名候选人分别是：A `sma_crossover_20_100`、B `breakout_20`、C `sma_crossover_50_200`。策略身份由模板 + 参数 + canonical key 决定，没有自定义 DSL，也不让模型写任意 Python。

### 3. A/B → 被拒绝 → 修复为 C（45–60 秒）

**画面**：`v1-final-183209-02-ledger-repair-1440x960.png` 中 Decision Ledger / learning trace 区
**Presenter clicks**：Candidate C 第一次创建被拒绝的记录 → 同一行的第二次成功记录 → learning trace 的 `correction_delta`。

讲稿：

> 第一次创建 Candidate C 时被拒绝。我们没有简单重试整段 prompt，而是把被拒绝的完整参数原封不动返回给模型，Agent 只把 `replan_decision.action` 从 `refine_parameters` 改成 `switch_approved_family`，第二次就成功了。`correction_delta` 里只记录了这个字段变化，没有混入其他输入。这是可验证的修复学习，不是“模型自己重写候选”。

Presenter notes / 技术附录可补充：拒绝原因为 `ITERATION_REPLAN_TEMPLATE_RELATION_INVALID`。

### 4. 训练排名 vs 基于证据的选择（45–60 秒）

**画面**：`v1-final-183209-03-analysis-selection-1440x960.png`
**Presenter clicks**：训练排名 C/B/A → C 的 0 交易提示 → 最终选中 B 的说明。

讲稿：

> 三名候选人在训练集上的最终排名是 C/B/A。但 C 在训练期产生了 **0 笔交易**，所以结构化决策通过 robustness override / minimum_trade_evidence 把选中对象改为 B，同时引用 C 作为排名参考。这不是说 B 能赚钱，而是说在“有交易信号”这个最低证据门槛上，B 比 C 更适合进入 holdout。B 的训练指标本身也是亏损的：Sharpe 约 -2.14，最大回撤约 -17.5%，年化收益约 -38.1%。

### 5. 密封 holdout 失败与下一步（45–60 秒）

**画面**：`v1-final-183209-04-holdout-revise-1440x960.png`
**Presenter clicks**：holdout 指标卡 → “Review & refine research” 下一步动作。

讲稿：

> B 进入密封 holdout 后失败。注意区分两个数字：holdout 总收益约 -5.40%，按持有期年化后约 -67.2%；最大回撤约 -8.5%，3 笔交易。因为 holdout 失败，系统没有给上线或推广动作，而是展示下一轮的改变、证据依据和停止条件，再由 **Review & refine research** 进入可编辑的研究设置。这就是 Qurio 的诚实边界：失败被显式保留，而不是被训练集指标掩盖。

### 6. E0 导出 + History 只读重开（30–45 秒）

**画面**：`v1-final-183209-05-e0-export-1440x960.png` 与 `v1-final-183209-06-history-reopen-1440x960.png`
**Presenter clicks**：E0 导出按钮 / 导出路径 → History 列表中同一个 Run → reopen 后的只读视图。

讲稿：

> 失败的结果仍然可以被导出为机器可读的 E0 证据包。然后从 History 重新打开同一个 Run，身份、数据集、选中候选、E0 路径完全一致。这次重开是纯 SQLite 历史只读重开，没有调用 worker 或模型，数据库字节未被修改。

Presenter notes / 技术附录可补充：Run ID 为 `6ad1c324-b6c5-55af-aa51-411d676b15d8`，数据集 ID 为 `kraken-BTCUSD-4h-0b4ade74171c8dc0`，重开后 SHA-256 不变。

---

## 真相边界与失败回退

**收尾讲稿（30 秒）**：

> 这个演示不是 alpha 声明，也不证明策略盈利、模型泛化或生产可用。它证明的是：Qurio 能把固定公开数据、受界研究契约、A/B/C 候选修复、训练排名、最小交易证据选择、密封 holdout 失败，以及 E0 导出和历史重开串成一条可验证的链。失败时下一步自动是 Refine，而不是把训练集结果当成可交付策略。

**绝对禁止的说法**：

- “这个策略是盈利的 / 能跑赢市场。”
- “DeepSeek 模型在交易上很可靠。”
- “这是生产就绪的 alpha。”
- “用户已经在用了 / 有市场需求。”
- “支持券商 / 实盘交易。”
- “结果具有统计显著性。”

**可接受的说法**：

- “训练排名 C/B/A，但 C 零交易，所以按最小交易证据选了 B。”
- “B 在 holdout 失败，下一步是审阅并编辑一轮有边界的 Refine。”
- “整个链条的数据集、Run、候选、E0 身份在导出和历史重开中保持一致。”

---

## 追问附录（Q&A）

**Q：候选 C 为什么第一次被拒绝？**
A：模板关系校验失败，错误码 `ITERATION_REPLAN_TEMPLATE_RELATION_INVALID`。系统把完整输入返回给 Agent，Agent 只修正 `replan_decision.action` 一个字段后通过。

**Q：为什么选 B 而不是训练排名最高的 C？**
A：C 在训练期 0 交易，不满足最小交易证据门槛。B 虽然训练指标也是亏损的，但有交易信号，因此进入 holdout。

**Q：holdout 失败意味着什么？**
A：意味着基于当前数据和参数，B 在未参与训练选择的 holdout 区间表现不佳。系统的下一步不是上线，而是 Refine / revise research。

**Q：History 重开是真的只读吗？**
A：是。演示使用的是 SQLite 只读会话回放，不调用 worker 或模型，数据库 SHA-256 在重开前后保持一致。

**Q：E0 导出里有什么？**
A：包含该 Run 的数据集身份、候选列表、训练与 holdout 指标、选择理由、失败判定和下一步动作，是机器可读的完整证据包。

---

## 演示前准备

- 打开已保留的只读 SQLite 会话目录：`.run/v1-kraken-deepseek-20260724-183209`。
- 在仓库根目录执行以下命令；它只启动 API + Mac UI，不启动 worker，也不需要模型 key：

  ```bash
  export VITE_GLINT_ACCESS_TOKEN="$(jq -r .principal_id .run/v1-kraken-deepseek-20260724-183209/pokiequant-live-session.json)"
  .venv/bin/python scripts/launch_quant_live_session.py --readonly-reopen
  ```

- 演示的是**真实数据库只读重开**，不是重新跑模型；启动后使用终端打印的 Mac UI 地址。
- 确认六个 1440×960 截图已就位：
  1. `docs/assets/pokiequant/v1-final-183209-01-data-1440x960.png`
  2. `docs/assets/pokiequant/v1-final-183209-02-ledger-repair-1440x960.png`
  3. `docs/assets/pokiequant/v1-final-183209-03-analysis-selection-1440x960.png`
  4. `docs/assets/pokiequant/v1-final-183209-04-holdout-revise-1440x960.png`
  5. `docs/assets/pokiequant/v1-final-183209-05-e0-export-1440x960.png`
  6. `docs/assets/pokiequant/v1-final-183209-06-history-reopen-1440x960.png`

## 演示核对清单

- [ ] 六个截图路径存在且分辨率为 1440×960。
- [ ] 90 秒主讲不提 token、终端命令、devtools、SHA 值、错误码、精确工程内部值。
- [ ] 区分 holdout 总收益与年化收益。
- [ ] 强调“C 训练排名第一但零交易，因此未选中”。
- [ ] 强调 holdout 失败后下一步是 Review & refine research，不是推广。
- [ ] 说明 History 是只读重开，未重新调用模型。
- [ ] 出现任何追问盈利/可靠性/生产就绪时，回退到本脚本的“真相边界”。
