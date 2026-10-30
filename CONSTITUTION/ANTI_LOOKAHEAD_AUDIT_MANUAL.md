# 反前视偏差与微观结构撮合审计操作手册
(Anti Look-Ahead Bias & Microstructure Matching Audit Manual)

> **宪法判词**：“凡以未来之收盘，撮过去之极值者，皆为数字幻象。”  
> **适用范围**：高频做市策略、微观网格策略、K 线回测引擎、订单簿状态机。

---

## 一、 本次重大前视偏差案情回放与破案过程

在对多 Agent 交付的 `run_doge_sui_backtest.py`（DOGE 宣称 +16,170%、SUI 宣称 +26,407%）与 `sol_engine_backtest.py` 进行真相层穿透式审计时，验证工作组（Verifier Agent）捕获了两个隐蔽性极高、但在高频量化中极具毁灭性的经典 Bug：

### 1. 致命案情：以“当前 Bar 收盘价”定价，却撮合在“当前 Bar 历史极值”
- **涉事源码切片 (`run_doge_sui_backtest.py` L124–L185)**：
  ```python
  for i in range(n):
      s = c_arr[i]           # 错误根源：获取当前 Bar 的收盘价 Close[i]
      ...
      p_micro = s + obi_arr[i] * (s * 0.0002)
      r = p_micro - inv_bias
      bid_p = r - delta_bid  # 基于当前 Bar 收盘价计算买单
      ask_p = r + delta_ask  # 基于当前 Bar 收盘价计算卖单
      ...
      # 致命逻辑穿透：当前 Bar 尚未结束，却判断当前 Bar 已经发生过的 Low[i] 是否触碰 bid_p
      if allow_bid and l_arr[i] <= bid_p:
          fill_p = bid_p
          cash -= (notional + fee)
          q += 1.0
  ```
- **破案逻辑推理**：
  1. 在实盘时间线上，$C_i$（当前分钟收盘价）在物理上发生在第 $59.999$ 秒；
  2. 而 $L_i$（当前分钟最低价）可能早在该分钟第 $10$ 秒就已经形成；
  3. 代码在第 $59.999$ 秒根据收盘价算出了一个最合理的做市买入价，却通过时间倒流（Time-Travel），在第 $10$ 秒以该价格“被动成交”；
  4. 这相当于拥有了“预测本分钟最终收盘价”的超能力去抄底这一分钟的最低点，在 91.8 万根 Bar 的复利滚雪球下，制造出上万倍的虚假收益率。

### 2. 致命案情：同 Bar 双边完美“高抛低吸”闭环
- **涉事源码切片**：
  在一根 1 分钟 Bar 的处理循环中，代码在同一个 `for i in range(n):` 迭代内，连续判断：
  ```python
  if allow_bid and l_arr[i] <= bid_p:
      q += 1.0  # 买单成交
  if allow_ask and h_arr[i] >= ask_p:
      q -= 1.0  # 卖单在同一根 Bar 内紧接着成交
  ```
- **破案逻辑推理**：
  单根 1 分钟 K 线只有四个汇总价格（OHLC），并没有内部价格运动序列。如果行情是**先暴涨冲顶再瀑布暴跌**：做市商挂在下方的买单在暴跌中被动接盘并深度套牢，而上方的卖单在冲顶时早已过去，根本不可能在该分钟内完成平仓。代码无条件假设一分钟内“既在最低点买了，又在最高点卖了”，将不可控的市场趋势风险凭空变成了确定性的双边收割。

---

## 二、 反前视偏差标准审计流程 (4 步审查法)

所有进入 Truth Layer 的做市回测代码，必须强制通过以下 4 步静态与动态审计：

```
                 ┌────────────────────────────────────────────────────────┐
                 │ 步骤 1: 静态 AST 检查 (变量索引对齐审查)               │
                 │ 检查报价计算中使用的价格数组索引 vs 撮合引用的极值索引 │
                 └───────────────────────────┬────────────────────────────┘
                                             │
                                             ▼
                 ┌────────────────────────────────────────────────────────┐
                 │ 步骤 2: 因果延迟强制注入 (Latency / Shift Assertion)   │
                 │ 报价最早只能在 i+1 根 Bar 挂单，或在下一个 Tick 撮合   │
                 └───────────────────────────┬────────────────────────────┘
                                             │
                                             ▼
                 ┌────────────────────────────────────────────────────────┐
                 │ 步骤 3: 真实微秒级 L2 订单簿压力测试 (Tick Benchmarking)│
                 │ 废除 K 线臆测，使用数据库内真实 20 档 Depth 数据撮合   │
                 └───────────────────────────┬────────────────────────────┘
                                             │
                                             ▼
                 ┌────────────────────────────────────────────────────────┐
                 │ 步骤 4: 黄金测试差分对比 (Golden Test Consistency)     │
                 │ 校验固定输入与预期结果的确定性哈希                    │
                 └────────────────────────────────────────────────────────┘
```

---

## 三、 宪法规范代码模板 (因果律撮合状态机)

### 1. K 线级别标准因果撮合模板 (Next-Bar Execution)
如果使用 1m K 线仿真，做市报价必须在第 $t$ 根 Bar 结束时基于历史计算，并在第 $t+1$ 根 Bar 生效：

```python
# 正确的因果撮合示范
for t in range(1, n):
    # 1. 严格使用 t-1 的历史信息计算保留价格与报价
    prev_close = c_arr[t - 1]
    sigma_prev = sig_arr[t - 1]
    obi_prev = obi_arr[t - 1]
    
    r_t = compute_reservation_price(prev_close, sigma_prev, q, obi_prev)
    bid_quote = r_t - delta_bid
    ask_quote = r_t + delta_ask
    
    # 2. 严格在第 t 根 Bar 的真实行进中检验撮合 (不能跨 Bar 串行闭环)
    bar_open = o_arr[t]
    bar_high = h_arr[t]
    bar_low = l_arr[t]
    
    # 防止盘口倒挂与同 Bar 穿透
    bid_filled = False
    ask_filled = False
    
    # 若开盘直接跳空穿透，按开盘价或限制挂单
    if bar_low <= bid_quote and q < max_inv:
        fill_bid_px = bid_quote
        execute_trade("BUY", fill_bid_px)
        bid_filled = True
        
    # 如果同一 Bar 内买单已成交，卖单平仓必须强制顺延至下一个事件，严禁同 Bar 立即平仓
    if bar_high >= ask_quote and q > -max_inv and not bid_filled:
        fill_ask_px = ask_quote
        execute_trade("SELL", fill_ask_px)
```

### 2. 逐笔 L2 订单簿订单生命周期模板 (Event-Driven LOB Execution)
最高精度的做市回测必须使用真实 L2 订单簿，由市场变动事件驱动队列消耗：

```python
# 订单簿因果生命周期
for t in range(n_ticks):
    current_market_ask = a1_p[t]
    current_market_bid = b1_p[t]
    
    # 1. 先用 t 时刻的新盘口行情撮合 t-1 时刻已挂在订单簿里的活动订单
    if active_bid is not None:
        if current_market_ask <= active_bid.price:
            # 真实对手盘主动砸穿我方挂单价
            confirm_fill(active_bid)
            active_bid = None
            cooldown_timer = COOLDOWN_TICKS
            
    if active_ask is not None:
        if current_market_bid >= active_ask.price:
            # 真实对手盘主动买穿我方挂单价
            confirm_fill(active_ask)
            active_ask = None
            cooldown_timer = COOLDOWN_TICKS
            
    # 2. 撮合完毕后，再根据 t 时刻的微观特征更新计算 t+1 的挂单报价
    new_bid, new_ask = compute_as_quotes(micro_px[t], obi[t], inventory)
    
    # 队列保持检查 (Queue Priority Preservation)
    if abs(active_bid.price - new_bid) > TOLERANCE:
        replace_order(new_bid)
```

---

## 四、 闸门审计清单 (Audit Checklist)

- [ ] **索引自洽性**：`bid_price[t]` 的计算输入中是否包含 `Close[t]`, `High[t]`, `Low[t]`？（若包含，直接红牌驳回）。
- [ ] **双向撮合独立性**：同一根 Bar 内是否存在同时触发买单和卖单的代码路径？（若存在且无 Tick 顺序证明，直接红牌驳回）。
- [ ] **向后填充检测**：全局搜索 `.bfill()` 与 `fillna(method='bfill')`，发现即刻熔断。
- [ ] **手续费名义基础**：衍生品手续费是否基于 $P \times Q \times \text{Leverage}$ 全额计提？
- [ ] **真实压力测试比对**：是否通过了 `BTCUSDT_depth20_20260326_governed.parquet`（32.2万 Ticks 暴跌压力测试）的独立验证？
