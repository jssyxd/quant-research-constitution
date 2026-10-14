# 案例二 · 模块一：AI 编排工作流与多 Agent 协同架构白皮书

> **定位**: 量化投研智能体蜂群调度宪法与工程实践规范  
> **核心原则**: **拒绝黑箱欺骗，确保每一步智能体行动可追溯、可审计、确定性复现**

---

## 1. 架构总览：总指挥 (Captain) - 执行者 (Workers) 两级拓扑

在传统量化研究中，由单一 LLM 会话长篇累牍地进行代码撰写与回测往往会导致上下文失真、自我印证幻觉（Self-Confirming Hallucination）与不可控调参。本体系采用分权制衡的多智能体蜂群协议（基于 `herdr-dispatch` 运行时）：

```
+---------------------------------------------------------------------------------------------------+
|                                  总指挥会话 (Captain Agent: omp / wT:p1)                          |
|                                                                                                   |
|  职责:                                                                                             |
|  - 目标解构与决策仲裁 (Task Decomposition & Arbitration)                                            |
|  - 确立阶段性假设与物理边界约束 (No-LOB Stage 1 vs LOB Stage 2)                                     |
|  - 动态调度子智能体生成独立工件 (Dispatch via herdr-dispatch)                                       |
|  - 收集交付物、统一审查反过拟合 (Credal Transformer & DSR)                                          |
|  - 任务完成后主动关闭子 Agent 窗格，终局仅保留主控 Session (Auto Cleanup)                           |
+---------------------------------------------------------------------------------------------------+
                                   │                              │
                   独立任务分发     │                              │ 独立任务分发
                 (Strict Brief)   │                              │ (Strict Brief)
                                   ▼                              ▼
+--------------------------------------------------+  +---------------------------------------------+
|    子智能体 1 (Worker: alphagpt-miner / wT:p4)     |  |   子智能体 2 (Worker: rd-qlib-miner / wT:p5)    |
|                                                  |  |                                             |
|  - 运行模型: cpa/gemini-3.8-flash-high           |  |  - 运行模型: cpa/gemini-3.8-flash-high      |
|  - 独立沙盒: .herd-dispatch/jobs/alphagpt-miner/ |  |  - 独立沙盒: .herd-dispatch/jobs/rd-qlib-   |
|  - 职责: 专注于 AlphaGPT 符号表达式树挖掘         |  |    miner/                                   |
|  - 输入: XAGUSDT 纯 OHLCV Parquet 数据           |  |  - 职责: 专注于微软 RD-Agent 假设驱动循环   |
|  - 产出: deliverable.md (6个公式化因子)          |  |    及 Qlib Alpha158/360 算子群              |
|  - 状态: 交付确认后由 Captain 主动 stop --yes 关闭 |  |  - 产出: deliverable.md + 计算脚本          |
+--------------------------------------------------+  +---------------------------------------------+
```

---

## 2. 调度动作生命周期 (Action Lifecycle)

为了保证 AI 协同全流程可复现，每一个智能体动作必须被显式日志化，禁止任何隐藏的终端后台幽灵进程：

### 步骤 1：系统体检与环境准入 (Doctor Precondition)
总指挥在分发任务前，必须执行环境自检：
```bash
python3 /home/da/.omp/agent/skills/herdr-dispatch/scripts/herd-dispatch doctor
```
- **输出约束**: 必须返回 `"ok": true`，确认 Captain Pane ID（如 `wT:p1`）与支持的智能体模型集合（`pi`, `omp`, `opencode` 等）。

### 步骤 2：建立隔离工作区与输入契约 (Contract Invariant)
严禁跨智能体共享未锁定的中间草稿文件。为每个 Worker 建立专属目录：
- `.herd-dispatch/jobs/<worker-name>/input.md`: 包含严格任务边界、数据路径、入选门槛与格式要求；
- `.herd-dispatch/jobs/<worker-name>/brief.md`: 冻结的系统指令。

### 步骤 3：异步分配与挂起监控 (Async Assign & Fleet Watch)
```bash
python3 scripts/herd-dispatch assign \
  --kind pi \
  --model cpa/gemini-3.8-flash-high \
  --name rd-qlib-miner \
  --message-file .herd-dispatch/jobs/rd-qlib-miner/input.md
```
- **状态转移**: `assign` 触发后，Worker 在后台专属 Pane (`wT:p5`) 开始执行计算；
- **群组监控**: Captain 通过定期检查 Worker 的生命周期状态（`working` $\to$ `done`），避免轮询阻塞。

### 步骤 4：交付归档与安全销毁 (Collect & Clean Teardown)
Worker 将成果输出为物理文件 `deliverable.md` 后，状态变为 `done`。总指挥读取验证其内容有效性后，**必须执行确定性销毁命令**：
```bash
python3 scripts/herd-dispatch stop --name rd-qlib-miner --yes
python3 scripts/herd-dispatch stop --name alphagpt-miner --yes
```
- **终局断言**: 终端环境由多 Pane 自动缩容收敛，仅保留 Captain 主窗口，消除算力泄露与残留进程。

---

## 3. 多智能体协作防欺骗八项铁律

1. **零共享代码库原则（Zero Shared Scratchpad）**：不同矿工（如 AlphaGPT 与 RD-Agent）必须物理隔离运行，严禁相互读取中间过程，确保两套工具挖掘因子的独立性与正交性；
2. **零硬编码结果注入（No Hardcoded Summaries）**：严禁 Worker 在终端打印预设的“高夏普假回测”，必须在工作目录下留下经过 Python 实际运算生成的原始 Parquet / CSV / 计算脚本；
3. **前向因果切分不可逆（Irreversible Chronological Split）**：前 80% 为 In-Sample，后 20% 为 Out-of-Sample，严禁将全量数据均值参与因子标准化，所有滚动统计指标必须使用前向滑动窗；
4. **摩擦成本不可省略（Friction Non-Zero Invariant）**：必须显式输入 Maker 0.02%、Taker 0.05%、滑点 5 bps，任何宣称“零滑点下年化 50%”的中间产物一律判定为无效作弊；
5. **算力即时释放（Terminal State Cleanliness）**：任务达成后，所有辅助子 Agent Pane 必须完全关闭，不留任何常驻悬挂 Shell；
6. **证据真空度强制门控（Credal Uncertainty Veto）**：任何单因子或多因子组合在回测前必须通过 Credal Transformer 狄利克雷审查，证据真空度 $u > 0.35$ 拥有一票否决权；
7. **多时段衰减穿透测试（Multi-Horizon Audit）**：因子不仅要在 1-bar 检验，必须同时拉取 2-bar (30m)、4-bar (1h) 的 Rank IC 衰减曲线，证明具有实际报单执行跑道；
8. **可移植复用性（Portability Standard）**：全套流程封装为统一参数接口，更换资产代码（如从 XAGUSDT 切换为 BTCUSDT 或原油 CL）时，仅需替换底层数据路径即可无缝复现。
