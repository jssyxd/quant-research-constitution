# 工作流案例：多资产 3H 线内即时成交重算与微观摩擦投研 SOP

> **案例标识**: `CASE-003-INTRABAR-RECALC-SOP`  
> **涉及标的**: 黄金 (GLD)、白银 (SLV)、BTC、纳斯达克 100 期货 (NQ)、标普 500 期货 (ES)  
> **涉及周期**: 15m / 1h / 2h / 3h (主力周期) / 4h  
> **核心命题**: 解构传统中长周期回测的“长达数小时风控盲区”，确立“没有线内即时成交与重算挂单，策略在物理上不成立”的铁律，沉淀多 Agent 分工、数据源审计标准与悲观撮合验证流程。

---

## 一、 核心投研公理与微观问题解构

### 1.1 传统 Bar-Close 回测的“信息延迟黑洞”
在多资产 3H 策略中：
- 策略于 12:00:00 挂出限价买单；
- 行情在 12:15:00 发生微观脉冲回踩并成交；
- **错误回测引擎的致命假设**：认为策略必须傻等剩余的 2 小时 45 分钟直到 15:00:00 柱线正式收盘，才能读取成交状态、才能计算止盈止损点位；
- **实盘灾难**：在这 2 小时 45 分钟里，市场可能已发生千点单边暴跌，策略由于没有任何保护单排队，直接导致穿仓。

### 1.2 线内即时重算挂单（`on_order_filled` / `calc_on_order_fills = true`）的核心机制
- 撮合引擎在订单触碰微秒内派发成交事件，立即打断系统等待；
- 策略瞬间访问真实执行价格 `event.last_px` 与已扣手续费；
- **在同一微观时间片内，立即以真实成交价为锚点，向交易所盘口挂出伴随的 OCO（One-Cancels-the-Other）止盈限价单与止损市价单**：
  $$	ext{Target TP} = P_{	ext{executed}} + 2.4 	imes 	ext{ATR}_{14}$$
  $$	ext{Stop Loss} = P_{	ext{executed}} - 1.2 	imes 	ext{ATR}_{14}$$
- 这一机制将风控盲区从 179 分钟彻底压缩为 0，单笔最大亏损被严格锁死在账户风险预算（1.0%）内，策略的正期望值（Positive EV）才具有物理现实性！

---

## 二、 多 Agent 标准化协作流图与准入验收标准 (Multi-Agent Workflow SOP)

```mermaid
flowchart TD
    classDef orch fill:#1e1e2e,stroke:#cba6f7,stroke-width:2px,color:#cdd6f4;
    classDef dataAgent fill:#181825,stroke:#89b4fa,stroke-width:2px,color:#cdd6f4;
    classDef devAgent fill:#181825,stroke:#a6e3a1,stroke-width:2px,color:#cdd6f4;
    classDef auditAgent fill:#181825,stroke:#f38ba8,stroke-width:2px,color:#cdd6f4;
    classDef deployAgent fill:#181825,stroke:#fab387,stroke-width:2px,color:#cdd6f4;
    classDef gate fill:#313244,stroke:#f9e2af,stroke-width:2px,stroke-dasharray: 5 5,color:#f9e2af;

    ORCH[<b>Lead Orchestrator (量化架构总控)</b>]:::orch

    subgraph S1 [阶段一: 湖仓治理与高精度数据对齐]
        AG_DATA[<b>Agent 1: Data Lake Specialist</b>]:::dataAgent
        GATE1{<b>Gate 1: 数据保真性验收标准</b><br>1. 1m 底层纳秒时序单调递增<br>2. 聚合 15m~4h 严格 closed=left, label=left<br>3. 0 前视偏差，0 伪造鬼影柱}:::gate
        AG_DATA --> GATE1
    end

    subgraph S2 [阶段二: 核心引擎与线内即时重算研发]
        AG_DEV[<b>Agent 2: Microstructure Developer</b>]:::devAgent
        GATE2{<b>Gate 2: 执行真实性验收标准</b><br>1. 必须基于 1m 微观切片进行线内 Limit 判定<br>2. 触碰瞬间必须立即触发 on_order_filled 打断等待<br>3. 止盈止损 Bracket 必须以真实成交价 last_px 锚定<br>4. 严防状态追溯污染与重复发单}:::gate
        GATE1 -->|通过合规数据| AG_DEV
        AG_DEV --> GATE2
    end

    subgraph S3 [阶段三: 悲观碰撞与 25 组参数矩阵量化审计]
        AG_AUDIT[<b>Agent 3: Forensic Auditor</b>]:::auditAgent
        GATE3{<b>Gate 3: 投研宪法悲观合规验收标准</b><br>1. 同柱触碰强制执行 COLLISION_STOP_LOSS<br>2. 双边 3 bps 佣金 + 3 bps 滑点硬扣除<br>3. 3H 核心周期 Sharpe > 3.0 且 MaxDD < 15%<br>4. 12 根 K 线超时强制 Time-Stop 清算}:::gate
        GATE2 -->|通过合规引擎| AG_AUDIT
        AG_AUDIT --> GATE3
    end

    subgraph S4 [阶段四: 工业级容器化封装与投研宪法入库]
        AG_DEPLOY[<b>Agent 4: Production MLOps Guardian</b>]:::deployAgent
        GATE4{<b>Gate 4: 投研宪法 CI 终审与入库</b><br>1. anti_p_hacking 扫描 100% CLEAN<br>2. 零未来函数与硬编码指标钳制<br>3. 成功 Push 至 GitHub main 分支}:::gate
        GATE3 -->|通过全量矩阵| AG_DEPLOY
        AG_DEPLOY --> GATE4
    end

    ORCH --> S1
    ORCH --> S2
    ORCH --> S3
    ORCH --> S4
    GATE4 --> PROD[(<b>GitHub 生产仓库沉淀</b>)]
```

---

## 三、 案例回测全量矩阵审计结果 (W:\database 湖仓实测)

全矩阵覆盖 5 大标的 x 5 周期，扣除双边 3 bps 佣金与 3 bps 滑点：

| 标的资产 | 15m 夏普 (胜率) | 1h 夏普 (胜率) | 2h 夏普 (胜率) | **3h 主力周期 (夏普 / 胜率 / 最大回撤)** | 4h 夏普 (胜率) |
|---|:---:|:---:|:---:|:---:|:---:|
| **BTC** | 15.64 (61.5%) | 7.06 (55.8%) | 5.29 (54.9%) | **4.03 (53.1% / MaxDD: 7.39%)** | 3.76 (55.6%) |
| **黄金 (GLD)** | 10.97 (72.9%) | 7.62 (65.1%) | 5.03 (61.0%) | **4.16 (59.5% / MaxDD: 6.14%)** | 3.95 (58.2%) |
| **白银 (SLV)** | 11.51 (64.4%) | 5.46 (54.5%) | 3.90 (53.0%) | **3.03 (52.9% / MaxDD: 12.99%)**| 3.12 (53.0%) |
| **NQ (纳指期货)**| 3.83 (67.9%) | 1.86 (63.5%) | 1.24 (60.4%) | **1.17 (62.1% / MaxDD: 3.17%)** | 0.97 (59.3%) |
| **ES (标普期货)**| 2.86 (73.4%) | 1.61 (58.8%) | 1.62 (64.1%) | **0.97 (60.9% / MaxDD: 3.26%)** | 1.00 (60.9%) |

> **出仓严格归因 (16,737 笔交易)**：
> - 止盈达成（`TAKE_PROFIT`）：7,356 笔 (44.0%)；
> - 止损触发（`STOP_LOSS`）：5,696 笔 (34.0%)；
> - 超时硬清算（`TIME_STOP`）：3,683 笔 (22.0%)；
> - 极端同柱悲观碰撞（`COLLISION_STOP_LOSS`）：2 笔 (悲观止损执行率 100%)。

---

## 四、 本 SOP 交付物目录规范

- `code/multi_asset_loader.py`：标准湖仓数据清洗与无未来函数重采样管线；
- `code/intrabar_engine.py`：线内即时重算撮合状态机与悲观碰撞仲裁核心引擎；
- `code/nautilus_strategy.py`：NautilusTrader 事件驱动标准规范；
- `code/run_matrix_backtest.py`：25 组参数矩阵批量压力测试脚本；
- `reports/intrabar_matrix_summary.csv`：25 组全矩阵汇总表；
- `reports/JANE_STREET_MATRIX_REPORT.md`：法医级量化审计底稿。
