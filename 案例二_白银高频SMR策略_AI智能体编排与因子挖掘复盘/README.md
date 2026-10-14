# 案例二：白银高频微观结构自适应 Timing 与深度在线蒸馏策略 (SMR) — AI 智能体编排与因子挖掘全景复盘

> **项目目标**: 建立不依赖黑箱的、工业级、完全透明且可稳定复现的 AI 智能体量化研发标准范式。  
> **核心标的**: 白银现货与永续合约 (`XAGUSDT` / `SHFE ag`)  
> **研究课题**: 量化金融 / 高频均值回归 SMR (Silver Mean Reversion)  
> **目标指标**: 年化复合收益率 (CAGR) **42.1%** ｜ 夏普比率 (Sharpe) **2.08** ｜ 胜率 **64%** ｜ 管理容量 **8000 万 CNY**

---

## 一、文档导航与交付矩阵

本案例目录完整收录了从最初的学术论文检索、TradingView 快速脚本试错、到推翻重构进入微软 RD-Agent、AlphaGPT、Qlib 与 NautilusTrader 生产级回测审查的全生命周期：

| 模块文件 | 核心内容与价值 |
|---|---|
| **[`01_AI编排工作流与多Agent协同架构.md`](./01_AI编排工作流与多Agent协同架构.md)** | **【多 Agent 协同宪法】** Captain-Worker 两级拓扑、Herdr Dispatch 调度规范、输入输出契约隔离、子 Agent 自动销毁只留主 Session 的零资源泄露原则。 |
| **[`02_用户提示词全景演进与投研决策拓扑.md`](./02_用户提示词全景演进与投研决策拓扑.md)** | **【Prompt 全景演进图】** 逐轮忠实记录人类研究员的高阶 Prompt、意图演进拓扑、从浅层 Pine 转向工业级多智能体系统的范式大跃迁。 |
| **[`03_独立因子挖掘与样本外复现标准.md`](./03_独立因子挖掘与样本外复现标准.md)** | **【双引擎独立因子挖掘】** 微软 RD-Agent / Qlib 算子群（12 个通过因子）与 AlphaGPT 符号表达式树（6 个通过因子），给出前 80% IS 与 后 20% OOS 盲测指标表。 |
| **[`04_Credal_Transformer反过拟合审查与NautilusTrader回测引擎.md`](./04_Credal_Transformer反过拟合审查与NautilusTrader回测引擎.md)** | **【反过拟合审查机制】** NeurIPS 2025 Credal Transformer 狄利克雷证据不确定性门控 ($u \le 0.35, C < 0.40$)、通缩夏普 (DSR)、Harvey-Liu 发型扣减与 NautilusTrader 事件驱动引擎。 |
| **[`05_多时间共振与微观执行诊断白皮书.md`](./05_多时间共振与微观执行诊断白皮书.md)** | **【多时间尺度深度诊断】** 严谨数学实测解答“为什么 15m 回测、1m 信号究竟怎么用、为什么必须小周期 Timing 入场大周期退出、三层多时间共振架构”及第二阶段 LOB 演进方案。 |
| **[`code/`](./code/)** | **【生产级可复现源码与结果】** 包含全套经过实跑检验的 Python 脚本、NautilusTrader 策略类、Credal 门控审查模块与原始回测结果 JSON。 |

---

## 二、代码资产库说明 (`code/` 目录)

为确保任何人或 AI 均能“一键确定性复现”本案的所有实测数据，关键代码资产均归档于 `code/`：

1. **`rd_qlib_miner_smr.py`**: 微软 RD-Agent / Qlib 因子自动计算与 15m/1m 滚动 IC 检验引擎；
2. **`credal_smr_audit.py`**: NeurIPS 2025 Credal Transformer 狄利克雷证据不确定性门控类、通缩夏普比率 (DSR) 及 1,000 次蒙特卡洛置换检验模块；
3. **`nautilus_silver_smr.py`**: NautilusTrader 1.221.0 原生事件驱动策略类（`NautilusSilverSMRStrategy` 与 `NautilusSilverSMRConfig`）；
4. **`run_nautilus_smr_production.py`**: 生产级 Walk-Forward 80% IS / 20% OOS 回测与全摩擦审计执行器；
5. **`smr_production_audit_summary.json`**: 真实运行输出的全部统计指标原始 JSON。

---

## 三、快速复现指引 (Step-by-Step Reproduction)

```bash
# 1. 进入案例代码目录
cd 案例二_白银高频SMR策略_AI智能体编排与因子挖掘复盘/code

# 2. 运行 Qlib / RD-Agent 因子挖掘与 OOS 检验
python3 rd_qlib_miner_smr.py

# 3. 运行 NautilusTrader 策略回测与 Credal Transformer 审计
python3 run_nautilus_smr_production.py
```

---

## 四、未来项目复用标准操作程序 (SOP)

当将此套工作流复用于其他任何全新项目（例如铜期货均值回归、原油日内动量、比特币高频做市）时，严格遵循以下四步：

1. **第一步（隔离双盲挖掘）**：将新标的的纯 OHLCV 数据分发给两个独立的 Worker 智能体（一个跑 AlphaGPT，一个跑 RD-Agent + Qlib），各自输出候选因子；
2. **第二步（OOS 严苛门槛）**：只筛选在后 20% 盲测集上 Rank IC > 0.030 且 $t > 2.50$ 的因子，剔除与均线相关度 $> 0.40$ 的共线性因子；
3. **第三步（多时间尺度解耦）**：分析新标的的单 Bar 平均波幅与交易摩擦比值，严禁在波幅小于 10 bps 的微观周期上直接平仓，确立“小周期 Timing、大周期 Anchor”的跨时间共振架构；
4. **第四步（Credal 门控与 Nautilus 回测）**：接入 Credal Transformer 进行防过拟合审查，计入悲观滑点与 Maker/Taker 费率，执行 DSR 与蒙特卡洛检验。
