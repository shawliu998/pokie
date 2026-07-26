# Qurio 面试演示脚本（3–5 分钟）

## 一句话定位

Qurio 是由一个受界自主 Research Agent 驱动的 AI-native 量化研究工作台：它把固定市场数据、可审批计划、候选实验、比较证据、密封 holdout 决策和下一版本串成一条可验证主线。

它不是 Agent Builder、券商或实盘交易平台。Paper Trading 是与研究隔离的本地模拟边界，只有最终候选通过密封 holdout 后才能创建待复核订单。

## 90 秒主讲

### 1. 独立安装与首次启动

> 这是可独立安装的 Apple-silicon macOS 应用。DMG 内置 FastAPI、Quant Agent worker 和本地数据库，面试演示不需要仓库、Python 或 Node。首次启动默认使用 Offline deterministic，无需 API key；也可以在 Settings 配置 DeepSeek，或填写一个 OpenAI-compatible HTTPS Base URL、模型和独立 Keychain API key。

不要在主讲中展示终端。若被追问，再说明当前包采用 ad-hoc 签名，公开分发前仍需 Developer ID 与 Apple notarization。

### 2. 从保留数据开始

打开 **Data**，展示 `BTCUSDT · 4h` 数据预览。

> Agent 不从一句聊天直接“猜策略”。我先选一份已验证、具有固定身份和覆盖范围的数据，再定义可衡量的研究目标。这个演示使用确定性 fixture，因此证明的是产品工作流，不是行情真实性或 alpha。

对应截图：`p1c-01-data-1440x960.png`

### 3. 计划先于执行

点击 **Generate plan**，展示待审批计划，再点击 **Approve & run**。

> Qurio 先冻结研究范围、候选家族、比较目标与完成条件。Agent 只有在批准后才能运行受注册工具；它不能写任意 Python、访问 shell、Broker 或下单。

对应截图：`p1c-02-plan-approval-1440x960.png`

### 4. 让 Agent 的自主性可读

切到 **Experiments**。

> 右侧 Research memo 只回答三件事：现在在做什么、出现了什么重要观察、为什么进行当前实验。这里 A 已完成，B 正在运行；中间区域保留最新训练证据与候选表。Agent 是主动执行和适应的，但每一步仍绑定批准的研究边界。

对应截图：`p1c-03-live-ab-1440x960.png`

### 5. 从观察适应到最终选择

等待运行结束，展示 Candidate comparison 与 Decision Ledger。

> Qurio 不把“模型思考日志”当产品。A/B 的训练结果形成结构化观察，再驱动 Candidate C；最终选择同时保留候选身份、比较指标和选择理由。排名、选择与 holdout 是不同阶段，不能混成一个结论。

对应截图：`p1c-04-observation-to-c-1440x960.png`

### 6. 诚实决策、Refine、导出与历史

切到 **Decision**，展示 holdout 失败结论、**Refine version** 与 **Export evidence**。

> 这个 Run 的密封 holdout 不支持推广，所以 Qurio 不生成 Paper 或上线动作，而是给出一项有边界的 Refine：改变什么、证据依据是什么、何时停止。证据包由服务端生成；History 重开同一 Run 时保持只读身份。

对应截图：

- `p1c-05-report-json-1440x960.png`
- `p1c-06-history-reopen-1440x960.png`

## 3–5 分钟展开顺序

1. **安装形态（20 秒）**：DMG → Applications → 首次启动选择 Offline deterministic。
2. **Data（30 秒）**：来源、interval、coverage、bar count、Research ready。
3. **Research Contract（30 秒）**：目标、候选家族、选择目标、完成条件。
4. **Agent 运行（45 秒）**：Now、Material observation、Why this experiment、实验预算。
5. **比较与适应（45 秒）**：A/B → Observation → Candidate C → Final choice。
6. **Analysis（30 秒）**：Equity、Drawdown、Trades；强调训练证据与 benchmark。
7. **Decision（45 秒）**：holdout 状态、Qurio decision、Refine version、停止条件。
8. **Export / History（30 秒）**：机器可读 evidence bundle 与历史只读重开。
9. **可选 Paper（20 秒）**：换到 sealed-holdout pass fixture，说明仅为本地确定性模拟，不连接 Broker。

## 真相边界

可以说：

- “Qurio 已完成 Data → Plan → Experiments → Compare → Analyze → Decision → Refine / History 的可执行主线。”
- “Agent 会根据保留的训练观察生成 Candidate C，但只能使用批准的策略模板和工具。”
- “密封 holdout 失败时不会进入 Paper；通过时才允许建立待复核的模拟订单。”
- “应用可独立安装，并提供无 key 的 Offline deterministic 首次启动路径。”

不要说：

- “这个策略能盈利或跑赢市场。”
- “已经有真实用户或验证了市场需求。”
- “支持券商、实盘、任意 Python 策略或 Agent marketplace。”
- “当前包已经 Apple notarized，任何 Mac 都能无提示安装。”
- “fixture 结果证明 Binance、Kraken 或 DeepSeek 的生产可靠性。”

## 常见追问

**为什么不是聊天框？**

量化研究的核心对象是数据、计划、实验、比较和结论。对话只辅助定位证据，不能代替结构化研究状态。

**Agent 的新意是什么？**

不是多 Agent 数量，而是一个有预算、有工具边界、能从训练观察适应候选、又能被完整验证的 Research Agent。界面直接呈现它的当前行动、重要观察和实验理由。

**持续学习在哪里？**

当前实现的是 verified learning：保留 Research Series、版本、尝试、修复差异和证据引用。它不会未经批准修改基础模型权重，也不会把聊天历史伪装成长期记忆。

**Paper Trading 是实盘吗？**

不是。它是 workspace-scoped、确定性的本地模拟账户与订单边界，没有 Broker host、凭证或 live-order route。

**为什么限制任意 Python？**

当前产品的差异化是权威证据链，而不是通用 IDE。固定模板和 canonical strategy identity 让候选比较、holdout 与历史重开保持同一计算路径。

## 演示前检查

- 使用最新 `Qurio_0.1.0_aarch64.dmg`，或运行下方确定性浏览器路径。
- 1440×960 下确认 Data、Plan、Experiments、Decision、History 无横向溢出。
- 1024×960 下确认导出弹窗的 Close 与 Download 按钮可用。
- 主讲使用当前按钮名：**Refine version**、**Export evidence**、**Generate next plan**。
- 不展示 access token、API key、私有路径或终端环境变量。

重建安装包：

```bash
pnpm --dir apps/mac package:mac
```

重放黄金路径并刷新截图：

```bash
GLINT_E2E_API_MODE=fixture \
GLINT_FIXTURE_PORT=4521 \
GLINT_E2E_APP_PORT=5521 \
POKIEQUANT_CAPTURE_SCREENSHOTS=1 \
pnpm --dir apps/mac exec playwright test e2e/p1c-golden-visual-proof.spec.ts
```

安装包位置：

- `apps/mac/src-tauri/target/release/bundle/macos/Qurio.app`
- `apps/mac/src-tauri/target/release/bundle/dmg/Qurio_0.1.0_aarch64.dmg`
- `apps/mac/src-tauri/target/release/bundle/dmg/SHA256SUMS.txt`
