# Quantitative Research Project Constitution (量化研发项目总宪法)

> **Core Philosophy**: **"Trust No Agent, Verify Every Hash."** (不信任任何 Agent，验证每一个哈希。)
> In high-precision quantitative trading (such as NautilusTrader backtesting & ML retraining), AI agents are probabilistic generators prone to hallucinations and un-reproducible drift. This Constitution establishes an immutable **Truth Layer** that separates deterministic execution from AI proposals.

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
   - 规则：只有当提议通过静态检查、单元测试、数据哈希校验、以及最关键的**黄金测试 (Golden Test 100% 吻合)** 后，方可合并至主分支。

---

## 二、 数据不可变与哈希校验契约 (Data Immutability & Hashing)

- **Catalog 版本化**：所有回测与 ML 训练数据（如 BTC 2026-01 30m OHLCV）必须存入只读目录。
- **Merkle / Catalog Hash**：每次实验开始前，`compute_data_hash.py` 会计算 catalog 的 SHA-256 合集哈希，必须与 `tests/golden/data_hash.txt` 完全一致，否则回测引擎直接触发安全熔断并终止。
- **时间戳与对齐**：强制左开盘 (`Left-Open`) / 右收盘 (`Right-Close`) 因果律隔离，杜绝前视偏差 (Lookahead Bias)。

---

## 三、 黄金测试强制契约 (Golden Test Mandate)

本项目包含针对每个核心环节的最小黄金测试集 (`tests/golden/`)：
1. **特征计算黄金测试 (`run_golden_features.py`)**：对固定 BTC 2026-01 小样本喂入，验证 OFI、CMF、ATR 及趋势特征输出在绝对容差 ($1e-5$) 内完全一致。
2. **回测指标黄金测试 (`run_golden_backtest.py`)**：对固定短周期跑完整策略，验证最终 PnL、胜率、交易次数与 `expected_metrics.json` 逐字对齐。

---

## 四、 智能体分工与反幻觉规约 (Agent Roles & Anti-Hallucination)

- **Proposal Agent (提议 Agent)**：只准提议，不准宣布“已完成”。
- **Verifier Agent (验证 Agent)**：专门负责“找茬”，检查是否有未来函数、硬编码、未声明的数据，运行黄金测试。你的通过标准是找出不一致，而不是帮忙圆谎。
- **Human Gate (人类闸门)**：最终签字确认。
