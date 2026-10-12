# americaStocks 历史项目全景梳理报告
> 整理归档路径：`/home/da/桌面/11/AMERICA_STOCKS_ORIGINAL_AND_FINAL_DELIVERY.md`  
> 日期：2026-10-12

---

## 一、 项目最初提供的原始文件清单与架构

在项目初始阶段（Git 初始提交 `971afae`），用户/仓库提供的完整文件结构如下：

```
americaStocks/
├── .agents/
│   └── skills/
│       ├── anti-overfitting-auditor/
│       │   └── SKILL.md
│       ├── quant-env-doctor/
│       │   └── SKILL.md
│       ├── smc-strategy-adapter/
│       │   └── SKILL.md
│       └── walk-forward-backtest/
│           └── SKILL.md
├── docs/
│   └── workflow/
│       └── QUANT_RESEARCH_WORKFLOW.md
├── results/
│   ├── batch_test/
│   │   └── summary.csv
│   ├── batch_w1/
│   │   └── summary.csv
│   ├── batch_w2/
│   │   └── summary.csv
│   ├── batch_w3/
│   │   └── summary.csv
│   ├── batch_w4/
│   │   └── summary.csv
│   ├── portfolio/
│   │   ├── HIGH_FREQUENCY_SMC_QLIB_REPORT.md
│   │   ├── monte_carlo_results.json
│   │   └── portfolio_summary.csv
│   └── unified/
│       ├── FINAL_BACKTEST_REPORT.md
│       └── all_backtest_summary.csv
├── smc_optimized/
│   ├── README.md
│   ├── v1_internal_factors/
│   │   ├── __init__.py
│   │   ├── indicators.py
│   │   └── smc_strategy.py
│   ├── v2_volatility_regime/
│   │   ├── __init__.py
│   │   ├── indicators.py
│   │   └── smc_strategy.py
│   └── v3_trend_strength/
│       ├── __init__.py
│       ├── indicators.py
│       └── smc_strategy.py
├── .gitignore
├── README.md
├── backtest_core.py
├── batch_runner.py
├── download_hf_data.py
├── generate_high_freq_report.py
├── generate_report.py
├── monte_carlo_analysis.py
├── run_all_backtests.py
├── smc_hf_alpha_engine.py
├── smc_hf_alpha_engine_v2.py
├── smc_hf_alpha_engine_v3.py
├── smc_hf_alpha_engine_v4.py
├── smc_hf_alpha_engine_v5.py
├── smc_hf_alpha_engine_v6.py
├── smc_portfolio_engine.py
├── smc_portfolio_engine_compound.py
├── smc_portfolio_engine_fixed.py
├── smc_portfolio_engine_full.py
├── test_compare_engines.py
├── test_hf_single.py
├── test_hf_single_v2.py
├── test_hf_single_v3.py
├── test_hf_single_v4.py
├── test_hf_single_v5.py
├── test_nautilus_conversion.py
├── test_nautilus_run.py
├── test_nautilus_run2.py
├── test_nautilus_run3.py
├── test_walk_forward_single.py
└── verify_final_completion.py
```

### 原始文件关键模块说明
1. **策略内核原型**: `smc_optimized/` 目录（v1 内部因子、v2 波动率状态滤波、v3 趋势强度）以及 `smc_hf_alpha_engine_v1~v6.py`。
2. **多资产组合与复利回测脚本**: `smc_portfolio_engine.py`、`smc_portfolio_engine_compound.py`。
3. **多智能体规范定义**: `.agents/skills/` 与 `docs/workflow/QUANT_RESEARCH_WORKFLOW.md`。

---

## 二、 最终策略产出文件

经过多轮 Herdr 多智能体 Swarm 迭代、NautilusTrader 纳秒级撮合重构与 OKX 异步订单状态机修复，项目的核心最终策略产出文件如下：

### 1. 核心回测与框架标准策略本体
* **文件路径**: `/home/da/桌面/americaStocks/src/nautilus_smc_strategy.py`
* **类名**: `NautilusSMCHighFreqStrategy`
* **说明**:
  - 原生适配 NautilusTrader (v1.227.0) 事件循环体系；
  - 彻底修复“限价单发出假定立即成交”的幽灵持仓（Ghost Position）Bug，改由 `on_order_filled` 状态回调驱动；
  - 实现基于 ATR 的动态止损与“1:1 风险回报平半仓保本、2:1 跑满主升浪”出场逻辑；
  - 核心微观结构因子提取器对应配套文件：`/home/da/桌面/americaStocks/src/qlib_smc_alpha.py`。

### 2. OKX 实盘/模拟盘部署交付文件
* **生产路径**: `/home/da/桌面/deploy/nautilus_okx_smc/live_smc_strategy.py`（以及入口脚本 `live_okx_smc.py`）
* **策略归档仓库备份**: `/home/da/桌面/strategy_repo/001_smc_matrix_20260930/smc_live_trader.py`
* **说明**:
  - 接入 OKX DEMO/实盘 WebSocket 行情与账户推送；
  - 修正了导致多空证据冲突值 $C$ 恒等于 1.0 的门控误杀 Bug。

---

## 三、 核心回测研报文件

项目最终沉淀的核心回测与反过拟合审计报告如下：

### 1. 生产级综合终审报告 (最权威总报告)
* **文件路径**:
  - `/home/da/桌面/americaStocks/results/PRODUCTION_HIGH_FREQ_CRYPTO_SMC_RESEARCH_REPORT.md`
  - *(镜像副本)*: `/home/da/桌面/americaStocks/docs/research/PRODUCTION_HIGH_FREQ_CRYPTO_SMC_RESEARCH_REPORT.md`
* **报告级别**: `v5.0-PRODUCTION`
* **内容涵盖**:
  - CIRO 首席投资总监阶段性裁定；
  - 4 币种组合（BTC, ETH, SOL, BNB）高频交易频次检验（单标的 1~8 笔/天，聚合 12~26 笔/天）；
  - 全摩擦检验（Taker/Maker 费用 + 滑点 + 悲观同 Bar 触价止损优先原则）；
  - Credal Transformer 狄利克雷不确定度 $u > 0.35$ 拒单实证与蒙特卡洛压力测试。

### 2. 真实性复查与红队审计报告
* **文件路径**: `/home/da/桌面/americaStocks/results/trade_verification_audit_report.md`
* **说明**: 针对历史回测中“312 笔固定假数据”与前瞻偏差进行的白帽打假审查和归因报告。

### 3. 错误细节剖析与下一代工作流规范
* **文件路径**: `/home/da/桌面/americaStocks/results/POST_AUDIT_ERROR_ANALYSIS_AND_NEXT_GEN_WORKFLOW.md`
