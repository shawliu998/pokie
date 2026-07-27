# Qurio｜AGI 管培生申请证据索引

> 目的：让评审者在不相信宣传语、也不修改源码的前提下，快速核验一次完整的
> Research Agent 研究过程。本文只索引仓库中已经存在的事实，不新增产品能力，
> 不宣称实现了 AGI，也不把回测结果解释为未来收益。

## 适配性结论

**结论：适合作为 DeepSeek AGI 核心业务管培生的工程作品样本，但必须与个人真实
贡献说明一起提交。**

截至 2026-07-27，DeepSeek [官方招聘入口](https://talent.deepseek.com/)公开列出
“AGI 核心业务管培生”，但该公开页面没有提供足以核验学历、年限、职责权重或面试
评分规则的完整职位说明。因此：

- **事实**：Qurio 展示了受约束 Agent、模型工具使用、确定性评估、失败修复、证据
  决策和留出集隔离；对应证据见下文。
- **申请推断**：这些事实可以支持“把模型能力转化为可验证系统”的能力陈述。
- **未知**：完整岗位硬要求、筛选权重，以及作品在实际招聘流程中的相对权重。

不应把上述未知项补写成 DeepSeek 的要求，也不应仅凭本作品声称已经满足岗位全部
条件。

## 一次可核验的研究过程

研究问题：一个受约束的 Research Agent 能否研究简单、可解释的 `BTCUSD · 4h`
策略，在训练证据上只做一次适应，并且不提前打开 sealed holdout？

| 环节 | 本次运行发生了什么 | 可核验证据 |
|---|---|---|
| **Observation** | Agent 先建立 A、B 两个基础候选；训练比较是后续适应可使用的证据。 | [案例第 1 节](../QURIO_KRAKEN_DEEPSEEK_CASE_STUDY.md#1-establish-two-base-candidates)；JSON `decision.base_candidate_count = 2`、`decision.path = "A/B -> C"` |
| **hypothesis** | Agent 提出候选 C，尝试切换到已批准的另一策略家族；第一次调用因合同关系无效被拒绝，下一轮只修复错误的 action。 | [案例第 2 节](../QURIO_KRAKEN_DEEPSEEK_CASE_STUDY.md#2-reject-an-invalid-adaptation)；JSON `decision.replan_action`、`agent.event_type_counts["tool.failed"] = 1` |
| **bounded experiment** | 总实验预算只使用 3 次，形成 A、B、C 三个候选；模型只能选择已注册研究动作，指标由确定性评估器计算。 | [案例边界](../QURIO_KRAKEN_DEEPSEEK_CASE_STUDY.md#the-retained-boundary)；JSON `run.used_experiments = 3`、`decision.candidate_count = 3` |
| **comparison / evidence** | 训练指标原始排序为 C、B、A；C 没有训练交易，最小交易证据规则没有机械选择第一名，而是选择 B。 | [案例第 3 节](../QURIO_KRAKEN_DEEPSEEK_CASE_STUDY.md#3-separate-ranking-from-selection) |
| **decision** | 候选冻结后，系统只在新鲜 sealed holdout 上评估 B；结果失败，最终动作是 `revise_research`，没有继续针对留出集调参。 | [案例第 4 节](../QURIO_KRAKEN_DEEPSEEK_CASE_STUDY.md#4-open-the-sealed-holdout-once)；JSON `decision.holdout_status = "fail"`、`decision.next_step = "revise_research"` |

## 演示口径

仓库里的申请案例、应用首次打开状态和 Guided Demo 分别承担不同作用：

| 画面 | 应该怎样理解 |
|---|---|
| 首次打开的 `Validation evidence withheld` | 当前保留运行无法核对最终候选身份，因此不展示 sealed holdout。这是有意保留的证据边界，不表示 Guided Demo 运行失败。 |
| `Open guided demo` | 打开单独保存的 Binance / DeepSeek 只读通过案例，供评审者检查主要界面与历史重开；不会调用模型或写入新证据。 |
| Kraken / DeepSeek 主案例 | 这是申请材料的主要叙事：无效调用被拒绝、Agent 完成窄修复、零交易候选没有被误选，最终在 holdout 失败后停止。 |

三个画面不是同一次运行。核验工程判断时以 Kraken 主案例及其脱敏 JSON 为准；检查
产品交互时再打开 Guided Demo。

Guided Demo 里的 `+173.3%` 只是一项有边界的实验输出：对应 4 笔 holdout 交易，
walk-forward 只有 1 / 3 个正收益窗口。引用时必须同时说明交易数和验证结果，不能
把它写成未来收益、盈利能力或统计显著性的证据。

## 为什么这不是聊天套壳

| 可验证主张 | 仓库依据 |
|---|---|
| 模型负责选择研究动作，不负责生成权威收益、回撤、交易或 holdout 指标。 | [产品说明](../../../apps/mac/PRODUCT.md)；[主案例](../QURIO_KRAKEN_DEEPSEEK_CASE_STUDY.md#the-retained-boundary) |
| 工具调用会被类型合同拒绝，失败和修复均保留在证据链中。 | [主案例第 2 节](../QURIO_KRAKEN_DEEPSEEK_CASE_STUDY.md#2-reject-an-invalid-adaptation)；JSON `tool.failed = 1`、`tool.completed = 10` |
| 候选原始排名和最终选择可以不同，系统会保留选择理由。 | [主案例第 3 节](../QURIO_KRAKEN_DEEPSEEK_CASE_STUDY.md#3-separate-ranking-from-selection) |
| holdout 失败仍可构成一次成功完成的研究过程。 | JSON `run.state = "completed"` 与 `decision.holdout_status = "fail"`；[主案例第 4 节](../QURIO_KRAKEN_DEEPSEEK_CASE_STUDY.md#4-open-the-sealed-holdout-once) |
| 历史重开读取同一数据、运行和导出身份，不把演示副本描述成新实验。 | JSON `history.read_only_snapshot = true`、`market_run_identity_equal = true`、`e0_export_equal = true` |

## 最短核验路径

1. 看 [架构图](../QURIO_AGENT_ARCHITECTURE.svg)，理解 Agent 与确定性评估器的边界。
2. 读 [主案例](../QURIO_KRAKEN_DEEPSEEK_CASE_STUDY.md)，查看失败、修复、比较与停止理由。
3. 打开 [脱敏证据 JSON](./qurio-v1-kraken-deepseek.json)，核对 Provider、数据身份、事件计数、候选数量、holdout 结果与限制声明。
4. 需要检查界面时再打开 Binance Guided Demo；不要把它和 Kraken 主案例视为同一次运行。
5. 需要工程范围时，再查 [能力清单](../../POKIEQUANT_CAPABILITY_INVENTORY.md)，不要用功能数量代替主案例判断。

## 已证明与未证明

### 已证明

- 一次真实 Kraken 市场数据、真实 DeepSeek Provider、Mock 回退关闭的有界工程运行；
- Agent 的无效动作能被拒绝，并在有限预算内完成窄修复；
- 候选比较、证据不足覆盖、sealed holdout 和负面结论可以被保留并复核；
- 证据 JSON 明确记录数据、运行、模型、导出和历史重开的身份。

### 未证明

- 通用 AGI 能力；
- 未来 alpha、盈利能力或统计显著性；
- 生产规模、可用性或真实用户需求；
- DeepSeek 全部岗位要求或录用适配度；
- 仅凭技术证据无法核验申请人的贡献陈述；该部分由申请人本人负责真实性。

## 个人贡献说明

申请人确认，Qurio 的问题定义、框架设计、任务规划、实现推进、检查验证和最终验收
均由本人负责。开发中使用了 AI 编程工具和开源依赖，但工具输出是否采用、系统如何
组织、测试是否通过以及哪些结论可以公开，均由本人判断。

这并不表示 Tauri、React、FastAPI 等依赖或既有通用工程基础由申请人从零编写。
个人贡献指向 Qurio 的产品判断、研究框架、具体实现、整合和交付质量。

一句话版本、30 秒口述版、简历版、面试展开版和 AI 辅助边界说明见
[投递说明](../QURIO_DEEPSEEK_APPLICATION_BRIEF_ZH.md#个人贡献)。
