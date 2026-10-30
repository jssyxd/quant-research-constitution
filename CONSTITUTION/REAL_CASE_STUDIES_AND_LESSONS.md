# 真实量化研发血泪案例复盘与防重犯备忘录
(Real-World Quantitative Case Studies & Anti-Recurrence Postmortem)

> **宪法判词**：“历史不会重复自己，但总是押着相同的韵脚。在真金白银的量化市场中，任何微小的数理妥协，都必将以账户穿仓为终局。”

---

## 案例一：子 Agent 虚构万倍超额收益幻觉案 (The +16,000% Fantasy Fill Case)

### 1. 案情现象 (Observed Anomaly)
在 Strategy 012 多 Agent 并行回测任务中，负责山寨币微观做市的子 Agent（`engine-doge-sui`）交付了一份令人瞠目结舌的报告（`reports/doge_sui_backtest_report.json`）：
- **DOGE 回测宣称**：初始本金 30 USDT，在 21 个月内飙升至 4,881 USDT，累计收益率 **+16,170.87%**，夏普比率 5.33，最大回撤仅 0.76%；
- **SUI 回测宣称**：初始本金 30 USDT，在 21 个月内飙升至 7,952 USDT，累计收益率 **+26,407.31%**，夏普比率 5.18，最大回撤仅 0.77%。

### 2. 闸门穿透调查 (Forensic Investigation)
Verifier Agent 调取 `run_doge_sui_backtest.py` 核心 Numba 循环进行代码审计，发现了两大逻辑造假：
1. **未来收盘价逆流撮合**：代码直接提取当前 1m Bar 的 `Close[i]` 计算报价 `bid_p`，却立即去匹配当前 Bar 的 `Low[i]`，相当于在得知一分钟后的最终收盘价后，回到一分钟前去以最低点成交；
2. **同 Bar 双边套利永动机**：在 1 分钟震荡中，假设做市商同时以 $Low$ 买了、又以 $High$ 卖了，完全无视价格单边波动的物理先后路径。

### 3. 真相层裁判结果 (Truth Layer Verdict)
我们将同套参数置入 `/home/da/桌面/database/` 内真实的 **24 小时 20 档微秒级订单簿全量数据集**（`BTCUSDT_depth20_20260326_governed.parquet`，322,674 Ticks 暴跌 -2,522 美元）中进行绝对因果回测：
- **真实表现**：在单边大跌下，策略不仅没有产生暴利，反而面临剧烈的逆向选择冲击。更改后的 V2 架构凭借 ADX 趋势阻断与 OBI 毒性熔断，净盈亏为 **-1.3974 USDT（回撤 -4.66%）**，保全了 95.34% 的本金。
- **判决**：子 Agent 的虚假高收益完全是前视未来函数制造的数字泡影，全盘废除虚假指标，将真实因果结果归档 Truth Layer。

---

## 案例二：实盘 51 小时对账真实案——Taker 费率毁灭与 Post-Only 救赎 (The 30.9% Taker Bloodbath)

### 1. 案情现象 (Observed Anomaly)
远端 VPS（`155.254.60.38`）同时运行了两个 3x 杠杆的做市容器，在分页拉取全量真实流水账单（`GET /api/v5/account/bills`）后，呈现两极分化：
- **子账户 `dayuan` (运行 40.96 小时)**：实际成交 2,123 笔，名义成交量 $16,839 USDT，但实现盈亏为 **-1.8578 USDT**，**手续费被扣除了 4.9177 USDT**，账户权益从 34.95 U 缩水至 28.25 U；
- **子账户 `accountbot3` (运行 10.38 小时)**：实际成交 208 笔，名义成交量 $1,657 USDT，实现盈亏仅微损 **-0.0943 USDT**，**手续费仅 0.3269 USDT**，账户权益保持在 29.58 U。

### 2. 根因剖析 (Root Cause Analysis)
- `dayuan` 跑的是旧版运行器，报单采用了普通限价单（`ord_type="limit"`）。在行情剧烈跳空时，挂出的买卖单直接与对手盘发生交叉撮合，导致 **30.9% 的订单滑向了 Taker 吃单（657 笔）**；
- 交易所对 Taker 征收 0.05% 的惩罚性费率。在 3x 杠杆放大下，手续费直接占了 `dayuan` 总亏损的 **72.6%**！策略沦为纯给交易所打工。
- `accountbot3` 运行的是整改后的 V2 代码，全面强制 `ord_type="post_only"`，若穿透盘口则由交易所直接取消，**彻底消灭 Taker（0.0%）**，Maker 比例达到 99.5%，手续费支出暴降 93.3%。

### 3. 铁律固化 (Codified Rule)
- 做市商绝不交纳 Taker 惩罚费！所有报单必须强制 `post_only`；
- 双边最优总价差必须覆盖双边手续费的 2 倍以上：$\text{Spread}_{\text{total}} \ge 2 \times \text{Fee}_{\text{Maker}} + \text{Buffer} \ge 8.0 \sim 12.0\text{ bps}$。

---

## 案例三：7.8 万笔虚假流水幽灵案 (The Phantom Trade Bug)

### 1. 案情现象 (Observed Anomaly)
早期策略在回测与实盘模拟中汇报了 78,000+ 笔成交，统计出高达数百万美元的虚假名义流水。但在审查交易所真实账单时，实际撮合笔数寥寥无几。

### 2. 根因剖析 (Root Cause Analysis)
代码在调用交易所下单接口后，直接以响应 `response.get("code") == "0"` 判定为成交并自增流水计数器：
```python
# 致命错误代码
res = client.place_order(...)
if res.get("code") == "0":
    matched_trades += 1  # 错误：code==0 仅代表订单被交易所系统成功接收并挂上订单簿！
```
2 秒后，下一轮主循环执行全额撤单重挂，未撮合的挂单被全部撤销，导致统计数据产生了海量的“幽灵交易”。

### 3. 铁律固化 (Codified Rule)
- 严禁将订单确认与成交记账混为一谈；
- 只有交易所私有 WebSocket 的 `orders` 频道推送 `state == "filled"` 且 `fillSz > 0`，或者 REST 对账流水 `bills`，才是法定成交证据。

---

## 案例四：牛市资产暴涨导致固定合约张数爆仓案 (The Margin Inflation Trap)

### 1. 案情现象 (Observed Anomaly)
在 SUI 与 SOL 长周期回测中，策略初期设定了固定合约张数（如固定每次开仓 20 SUI、0.5 SOL）。
- 2025 年初，SUI 价格为 $1.50 USDT：单笔 20 SUI 名义价值仅为 $30.00 USDT，在 3x 杠杆下占用保证金 $10.00 USDT（占 30U 本金的 33.3%，尚在安全区间）；
- 2025 年下半年，SUI 暴涨至 $5.37 USDT：单笔 20 SUI 的名义价值暴增至 **$107.40 USDT**，占用保证金高达 **$35.80 USDT（占用率达 119.3%！）**；
- 单笔开仓即直接触发交易所爆仓线，系统在资产大牛市中不仅没赚钱，反而因名义敞口被动膨胀而穿仓。

### 2. 铁律固化 (Codified Rule)
- 严禁在波动的加密市场中使用固定的标的物张数；
- 必须基于目标名义美元价值动态折算开仓尺寸：
  $$\text{LotSize}(t) = \text{round}\left(\frac{\text{TargetNotionalUSD}}{P_{\text{mid}}(t)}, \; \text{Precision}\right)$$
  将单笔名义开仓严格锁定在 $\le 10\text{ USDT}$（保证金占用 $\le 3.33\text{ USDT}$），保证无论币价涨跌，初始保证金占用率永远 $\le 15\%$，净持仓占用永远 $\le 45\%$，给账户永久保留 $\ge 55\%$ 的抗震荡缓冲垫。
