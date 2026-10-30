# Quantitative Research Project Constitution (量化研发项目总宪法)

> **Core Philosophy**: **"Trust No Agent, Verify Every Hash."** (不信任任何 Agent，验证每一个哈希。)  
> In high-precision quantitative trading (such as NautilusTrader backtesting & ML retraining), AI agents are probabilistic generators prone to hallucinations, phantom fills, and un-reproducible drift. This Constitution establishes an immutable **Truth Layer** that separates deterministic execution from AI proposals.

---

## 🏛️ 宪法法典体系与操作规范

本仓库为所有量化投研策略、特征工程、回测引擎与实盘部署设立不可逾越的法定基准与闸门审查规范：

1. **[核心总宪法 (CONSTITUTION.md)](CONSTITUTION/CONSTITUTION.md)**：
   - 系统三层架构原则 (Truth / Proposal / Gate Layer)
   - 数据不可变契约与 Merkle/Catalog SHA-256 哈希校验
   - 黄金测试（Golden Test）强制契约
   - 智能体分工与反幻觉规约
   - **因果律与反前视偏差铁律** (Anti Look-Ahead Bias)
   - **撮合成交真实性与虚假流水审计** (Anti-Phantom Fills & Post-Only)
   - **动态名义杠杆与资本规模适配铁律** (Margin Scaling & Buffer)
   - **闸门层执行审查标准与反过拟合判决** (Credal Transformer Audit)

2. **[反前视偏差与微观结构撮合审计操作手册 (ANTI_LOOKAHEAD_AUDIT_MANUAL.md)](CONSTITUTION/ANTI_LOOKAHEAD_AUDIT_MANUAL.md)**：
   - 同 Bar 逆向穿越撮合（Same-Bar Price-Level Violation）的查验与代码排查
   - 同 Bar 双边套利永动机的破案机理
   - 4 步反前视审查法与因果撮合状态机代码模板

3. **[真实量化研发血泪案例复盘与防重犯备忘录 (REAL_CASE_STUDIES_AND_LESSONS.md)](CONSTITUTION/REAL_CASE_STUDIES_AND_LESSONS.md)**：
   - 案例一：子 Agent 虚构万倍超额收益幻觉案（DOGE +16,170% / SUI +26,407% 泡沫破灭）
   - 案例二：实盘 51 小时对账真实案（dayuan 30.9% Taker 吃单手续费毁灭 vs accountbot3 99.5% Maker 救赎）
   - 案例三：7.8 万笔虚假流水幽灵案（报单成功误当撮合成交）
   - 案例四：牛市资产暴涨导致固定合约张数保证金被动击穿爆仓案

---

## 🧪 黄金测试运行指南 (Running Golden Tests)

任何策略修改与特征调整，必须 100% 跑通以下黄金测试断言：

```bash
# 1. 验证特征计算纯函数无漂移 (绝对容差 1e-8, 相对容差 1e-5)
python3 scripts/run_golden_features.py

# 2. 验证确定性回测指标与基准逐字对齐
python3 scripts/run_golden_backtest.py

# 3. 验证数据目录 SHA-256 完整性哈希
python3 scripts/compute_data_hash.py
```

---

## 🛡️ 智能体协作守则 (Agent Directives)

- **Proposal Agent (提议 Agent)**：仅能生成策略想法、特征公式与参数建议，严禁私自编写简陋撮合器宣称高收益；
- **Verifier Agent (验证 Agent)**：专门负责“找茬”，检查未来函数、硬编码、同 Bar 撮合、名义敞口膨胀，运行黄金测试；
- **Human Gate (人类闸门)**：最终签字仲裁，未获哈希认证与因果核实的代码严禁合入生产主分支。
