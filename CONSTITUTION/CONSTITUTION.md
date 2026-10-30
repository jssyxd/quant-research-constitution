# Quantitative Research Project Constitution (量化研发项目总宪法)

> **Core Philosophy**: **"Trust No Agent, Verify Every Hash."** (不信任任何 Agent，验证每一个哈希。)  
> In high-precision quantitative trading (such as NautilusTrader backtesting & ML retraining), AI agents are probabilistic generators prone to hallucinations, phantom fills, and un-reproducible drift. This Constitution establishes an immutable **Truth Layer** that separates deterministic execution from AI proposals.

---

## 目录
1. [系统三层架构原则 (Three-Tier Architecture)](#一-系统三层架构原则-three-tier-architecture)
2. [数据不可变与哈希校验契约 (Data Immutability & Hashing)](#二-数据不可变与哈希校验契约-data-immutability--hashing)
3. [黄金测试强制契约 (Golden Test Mandate)](#三-黄金测试强制契约-golden-test-mandate)
4. [智能体分工与反幻觉规约 (Agent Roles & Anti-Hallucination)](#四-智能体分工与反幻觉规约-agent-roles--anti-hallucination)
5. [因果律与反前视偏差铁律 (Anti Look-Ahead Bias & Strict Causality)](#五-因果律与反前视偏差铁律-anti-look-ahead-bias--strict-causality)
6. [撮合成交真实性与虚假流水审计 (True Fill Accounting & Anti-Phantom Fills)](#六-撮合成交真实性与虚假流水审计-true-fill-accounting--anti-phantom-fills)
7. [动态名义杠杆与资本规模适配铁律 (Dynamic Capital & Margin Scaling)](#七-动态名义杠杆与资本规模适配铁律-dynamic-capital--margin-scaling)
8. [闸门层执行审查标准与反过拟合判决 (Gatekeeper Audit & Anti-Overfitting Protocol)](#八-闸门层执行审查标准与反过拟合判决-gatekeeper-audit--anti-overfitting-protocol)

---

## 一、 系统三层架构原则 (Three-Tier Architecture)

1. **Truth Layer (真相层 - 确定性核心)**:
   - 包含：固定数据集 (Parquet Catalog)、数据哈希验证器、特征计算纯函数、固定种子回测引擎 (BacktestNode)、黄金测试断言 (Golden Tests)。
   - 规则：**任何 LLM/Agent 绝对禁止直接修改真相层代码或数据**。真相层的变动必须经过双人或双模型验证 + 自动化哈希对比。
2. **Proposal Layer (提议层 - AI 代理)**:
   - 角色：Proposal Agent / AlphaGPT / Qlib / RD-Agent / Claude / Grok。
   - 规则：AI 只能生成策略想法、代码草稿、特征公式、配置文件建议，输出 `git diff` 形式的提议。
3. **Gate Layer (闸门层 - 最终仲裁)**:
   - 角色：人类研究员 + Verifier Agent (验证者工作组)。
   - 规则：只有当提议通过静态检查、因果性代码审计、数据哈希校验、以及最关键的**黄金测试 (Golden Test 100% 吻合)** 后，方可合并至主分支。

---

## 二、 数据不可变与哈希校验契约 (Data Immutability & Hashing)

- **Catalog 版本化**：所有回测与 ML 训练数据（如 BTC 2026-01 30m OHLCV、L2 订单簿切片）必须存入只读目录。
- **Merkle / Catalog Hash**：每次实验开始前，`compute_data_hash.py` 会计算 catalog 的 SHA-256 合集哈希，必须与 `tests/golden/data_hash.txt` 完全一致，否则回测引擎直接触发安全熔断并终止。
- **时间戳与对齐**：强制左开盘 (`Left-Open`) / 右收盘 (`Right-Close`) 因果律隔离，杜绝前视偏差 (Lookahead Bias)。

---

## 三、 黄金测试强制契约 (Golden Test Mandate)

本项目包含针对每个核心环节的最小黄金测试集 (`tests/golden/`)：
1. **特征计算黄金测试 (`run_golden_features.py`)**：对固定小样本喂入，验证 OFI、CMF、ATR 及趋势特征输出在绝对容差 ($10^{-8}$) 与相对容差 ($10^{-5}$) 内完全一致。
2. **回测指标黄金测试 (`run_golden_backtest.py`)**：对固定短周期跑完整策略，验证最终 PnL、胜率、交易次数与 `expected_metrics.json` 逐字对齐。

---

## 四、 智能体分工与反幻觉规约 (Agent Roles & Anti-Hallucination)

- **Proposal Agent (提议 Agent)**：只准提议，不准宣布“已完成”，不准私自编写未经验收的仿真撮合器并宣称高收益。
- **Verifier Agent (验证 Agent)**：专门负责“找茬”，检查是否有未来函数、硬编码、未声明的数据，运行黄金测试。**通过标准是找出不一致与漏洞，而不是帮忙圆谎**。
- **Human Gate (人类闸门)**：最终签字确认。

---

## 五、 因果律与反前视偏差铁律 (Anti Look-Ahead Bias & Strict Causality)

在微观结构与高频网格做市回测中，**99% 的暴利神话源于前视未来函数**。闸门层设立三条不可跨越的因果红线：

### 5.1 严禁“同 Bar 逆向穿越撮合”（Same-Bar Price-Level Violation）
- **违规特征**：在第 $i$ 根 1 分钟 Bar 中，使用该 Bar 的收盘价 $C_i$ 计算做市保留价格与买卖报价，却在同一根 Bar 内部判定 $Low_i \le P_{\text{bid}}$ 或 $High_i \ge P_{\text{ask}}$ 发生撮合。
- **物理违规实质**：在实盘中，$C_i$ 只有在该分钟第 59.999 秒才被观测，不能倒流回去匹配第 10 秒发生过的最低价 $Low_i$。
- **宪法强制规范**：
  $$\text{Quote}_t = f(\mathcal{I}_{t-1}) \quad \text{或} \quad \text{Quote}_t = f(\text{Open}_t)$$
  在第 $i$ 根 Bar 结束时计算的报价，**最早只能在第 $i+1$ 根 Bar 挂单并接受撮合**；在逐笔 Tick 订单簿中，必须在 $t$ 时刻报价，由 $t+1, t+2, \dots$ 的市场主动订单流撮合。

### 5.2 严禁“同 Bar 双向高抛低吸完美闭环”
- **违规特征**：在一根 1 分钟 K 线内，由于 $Low_i \le P_{\text{bid}}$ 且 $High_i \ge P_{\text{ask}}$ 均满足，代码无条件判定买单与卖单在同一分钟双双成交，无风险空手套白狼收割完整买卖振幅。
- **物理违规实质**：单根 Bar 内缺少时间优先顺序（先冲高再破位大跌时，高位卖单根本未被挂出，反而买单在暴跌中被动接盘）。在无逐笔 L2/Tick 数据下，严禁假设同 Bar 双向完美撮合。

### 5.3 彻底封杀向后填充未来函数
- 严禁在时序特征中调用 `.bfill()` 或 `fillna(method='bfill')`，这会导致前值被未来的均值或极值填充。
- 滚动特征必须限定 `min_periods=1`，且仅允许使用 `.shift(1)` 后的历史切片。

---

## 六、 撮合成交真实性与虚假流水审计 (True Fill Accounting & Anti-Phantom Fills)

### 6.1 报单成功绝不等于撮合成交（Anti-Phantom Fills）
- **血泪教训**：历史系统中曾因将 API 报单响应 `code == "0"` 误计为 `matched_trades += 1`，虚增出 7.8 万笔不存在的假流水。
- **真理口径**：**成交判定必须且仅能以成交账单为准**。仅有交易所私有 WebSocket 的 `orders` 频道推送 `state in ["filled", "partially_filled"]` 且 `fillSz > 0`，或者 `/api/v5/account/bills` 分页流水，才是真实撮合的凭证。

### 6.2 强制严格 Post-Only（只做 Maker，杜绝 Taker 费率毁灭）
- 在加密永续做市中，普通限价单在极端微观跳价中极易与盘口对手单直接交叉，被交易所按 0.05% Taker 吃单费率扣除，造成不可逆的巨额亏损（实盘数据证明 Taker 费用占旧版总亏损的 72.6%）。
- **宪法强制规范**：所有做市报文必须显式指定 `ord_type = "post_only"`，双边总价差强制满足：
  $$\text{Spread}_{\text{total}} \ge 2 \times \text{Fee}_{\text{Maker}} + \text{Buffer} \quad (\ge 8.0 \sim 12.0\text{ bps})$$

### 6.3 队列优先权感知与保护（Queue Priority Preservation）
- 严禁每个循环无脑“全撤全挂”。频繁撤单重挂会导致订单永远处于 FIFO 撮合队列的最末端，彻底丧失 Maker 被动成交权。
- 必须设定微观价格容差（如 BTC $\pm 1.5\text{ U}$），在公允价微幅波动时执行 `QUEUE_HOLD` 保持排队优势。

---

## 七、 动态名义杠杆与资本规模适配铁律 (Dynamic Capital & Margin Scaling)

### 7.1 严禁机构级参数在微账户上混用
- 10 万 USDT 账户训练的风险厌恶参数（如 $\gamma = 0.0451$）在 30 USDT 实盘微账户上会导致保留价格倾斜力度严重不足，单位库存引起的价格调整微乎其微，引发单边持续加仓直至耗尽保证金（实盘保证金占用达 99.1% 被交易所拒单）。
- 微账户必须配置高风险厌恶（$\gamma = 0.35 \sim 3.00$），强化库存惩罚倾斜力度。

### 7.2 严禁固定合约张数导致的被动名义敞口膨胀
- 严禁在长周期回测中使用静态固定合约张数（如固定每次 0.5 SOL、20 SUI）。
- 当资产价格因大牛市暴涨 3~5 倍时，固定合约张数会导致单笔名义开仓金额与保证金占用率被动翻倍，直接击穿 30U 微账户的承载极限（保证金占用从 40% 爆增至 120% 穿仓）。
- **宪法强制规范**：生产与回测必须接入 `as_dynamic_risk.py` 动态折算：
  $$\text{LotSize}(t) = \text{round}\left(\frac{\text{TargetNotionalUSD}}{P_{\text{mid}}(t)}, \; \text{Precision}\right)$$
  将初始保证金占用率严格锁死在 $\le 15\%$，最大净持仓锁死在 $\le 45\%$，**永久保留 $\ge 55\%$ 的流动性安全垫**。

---

## 八、 闸门层执行审查标准与反过拟合判决 (Gatekeeper Audit & Anti-Overfitting Protocol)

任何 Agent 提交的策略报告进入主分支前，Verifier Agent 必须执行以下四项判决检查：

1. **异常暴利死刑判决（Unrealistic Gain Inquest）**：
   - 凡是在 1m K 线上报告单年收益超过 1,000% 且胜率超过 75% 的网格做市策略，**一律预设存在前视未来函数**。必须穿透其撮合逻辑，核查是否存在“同 Bar 逆向穿越”或“同 Bar 双边套利”。
2. **真实订单簿全量压力测试（L2 Tick Benchmark）**：
   - 必须通过 `/home/da/桌面/database/` 内真实的 L2 订单簿切片（如 BTC 322,674 Ticks 暴跌压力测试集）进行**逐笔事件驱动回测**。在单日大盘单边暴跌 -3.54% 下，策略必须证明其能够保全 90% 以上本金。
3. **Credal Transformer 认知不确定性过滤（Anti-Hallucination Audit）**：
   - 模型推断中必须输出狄利克雷认知空虚度 $u_t$。在面对未见过的极端单边行情（OOD 数据）时，模型必须主动收窄报价或切断同侧挂单，拒绝 Softmax 虚假确定性。
4. **全量手续费与滑点穿透核算**：
   - 必须将 Maker 0.02% / Taker 0.05% 费率全额计入杠杆名义成交额，严格核算双边摩擦成本。

---
*Immutable Truth Layer. Verified and Certified under Quant Research Constitution.*
