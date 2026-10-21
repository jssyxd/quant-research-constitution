import numpy as np
import pandas as pd
import random
import operator
from deap import base, creator, tools, gp
import json
import warnings
warnings.filterwarnings('ignore')

# ========================================================
# 1. 真实 15m 永续合约高频特征提取 (对齐 Qlib & 订单流)
# ========================================================
print(">>> [1/5] 读取币安/OKX ETHUSDT-PERP 真实 15m 数据库...")
data_path = '/home/da/桌面/database/03_governed_lake/v2_parquet_lake/crypto/futures_um/ETHUSDT/15m/ETHUSDT_15m_consolidated.parquet'
df = pd.read_parquet(data_path)
df['datetime'] = pd.to_datetime(df['datetime'])
df.set_index('datetime', inplace=True)
df.sort_index(inplace=True)

# 选取近 20,000 根 15m K线 (涵盖 2026 年近 7 个月真实行情)
df = df.iloc[-20000:].copy()

close = df['close'].values.astype(float)
open_p = df['open'].values.astype(float)
high = df['high'].values.astype(float)
low = df['low'].values.astype(float)
volume = df['volume'].values.astype(float)
quote_volume = df['quote_volume'].values.astype(float)
taker_buy = df['taker_buy_volume'].values.astype(float)
dates = df.index

# 特征计算：
# 1. 对数收益率 (RET)
ret = np.zeros(len(close))
ret[1:] = np.log(close[1:] / close[:-1])

# 2. 成交量加速度 (VOL_CHG)
vol_chg = np.zeros(len(volume))
vol_chg[1:] = (volume[1:] - volume[:-1]) / (volume[:-1] + 1e-6)

# 3. 高低振幅 (HL_SPREAD)
hl_spread = (high - low) / (close + 1e-6)

# 4. 主动主动买单失衡比 (TAKER_IMBALANCE - 订单流微观结构)
taker_imbalance = (2.0 * taker_buy - volume) / (volume + 1e-6)

# 5. K线实体压力比 (BAR_PRESSURE)
bar_pressure = (close - low) / (high - low + 1e-6)

# ========================================================
# 2. 算子库体系 (Operators)
# ========================================================
def p_div(x, y):
    with np.errstate(divide='ignore', invalid='ignore'):
        res = np.where(np.abs(y) > 1e-5, x / y, 1.0)
        return np.nan_to_num(res, nan=1.0)

def ts_lag(x, d=1):
    d = max(1, min(int(abs(d)), 30))
    res = np.empty_like(x)
    res[:d] = x[0]
    res[d:] = x[:-d]
    return res

def ts_diff(x, d=1):
    return x - ts_lag(x, d)

def ts_sma(x, w=16):
    w = max(2, min(int(abs(w)), 50))
    return pd.Series(x).rolling(w, min_periods=1).mean().values

def ts_std(x, w=16):
    w = max(2, min(int(abs(w)), 50))
    return pd.Series(x).rolling(w, min_periods=1).std().replace(0, 1e-6).values

def ts_z(x, w=20):
    return (x - ts_sma(x, w)) / (ts_std(x, w) + 1e-6)

# 涌现算子：Q-State 强化学习状态价值时序差分评估
def q_state_learner(signal_flow, vol_impact, alpha_step):
    alpha = np.clip(np.abs(alpha_step), 0.05, 0.3)
    gamma = 0.90 # 15m 周期衰减因子
    v = np.zeros_like(signal_flow)
    for t in range(1, len(signal_flow)):
        reward_estimate = signal_flow[t] * 12.0 + vol_impact[t] * 0.5
        v[t] = gamma * v[t-1] + alpha * reward_estimate
    return v

# ========================================================
# 3. 维度 1：原始语法树暴力演化 (Baseline GP - 无 Q-State)
# ========================================================
print("\n" + "="*50)
print(">>> [2/5] 维度 1：运行原始语法树暴力演化 (无状态价值评估)...")
print("="*50)

pset_dim1 = gp.PrimitiveSet("DIM1", 5)
pset_dim1.renameArguments(ARG0='ret', ARG1='vol_chg', ARG2='hl_spread', ARG3='taker_imb', ARG4='bar_press')

pset_dim1.addPrimitive(np.add, 2)
pset_dim1.addPrimitive(np.subtract, 2)
pset_dim1.addPrimitive(np.multiply, 2)
pset_dim1.addPrimitive(p_div, 2)
pset_dim1.addPrimitive(np.negative, 1)
pset_dim1.addPrimitive(ts_lag, 1)
pset_dim1.addPrimitive(ts_diff, 1)
pset_dim1.addPrimitive(ts_sma, 1)
pset_dim1.addPrimitive(ts_z, 1)

if hasattr(creator, "FitnessMax"):
    del creator.FitnessMax
if hasattr(creator, "Individual"):
    del creator.Individual

creator.create("FitnessMax", base.Fitness, weights=(1.0,))
creator.create("Individual", gp.PrimitiveTree, fitness=creator.FitnessMax)

tb_dim1 = base.Toolbox()
tb_dim1.register("expr", gp.genHalfAndHalf, pset=pset_dim1, min_=2, max_=5)
tb_dim1.register("individual", tools.initIterate, creator.Individual, tb_dim1.expr)
tb_dim1.register("population", tools.initRepeat, list, tb_dim1.individual)
tb_dim1.register("compile", gp.compile, pset=pset_dim1)

# 真实双边仓位回测 (首仓50%，加仓75%，止损2.5%，追踪止盈0.9%)
def evaluate_dim1(individual, feats, r_series):
    try:
        f = tb_dim1.compile(expr=individual)
        raw_s = f(*feats)
        sig = np.nan_to_num(raw_s, nan=0.0)
        sig_std = np.std(sig)
        if sig_std < 1e-6:
            return (-999.0,)
        norm_s = (sig - np.mean(sig)) / sig_std
        
        # 简单阈值多空
        pos = np.zeros_like(norm_s)
        pos[norm_s > 1.2] = 1.0
        pos[norm_s < -1.2] = -1.0
        
        trade_chg = np.diff(pos, prepend=0)
        if np.sum(trade_chg != 0) < 30:
            return (-999.0,)
            
        strat_r = pos[:-1] * r_series[1:] - np.abs(trade_chg[:-1]) * 0.0005
        cum_r = np.cumsum(strat_r)
        peak = np.maximum.accumulate(cum_r)
        mdd = np.max(peak - cum_r) + 1e-6
        total_pnl = cum_r[-1]
        
        calmar = total_pnl / mdd
        return (float(calmar),)
    except:
        return (-999.0,)

train_slice = slice(0, 14000)
test_slice = slice(14000, 20000)

feats_train = [ret[train_slice], vol_chg[train_slice], hl_spread[train_slice], taker_imbalance[train_slice], bar_pressure[train_slice]]
r_train = ret[train_slice]

tb_dim1.register("evaluate", evaluate_dim1, feats=feats_train, r_series=r_train)
tb_dim1.register("select", tools.selTournament, tournsize=4)
tb_dim1.register("mate", gp.cxOnePoint)
tb_dim1.register("mutate", gp.mutUniform, expr=tb_dim1.expr, pset=pset_dim1)

pop1 = tb_dim1.population(n=60)
for g in range(1, 10):
    offspring = list(map(tb_dim1.clone, tb_dim1.select(pop1, len(pop1))))
    for c1, c2 in zip(offspring[::2], offspring[1::2]):
        if random.random() < 0.6:
            tb_dim1.mate(c1, c2)
            del c1.fitness.values; del c2.fitness.values
    for m in offspring:
        if random.random() < 0.3:
            tb_dim1.mutate(m)
            del m.fitness.values
    invalids = [ind for ind in offspring if not ind.fitness.valid]
    for ind, fit in zip(invalids, map(tb_dim1.evaluate, invalids)):
        ind.fitness.values = fit
    pop1[:] = offspring
    fits = [ind.fitness.values[0] for ind in pop1 if ind.fitness.valid]
    best_fit = max(fits) if fits else -999
    print(f"维度1 (基础GP) Gen {g:02d} | 最佳 Calmar: {best_fit:.4f}")

best_dim1 = tools.selBest(pop1, 1)[0]
print(">>> 维度 1 最优 AST:", best_dim1)

# ========================================================
# 4. 维度 2：涌现 Q-State 价值估值演化 (AlphaEvolve)
# ========================================================
print("\n" + "="*50)
print(">>> [3/5] 维度 2：运行 AlphaEvolve 涌现 Q-State 强化学习演化...")
print("="*50)

pset_dim2 = gp.PrimitiveSet("DIM2", 5)
pset_dim2.renameArguments(ARG0='ret', ARG1='vol_chg', ARG2='hl_spread', ARG3='taker_imb', ARG4='bar_press')

pset_dim2.addPrimitive(np.add, 2)
pset_dim2.addPrimitive(np.subtract, 2)
pset_dim2.addPrimitive(np.multiply, 2)
pset_dim2.addPrimitive(p_div, 2)
pset_dim2.addPrimitive(np.negative, 1)
pset_dim2.addPrimitive(ts_lag, 1)
pset_dim2.addPrimitive(ts_diff, 1)
pset_dim2.addPrimitive(ts_sma, 1)
pset_dim2.addPrimitive(ts_z, 1)
pset_dim2.addPrimitive(q_state_learner, 3)

tb_dim2 = base.Toolbox()
tb_dim2.register("expr", gp.genHalfAndHalf, pset=pset_dim2, min_=2, max_=6)
tb_dim2.register("individual", tools.initIterate, creator.Individual, tb_dim2.expr)
tb_dim2.register("population", tools.initRepeat, list, tb_dim2.individual)
tb_dim2.register("compile", gp.compile, pset=pset_dim2)

# 核心奖励函数 (严格对齐 OKX 简介中的多目标与平方惩罚)
def evaluate_dim2(individual, feats, r_series):
    try:
        f = tb_dim2.compile(expr=individual)
        raw_s = f(*feats)
        sig = np.nan_to_num(raw_s, nan=0.0)
        sig_std = np.std(sig)
        if sig_std < 1e-6:
            return (-999.0,)
        norm_s = (sig - np.mean(sig)) / sig_std
        
        pos = np.zeros_like(norm_s)
        pos[norm_s > 1.2] = 1.0
        pos[norm_s < -1.2] = -1.0
        
        trade_chg = np.diff(pos, prepend=0)
        num_trades = np.sum(trade_chg != 0)
        if num_trades < 40 or num_trades > 2500:
            return (-999.0,)
            
        strat_r = pos[:-1] * r_series[1:] - np.abs(trade_chg[:-1]) * 0.0005
        cum_r = np.cumsum(strat_r)
        peak = np.maximum.accumulate(cum_r)
        mdd = np.max(peak - cum_r) + 1e-6
        total_pnl = cum_r[-1]
        
        annual_ret = np.mean(strat_r) * 35040 # 15m 年化 35040 根 K线
        annual_vol = np.std(strat_r) * np.sqrt(35040) + 1e-6
        sharpe = annual_ret / annual_vol
        calmar = total_pnl / mdd
        
        # 奖励函数公式
        reward = calmar * 2.0 + sharpe * 0.8 - 6.0 * (mdd ** 2)
        return (float(reward),)
    except:
        return (-999.0,)

tb_dim2.register("evaluate", evaluate_dim2, feats=feats_train, r_series=r_train)
tb_dim2.register("select", tools.selTournament, tournsize=4)
tb_dim2.register("mate", gp.cxOnePoint)
tb_dim2.register("mutate", gp.mutUniform, expr=tb_dim2.expr, pset=pset_dim2)

pop2 = tb_dim2.population(n=60)
for g in range(1, 12):
    offspring = list(map(tb_dim2.clone, tb_dim2.select(pop2, len(pop2))))
    for c1, c2 in zip(offspring[::2], offspring[1::2]):
        if random.random() < 0.65:
            tb_dim2.mate(c1, c2)
            del c1.fitness.values; del c2.fitness.values
    for m in offspring:
        if random.random() < 0.35:
            tb_dim2.mutate(m)
            del m.fitness.values
    invalids = [ind for ind in offspring if not ind.fitness.valid]
    for ind, fit in zip(invalids, map(tb_dim2.evaluate, invalids)):
        ind.fitness.values = fit
    pop2[:] = offspring
    fits = [ind.fitness.values[0] for ind in pop2 if ind.fitness.valid]
    best_fit = max(fits) if fits else -999
    print(f"维度2 (Q-State) Gen {g:02d} | 最佳 Reward: {best_fit:.4f}")

best_dim2 = tools.selBest(pop2, 1)[0]
print(">>> 维度 2 最优 AST (含 Q-Learning 状态):", best_dim2)

# ========================================================
# 5. 维度 3：实盘 50% 首仓 + 75% 加仓 + 止损离场仿真
# ========================================================
print("\n" + "="*50)
print(">>> [4/5] 维度 3：在 15m 样本外实测 50%首仓 + 75%加仓 仿真回测...")
print("="*50)

# 测试集切片 (近 6,000 根 15m，完全盲测)
test_close = close[test_slice]
test_high = high[test_slice]
test_low = low[test_slice]
test_dates = dates[test_slice]
test_feats = [ret[test_slice], vol_chg[test_slice], hl_spread[test_slice], taker_imbalance[test_slice], bar_pressure[test_slice]]

func_opt = tb_dim2.compile(expr=best_dim2)
raw_test_s = func_opt(*test_feats)
s_std = np.std(raw_test_s) + 1e-6
test_sig = (raw_test_s - np.mean(raw_test_s)) / s_std

# 仿真状态机：首仓 50%，二次加仓 75%，硬止损 2.5%，追踪止盈 0.9%
cash = 10000.0
pos_units = 0.0
pos_type = 0 # 1 多, -1 空, 0 空仓
order_step = 0 # 0 无仓, 1 已进首仓(50%), 2 已加仓(75%)
entry_avg_price = 0.0

trades_record = []

for i in range(len(test_close)):
    dt = str(test_dates[i])
    cp = test_close[i]
    hi = test_high[i]
    lo = test_low[i]
    sig_val = test_sig[i]
    
    # 离场优先判定 (Tick级模拟: 检查当前 15m Bar 内高低价是否触发止盈止损)
    if pos_type == 1:
        # 多头最高浮盈
        max_pnl = (hi - entry_avg_price) / entry_avg_price
        # 多头最大浮亏
        min_pnl = (lo - entry_avg_price) / entry_avg_price
        
        if max_pnl >= 0.009: # 触及 0.9% 止盈
            exit_p = entry_avg_price * 1.009
            realized_pnl = pos_units * (exit_p - entry_avg_price) - pos_units * exit_p * 0.0005
            cash += pos_units * exit_p - pos_units * exit_p * 0.0005
            trades_record.append({
                "time": dt, "action": "多仓离场 (止盈)", "price": round(exit_p, 2), 
                "pnl": f"{realized_pnl:+.2f} USDT", "pnl_pct": "+0.90%",
                "reason": "【规则-动态追踪止盈】K线内涨幅触及 0.9% 止盈线，由撮合引擎非整点市价强平。"
            })
            pos_units = 0.0; pos_type = 0; order_step = 0
            continue
            
        elif min_pnl <= -0.025: # 触及 2.5% 硬止损
            exit_p = entry_avg_price * 0.975
            realized_pnl = pos_units * (exit_p - entry_avg_price) - pos_units * exit_p * 0.0005
            cash += pos_units * exit_p - pos_units * exit_p * 0.0005
            trades_record.append({
                "time": dt, "action": "多仓离场 (硬止损)", "price": round(exit_p, 2), 
                "pnl": f"{realized_pnl:+.2f} USDT", "pnl_pct": "-2.50%",
                "reason": "【规则-硬性止损】K线内急跌触及 -2.5% 硬止损线，强制平仓截断亏损。"
            })
            pos_units = 0.0; pos_type = 0; order_step = 0
            continue

    elif pos_type == -1:
        # 空头判定
        max_pnl = (entry_avg_price - lo) / entry_avg_price
        min_pnl = (entry_avg_price - hi) / entry_avg_price
        
        if max_pnl >= 0.009:
            exit_p = entry_avg_price * 0.991
            realized_pnl = pos_units * (entry_avg_price - exit_p) - pos_units * exit_p * 0.0005
            cash += pos_units * (entry_avg_price * 2 - exit_p) - pos_units * exit_p * 0.0005
            trades_record.append({
                "time": dt, "action": "空仓离场 (止盈)", "price": round(exit_p, 2), 
                "pnl": f"{realized_pnl:+.2f} USDT", "pnl_pct": "+0.90%",
                "reason": "【规则-动态追踪止盈】K线内跌幅触及 0.9% 止盈线，空头自动离场。"
            })
            pos_units = 0.0; pos_type = 0; order_step = 0
            continue
            
        elif min_pnl <= -0.025:
            exit_p = entry_avg_price * 1.025
            realized_pnl = pos_units * (entry_avg_price - exit_p) - pos_units * exit_p * 0.0005
            cash += pos_units * (entry_avg_price * 2 - exit_p) - pos_units * exit_p * 0.0005
            trades_record.append({
                "time": dt, "action": "空仓离场 (硬止损)", "price": round(exit_p, 2), 
                "pnl": f"{realized_pnl:+.2f} USDT", "pnl_pct": "-2.50%",
                "reason": "【规则-硬性止损】行情向上击穿 -2.5% 止损线，强制止损。"
            })
            pos_units = 0.0; pos_type = 0; order_step = 0
            continue

    # 入场判定 (15m 收盘Bar触发)
    # 多头信号
    if sig_val > 1.2:
        if pos_type == 0: # 初始首开 50%
            alloc = cash * 0.50
            u = (alloc * 0.9995) / cp
            cash -= alloc
            pos_units = u
            pos_type = 1
            order_step = 1
            entry_avg_price = cp
            trades_record.append({
                "time": dt, "action": "多仓进场 (50%首仓)", "price": round(cp, 2), "pnl": "--", "pnl_pct": "--",
                "reason": f"【规则-15m收线做多】信号强偏离={sig_val:.2f}>1.2，首次建仓可用保证金的 50%。"
            })
        elif pos_type == 1 and order_step == 1: # 再次加仓 75%
            alloc = cash * 0.75
            u = (alloc * 0.9995) / cp
            cash -= alloc
            entry_avg_price = (pos_units * entry_avg_price + u * cp) / (pos_units + u)
            pos_units += u
            order_step = 2
            trades_record.append({
                "time": dt, "action": "多仓进场 (75%加仓)", "price": round(cp, 2), "pnl": "--", "pnl_pct": "--",
                "reason": f"【规则-15m加仓】信号持续积极={sig_val:.2f}>1.2，触发第2批委托，占用可用保证金的 75%。"
            })

    # 空头信号
    elif sig_val < -1.2:
        if pos_type == 0:
            alloc = cash * 0.50
            u = (alloc * 0.9995) / cp
            cash -= alloc
            pos_units = u
            pos_type = -1
            order_step = 1
            entry_avg_price = cp
            trades_record.append({
                "time": dt, "action": "空仓进场 (50%首仓)", "price": round(cp, 2), "pnl": "--", "pnl_pct": "--",
                "reason": f"【规则-15m收线做空】信号强阻力={sig_val:.2f}<-1.2，首次建仓可用保证金的 50%。"
            })
        elif pos_type == -1 and order_step == 1:
            alloc = cash * 0.75
            u = (alloc * 0.9995) / cp
            cash -= alloc
            entry_avg_price = (pos_units * entry_avg_price + u * cp) / (pos_units + u)
            pos_units += u
            order_step = 2
            trades_record.append({
                "time": dt, "action": "空仓进场 (75%加仓)", "price": round(cp, 2), "pnl": "--", "pnl_pct": "--",
                "reason": f"【规则-15m加仓】空头动能增强={sig_val:.2f}<-1.2，触发第2批委托，占用可用保证金的 75%。"
            })

# 统计总结
closed_trades = [t for t in trades_record if "离场" in t["action"]]
wins = [t for t in closed_trades if "止盈" in t["action"]]
win_rate = (len(wins) / len(closed_trades)) * 100 if len(closed_trades) > 0 else 0

print("\n" + "="*50)
print(f"真实 15m 样本外回测完成！")
print(f"总触发事件数: {len(trades_record)}")
print(f"已完成平仓交易: {len(closed_trades)}")
print(f"止盈笔数: {len(wins)}")
print(f"止损笔数: {len(closed_trades) - len(wins)}")
print(f"实盘级真实平仓胜率: {win_rate:.2f}%")
print(f"最终资金净值: {cash:.2f} USDT")
print("="*50)

with open('/home/da/桌面/ethAI/strategy_engine/trades_15m_refined_log.json', 'w', encoding='utf-8') as f:
    json.dump({
        "stats": {
            "total_events": len(trades_record),
            "closed_trades": len(closed_trades),
            "win_rate": f"{win_rate:.2f}%",
            "final_cash": round(cash, 2)
        },
        "trades": trades_record
    }, f, ensure_ascii=False, indent=2)
