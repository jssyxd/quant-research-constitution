import numpy as np
import pandas as pd
import random
import json
from deap import base, creator, tools, gp
import warnings
warnings.filterwarnings('ignore')

# ==============================================================================
# 1. 真实行情与特征提取 (ETHUSDT-PERP 15m 永续合约)
# ==============================================================================
print(">>> [Step 1] 加载本地 15m ETH 永续合约数据 (Parquet)...")
path = '/home/da/桌面/database/03_governed_lake/v2_parquet_lake/crypto/futures_um/ETHUSDT/15m/ETHUSDT_15m_consolidated.parquet'
df = pd.read_parquet(path)
df['datetime'] = pd.to_datetime(df['datetime'])
df.set_index('datetime', inplace=True)
df.sort_index(inplace=True)

# 取最近 25,000 根 15m K线 (约 8.5 个月，含高波动、单边、震荡行情)
df = df.iloc[-25000:].copy()

close = df['close'].values.astype(float)
open_p = df['open'].values.astype(float)
high = df['high'].values.astype(float)
low = df['low'].values.astype(float)
volume = df['volume'].values.astype(float)
quote_vol = df['quote_volume'].values.astype(float)
taker_buy = df['taker_buy_volume'].values.astype(float)
dates = df.index

# 因子特征矩阵
# F1: RET (对数收益率)
ret = np.zeros(len(close))
ret[1:] = np.log(close[1:] / close[:-1])

# F2: VOL_ACCEL (成交量加速度)
vol_accel = np.zeros(len(volume))
vol_accel[1:] = (volume[1:] - volume[:-1]) / (volume[:-1] + 1e-6)

# F3: HL_SPREAD (高低振幅)
hl_spread = (high - low) / (close + 1e-6)

# F4: TAKER_IMBALANCE (主动买入量失衡)
taker_imb = (2.0 * taker_buy - volume) / (volume + 1e-6)

# F5: K_POSITION (K线收盘位置，压力比)
k_pos = (close - low) / (high - low + 1e-6)

# ==============================================================================
# 2. AlphaEvolve 算子定义 (含 Q-Learning 状态更新节点)
# ==============================================================================
def safe_div(x, y):
    with np.errstate(divide='ignore', invalid='ignore'):
        return np.nan_to_num(np.where(np.abs(y) > 1e-5, x / y, 1.0), nan=1.0)

def ts_lag(x):
    res = np.empty_like(x)
    res[0] = x[0]
    res[1:] = x[:-1]
    return res

def ts_delta(x):
    return x - ts_lag(x)

def ts_sma(x):
    return pd.Series(x).rolling(16, min_periods=1).mean().values

def ts_zscore(x):
    s = pd.Series(x)
    m = s.rolling(20, min_periods=1).mean()
    std = s.rolling(20, min_periods=1).std().replace(0, 1e-6)
    return ((s - m) / std).fillna(0.0).values

# 涌现算子：时序差分 Q-State 价值估值
def q_learning_node(state_in, impact_in, discount_weight):
    # V(t) = gamma * V(t-1) + alpha * (reward_estimate)
    # 模拟无人工干预下的强化学习动态博弈打分
    gamma = 0.88
    alpha = 0.12
    v = np.zeros_like(state_in)
    for t in range(1, len(state_in)):
        reward_step = state_in[t] * 15.0 + impact_in[t] * 0.8
        v[t] = gamma * v[t-1] + alpha * reward_step
    return v

# ==============================================================================
# 3. 构建 GP 演化环境 (DEAP PrimitiveSet)
# ==============================================================================
pset = gp.PrimitiveSet("MAIN", 5)
pset.renameArguments(ARG0='ret', ARG1='vol_accel', ARG2='hl_spread', ARG3='taker_imb', ARG4='k_pos')

pset.addPrimitive(np.add, 2)
pset.addPrimitive(np.subtract, 2)
pset.addPrimitive(np.multiply, 2)
pset.addPrimitive(safe_div, 2)
pset.addPrimitive(np.negative, 1)
pset.addPrimitive(ts_lag, 1)
pset.addPrimitive(ts_delta, 1)
pset.addPrimitive(ts_sma, 1)
pset.addPrimitive(ts_zscore, 1)
pset.addPrimitive(q_learning_node, 3)

if hasattr(creator, "FitnessMax"):
    del creator.FitnessMax
if hasattr(creator, "Individual"):
    del creator.Individual

creator.create("FitnessMax", base.Fitness, weights=(1.0,))
creator.create("Individual", gp.PrimitiveTree, fitness=creator.FitnessMax)

toolbox = base.Toolbox()
toolbox.register("expr", gp.genHalfAndHalf, pset=pset, min_=2, max_=5)
toolbox.register("individual", tools.initIterate, creator.Individual, toolbox.expr)
toolbox.register("population", tools.initRepeat, list, toolbox.individual)
toolbox.register("compile", gp.compile, pset=pset)

# 划分训练集（16,000根 15m）与样本外测试集（最后 9,000 根 15m，约 93 天完全未见数据）
train_len = 16000
train_feats = [ret[:train_len], vol_accel[:train_len], hl_spread[:train_len], taker_imb[:train_len], k_pos[:train_len]]
train_close = close[:train_len]
train_high = high[:train_len]
train_low = low[:train_len]

# ==============================================================================
# 4. 核心评估函数：高胜率剥头皮 (0.9%止盈, 2.5%止损, 50%首仓+75%加仓)
# ==============================================================================
def fast_evaluate(individual, feats, c_arr, h_arr, l_arr):
    try:
        f = toolbox.compile(expr=individual)
        raw_s = f(*feats)
        sig = np.nan_to_num(raw_s, nan=0.0)
        s_std = np.std(sig)
        if s_std < 1e-6:
            return (-999.0,)
        norm_s = (sig - np.mean(sig)) / s_std
        
        # 严格执行实盘回测状态机
        cash = 10000.0
        pos_u = 0.0
        pos_dir = 0
        order_step = 0
        entry_avg_p = 0.0
        
        pnl_records = []
        trade_count = 0
        
        for t in range(50, len(c_arr)):
            cp = c_arr[t]
            hi = h_arr[t]
            lo = l_arr[t]
            s_val = norm_s[t]
            
            # 止盈止损优先判定
            if pos_dir == 1:
                # 多单：最高冲到 hi，最低踩到 lo
                if (hi - entry_avg_p) / entry_avg_p >= 0.009: # 0.9% 快速止盈
                    exit_p = entry_avg_p * 1.009
                    pnl = pos_u * (exit_p - entry_avg_p) - pos_u * exit_p * 0.0005
                    cash += pos_u * exit_p - pos_u * exit_p * 0.0005
                    pnl_records.append(pnl)
                    pos_u = 0.0; pos_dir = 0; order_step = 0
                    continue
                elif (lo - entry_avg_p) / entry_avg_p <= -0.025: # 2.5% 硬止损
                    exit_p = entry_avg_p * 0.975
                    pnl = pos_u * (exit_p - entry_avg_p) - pos_u * exit_p * 0.0005
                    cash += pos_u * exit_p - pos_u * exit_p * 0.0005
                    pnl_records.append(pnl)
                    pos_u = 0.0; pos_dir = 0; order_step = 0
                    continue
            elif pos_dir == -1:
                if (entry_avg_p - lo) / entry_avg_p >= 0.009:
                    exit_p = entry_avg_p * 0.991
                    pnl = pos_u * (entry_avg_p - exit_p) - pos_u * exit_p * 0.0005
                    cash += pos_u * (entry_avg_p * 2 - exit_p) - pos_u * exit_p * 0.0005
                    pnl_records.append(pnl)
                    pos_u = 0.0; pos_dir = 0; order_step = 0
                    continue
                elif (entry_avg_p - hi) / entry_avg_p <= -0.025:
                    exit_p = entry_avg_p * 1.025
                    pnl = pos_u * (entry_avg_p - exit_p) - pos_u * exit_p * 0.0005
                    cash += pos_u * (entry_avg_p * 2 - exit_p) - pos_u * exit_p * 0.0005
                    pnl_records.append(pnl)
                    pos_u = 0.0; pos_dir = 0; order_step = 0
                    continue
            
            # 入场与加仓逻辑 (50% 首仓 + 75% 加仓)
            if s_val > 1.3: # 多头极值信号
                if pos_dir == 0:
                    alloc = cash * 0.50
                    u = (alloc * 0.9995) / cp
                    cash -= alloc
                    pos_u = u; pos_dir = 1; order_step = 1
                    entry_avg_p = cp
                    trade_count += 1
                elif pos_dir == 1 and order_step == 1:
                    alloc = cash * 0.75
                    u = (alloc * 0.9995) / cp
                    cash -= alloc
                    entry_avg_p = (pos_u * entry_avg_p + u * cp) / (pos_u + u)
                    pos_u += u
                    order_step = 2
                    trade_count += 1
            elif s_val < -1.3: # 空头极值信号
                if pos_dir == 0:
                    alloc = cash * 0.50
                    u = (alloc * 0.9995) / cp
                    cash -= alloc
                    pos_u = u; pos_dir = -1; order_step = 1
                    entry_avg_p = cp
                    trade_count += 1
                elif pos_dir == -1 and order_step == 1:
                    alloc = cash * 0.75
                    u = (alloc * 0.9995) / cp
                    cash -= alloc
                    entry_avg_p = (pos_u * entry_avg_p + u * cp) / (pos_u + u)
                    pos_u += u
                    order_step = 2
                    trade_count += 1
                    
        if len(pnl_records) < 15:
            return (-999.0,)
            
        wins = [p for p in pnl_records if p > 0]
        win_rate = len(wins) / len(pnl_records)
        total_profit = sum(pnl_records)
        
        # 计算资金曲线最大回撤
        equity = 10000.0 + np.cumsum(pnl_records)
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / peak
        max_dd = np.max(dd) if len(dd) > 0 else 0.5
        
        # 奖励函数核心：Calmar + 极高胜率激励 + 回撤平方重罚
        calmar = (total_profit / 10000.0) / (max_dd + 1e-6)
        fitness = calmar * 1.5 + win_rate * 10.0 - 15.0 * (max_dd ** 2)
        return (float(fitness),)
    except:
        return (-999.0,)

toolbox.register("evaluate", fast_evaluate, feats=train_feats, c_arr=train_close, h_arr=train_high, l_arr=train_low)
toolbox.register("select", tools.selTournament, tournsize=4)
toolbox.register("mate", gp.cxOnePoint)
toolbox.register("mutate", gp.mutUniform, expr=toolbox.expr, pset=pset)

# ==============================================================================
# 5. 执行演化搜索 (AlphaEvolve Loop)
# ==============================================================================
print(">>> [Step 2] 启动 AlphaEvolve 世代演化 (共 15 世代)...")
pop = toolbox.population(n=60)
hof = tools.HallOfFame(1)

for gen in range(1, 16):
    offspring = list(map(toolbox.clone, toolbox.select(pop, len(pop))))
    for c1, c2 in zip(offspring[::2], offspring[1::2]):
        if random.random() < 0.65:
            toolbox.mate(c1, c2)
            del c1.fitness.values; del c2.fitness.values
    for m in offspring:
        if random.random() < 0.35:
            toolbox.mutate(m)
            del m.fitness.values
    invalids = [ind for ind in offspring if not ind.fitness.valid]
    for ind, fit in zip(invalids, map(toolbox.evaluate, invalids)):
        ind.fitness.values = fit
    pop[:] = offspring
    hof.update(pop)
    best_ind = hof[0]
    print(f"Gen {gen:02d} | 最佳个体 Fitness: {best_ind.fitness.values[0]:.4f} | 树深: {best_ind.height}")

best_tree = hof[0]
print("\n" + "="*60)
print(">>> [Step 3] AlphaEvolve 演化收敛！最优策略符号树 AST:")
print(best_tree)
print("="*60)

# ==============================================================================
# 6. 样本外（Out-of-Sample）盲测与逐笔交易日志生成
# ==============================================================================
print("\n>>> [Step 4] 在近 9,000 根 15m 样本外数据上运行 VectorBT 级状态机仿真...")
test_feats = [ret[train_len:], vol_accel[train_len:], hl_spread[train_len:], taker_imb[train_len:], k_pos[train_len:]]
test_c = close[train_len:]
test_h = high[train_len:]
test_l = low[train_len:]
test_d = dates[train_len:]

f_opt = toolbox.compile(expr=best_tree)
raw_test_sig = f_opt(*test_feats)
std_s = np.std(raw_test_sig) + 1e-6
test_sig = (raw_test_sig - np.mean(raw_test_sig)) / std_s

cash = 10000.0
pos_u = 0.0
pos_dir = 0
order_step = 0
entry_avg_p = 0.0

trade_logs = []
for t in range(50, len(test_c)):
    dt = str(test_d[t])
    cp = test_c[t]
    hi = test_h[t]
    lo = test_l[t]
    s_val = test_sig[t]
    
    # 离场判断
    if pos_dir == 1:
        if (hi - entry_avg_p) / entry_avg_p >= 0.009:
            exit_p = entry_avg_p * 1.009
            pnl = pos_u * (exit_p - entry_avg_p) - pos_u * exit_p * 0.0005
            cash += pos_u * exit_p - pos_u * exit_p * 0.0005
            trade_logs.append({
                "timestamp": dt, "action": "多仓离场 (动态止盈)", "price": round(exit_p, 2),
                "pnl": f"{pnl:+.2f} USDT", "pnl_pct": "+0.90%",
                "reason": "【规则-动态追踪止盈】K线内涨幅触及 0.9% 目标，市价平多离场锁定利润。"
            })
            pos_u = 0.0; pos_dir = 0; order_step = 0
            continue
        elif (lo - entry_avg_p) / entry_avg_p <= -0.025:
            exit_p = entry_avg_p * 0.975
            pnl = pos_u * (exit_p - entry_avg_p) - pos_u * exit_p * 0.0005
            cash += pos_u * exit_p - pos_u * exit_p * 0.0005
            trade_logs.append({
                "timestamp": dt, "action": "多仓离场 (硬性止损)", "price": round(exit_p, 2),
                "pnl": f"{pnl:+.2f} USDT", "pnl_pct": "-2.50%",
                "reason": "【规则-硬性止损】K线急跌击穿 -2.5% 安全线，强制清仓截断亏损。"
            })
            pos_u = 0.0; pos_dir = 0; order_step = 0
            continue
    elif pos_dir == -1:
        if (entry_avg_p - lo) / entry_avg_p >= 0.009:
            exit_p = entry_avg_p * 0.991
            pnl = pos_u * (entry_avg_p - exit_p) - pos_u * exit_p * 0.0005
            cash += pos_u * (entry_avg_p * 2 - exit_p) - pos_u * exit_p * 0.0005
            trade_logs.append({
                "timestamp": dt, "action": "空仓离场 (动态止盈)", "price": round(exit_p, 2),
                "pnl": f"{pnl:+.2f} USDT", "pnl_pct": "+0.90%",
                "reason": "【规则-动态追踪止盈】K线下跌触及 0.9% 目标，市价平空离场。"
            })
            pos_u = 0.0; pos_dir = 0; order_step = 0
            continue
        elif (entry_avg_p - hi) / entry_avg_p <= -0.025:
            exit_p = entry_avg_p * 1.025
            pnl = pos_u * (entry_avg_p - exit_p) - pos_u * exit_p * 0.0005
            cash += pos_u * (entry_avg_p * 2 - exit_p) - pos_u * exit_p * 0.0005
            trade_logs.append({
                "timestamp": dt, "action": "空仓离场 (硬性止损)", "price": round(exit_p, 2),
                "pnl": f"{pnl:+.2f} USDT", "pnl_pct": "-2.50%",
                "reason": "【规则-硬性止损】行情向上击穿 -2.5% 安全线，强制止损出局。"
            })
            pos_u = 0.0; pos_dir = 0; order_step = 0
            continue

    # 入场判定 (15m 收线检测)
    if s_val > 1.3:
        if pos_dir == 0:
            alloc = cash * 0.50
            u = (alloc * 0.9995) / cp
            cash -= alloc
            pos_u = u; pos_dir = 1; order_step = 1
            entry_avg_p = cp
            trade_logs.append({
                "timestamp": dt, "action": "多仓进场 (50%首仓)", "price": round(cp, 2),
                "pnl": "--", "pnl_pct": "--",
                "reason": f"【规则-15m收盘开多】AlphaEvolve涌现信号={s_val:.2f}>1.3，首仓占用可用保证金 50%。"
            })
        elif pos_dir == 1 and order_step == 1:
            alloc = cash * 0.75
            u = (alloc * 0.9995) / cp
            cash -= alloc
            entry_avg_p = (pos_u * entry_avg_p + u * cp) / (pos_u + u)
            pos_u += u
            order_step = 2
            trade_logs.append({
                "timestamp": dt, "action": "多仓进场 (75%加仓)", "price": round(cp, 2),
                "pnl": "--", "pnl_pct": "--",
                "reason": f"【规则-15m加仓】信号维持强势={s_val:.2f}>1.3，追加可用保证金的 75%。"
            })
    elif s_val < -1.3:
        if pos_dir == 0:
            alloc = cash * 0.50
            u = (alloc * 0.9995) / cp
            cash -= alloc
            pos_u = u; pos_dir = -1; order_step = 1
            entry_avg_p = cp
            trade_logs.append({
                "timestamp": dt, "action": "空仓进场 (50%首仓)", "price": round(cp, 2),
                "pnl": "--", "pnl_pct": "--",
                "reason": f"【规则-15m收盘开空】AlphaEvolve涌现信号={s_val:.2f}<-1.3，首仓占用可用保证金 50%。"
            })
        elif pos_dir == -1 and order_step == 1:
            alloc = cash * 0.75
            u = (alloc * 0.9995) / cp
            cash -= alloc
            entry_avg_p = (pos_u * entry_avg_p + u * cp) / (pos_u + u)
            pos_u += u
            order_step = 2
            trade_logs.append({
                "timestamp": dt, "action": "空仓进场 (75%加仓)", "price": round(cp, 2),
                "pnl": "--", "pnl_pct": "--",
                "reason": f"【规则-15m加仓】空头信号持续共振={s_val:.2f}<-1.3，追加可用保证金的 75%。"
            })

closed = [t for t in trade_logs if "离场" in t["action"]]
wins = [t for t in closed if "止盈" in t["action"]]
win_rate = (len(wins) / len(closed)) * 100 if len(closed) > 0 else 0

print("="*60)
print(f"样本外 (9000根 15m) 回测统计:")
print(f"总触发事件: {len(trade_logs)} 次")
print(f"已完成平仓交易: {len(closed)} 笔")
print(f"盈利笔数 (止盈): {len(wins)} 笔")
print(f"亏损笔数 (止损): {len(closed) - len(wins)} 笔")
print(f"真实平仓胜率: {win_rate:.2f}%")
print(f"期末资金: {cash:.2f} USDT (初始 10000 USDT)")
print("="*60)

with open('/home/da/桌面/ethAI/strategy_engine/alphaevolve_15m_final_trades.json', 'w', encoding='utf-8') as f:
    json.dump({
        "ast": str(best_tree),
        "win_rate": f"{win_rate:.2f}%",
        "final_cash": round(cash, 2),
        "trades": trade_logs
    }, f, ensure_ascii=False, indent=2)
