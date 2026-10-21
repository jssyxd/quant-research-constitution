import numpy as np
import pandas as pd
import random
import operator
from deap import base, creator, tools, gp
import warnings
warnings.filterwarnings('ignore')

# 1. 规范化特征算子
def protected_div(left, right):
    with np.errstate(divide='ignore', invalid='ignore'):
        res = np.where(np.abs(right) > 1e-4, left / right, 1.0)
        res = np.nan_to_num(res, nan=1.0, posinf=1.0, neginf=1.0)
    return res

def ts_delay(x):
    res = np.empty_like(x)
    res[0] = x[0]
    res[1:] = x[:-1]
    return res

def ts_delta(x):
    return x - ts_delay(x)

def ts_ma10(x):
    return pd.Series(x).rolling(10, min_periods=1).mean().values

def ts_ma30(x):
    return pd.Series(x).rolling(30, min_periods=1).mean().values

def ts_zscore20(x):
    s = pd.Series(x)
    m = s.rolling(20, min_periods=2).mean()
    std = s.rolling(20, min_periods=2).std().replace(0, 1e-6)
    return ((s - m) / std).fillna(0.0).values

def q_eval_node(state_eval, momentum, discount):
    # 模拟在GP环境下的Q-Learning涌现结构：
    # V(s) = (1 - alpha)*V(s-1) + alpha*(Reward_est + gamma * Q_next)
    alpha = 0.2
    gamma = 0.85
    v = np.zeros_like(state_eval)
    for t in range(1, len(state_eval)):
        v[t] = (1 - alpha) * v[t-1] + alpha * (momentum[t] + gamma * state_eval[t-1])
    return v

# 2. PrimitiveSet
pset = gp.PrimitiveSet("MAIN", 4)
pset.renameArguments(ARG0='ret', ARG1='vol_chg', ARG2='hl_spread', ARG3='pressure')

pset.addPrimitive(np.add, 2)
pset.addPrimitive(np.subtract, 2)
pset.addPrimitive(np.multiply, 2)
pset.addPrimitive(protected_div, 2)
pset.addPrimitive(np.negative, 1)
pset.addPrimitive(np.sign, 1)
pset.addPrimitive(ts_delay, 1)
pset.addPrimitive(ts_delta, 1)
pset.addPrimitive(ts_ma10, 1)
pset.addPrimitive(ts_ma30, 1)
pset.addPrimitive(ts_zscore20, 1)
pset.addPrimitive(q_eval_node, 3)

# 3. Creator
if not hasattr(creator, "FitnessMax"):
    creator.create("FitnessMax", base.Fitness, weights=(1.0,))
if not hasattr(creator, "Individual"):
    creator.create("Individual", gp.PrimitiveTree, fitness=creator.FitnessMax)

toolbox = base.Toolbox()
toolbox.register("expr", gp.genHalfAndHalf, pset=pset, min_=2, max_=6)
toolbox.register("individual", tools.initIterate, creator.Individual, toolbox.expr)
toolbox.register("population", tools.initRepeat, list, toolbox.individual)
toolbox.register("compile", gp.compile, pset=pset)

# 4. 回测打分器：重度卡玛比率与风控截断
def evaluate_strategy(individual, features, ret_series):
    try:
        func = toolbox.compile(expr=individual)
        sig = func(*features)
        sig = np.nan_to_num(sig, nan=0.0)
        
        # 信号标准化与离散开平仓
        sig_std = np.std(sig)
        if sig_std < 1e-6:
            return (-999.0,)
        norm_sig = (sig - np.mean(sig)) / sig_std
        
        pos = np.zeros_like(norm_sig)
        pos[norm_sig > 0.8] = 1.0
        pos[norm_sig < -0.8] = -1.0
        
        # 统计开平仓次数
        trade_chg = np.diff(pos, prepend=0)
        num_trades = np.sum(trade_chg != 0)
        if num_trades < 30 or num_trades > 2000:
            return (-999.0,)
            
        cost = np.abs(trade_chg) * 0.0006 # 0.06% 单边手续费滑点
        strat_ret = pos[:-1] * ret_series[1:] - cost[:-1]
        
        cum_ret = np.cumsum(strat_ret)
        peak = np.maximum.accumulate(cum_ret)
        dd = peak - cum_ret
        max_dd = np.max(dd) + 1e-6
        total_pnl = cum_ret[-1]
        
        if total_pnl <= 0:
            return (-100.0 + total_pnl,)
            
        calmar = total_pnl / max_dd
        annual_ret = np.mean(strat_ret) * 8760
        annual_vol = np.std(strat_ret) * np.sqrt(8760) + 1e-6
        sharpe = annual_ret / annual_vol
        
        # 胜率
        trades_idx = np.where(trade_chg[:-1] != 0)[0]
        # 简单近似每笔交易持仓收益
        win_count = 0
        total_closed = 0
        cur_entry = None
        cur_dir = 0
        for i in range(len(pos)-1):
            if trade_chg[i] != 0:
                if cur_dir != 0: # 平仓结算
                    closed_pnl = (cum_ret[i] - cur_entry)
                    if closed_pnl > 0: win_count += 1
                    total_closed += 1
                cur_dir = pos[i]
                cur_entry = cum_ret[i]
                
        win_rate = (win_count / total_closed) if total_closed > 0 else 0
        
        fitness = calmar * 2.0 + sharpe * 0.8 - 4.0 * (max_dd ** 2) + win_rate * 5.0
        return (float(fitness),)
    except Exception as e:
        return (-999.0,)

toolbox.register("select", tools.selTournament, tournsize=5)
toolbox.register("mate", gp.cxOnePoint)
toolbox.register("mutate", gp.mutUniform, expr=toolbox.expr, pset=pset)

def run():
    print(">>> 加载真实 1h 数据...")
    df = pd.read_csv('/home/da/桌面/database/01_raw_lake/cryptodatadownload/bitstamp/Bitstamp_ETHUSDT_1h.csv', skiprows=1)
    df = df.iloc[::-1].reset_index(drop=True)
    
    close = df['close'].values.astype(float)
    volume = df['Volume ETH'].values.astype(float)
    ret = np.diff(close, prepend=close[0]) / (close + 1e-6)
    vol_chg = np.diff(volume, prepend=volume[0]) / (volume + 1e-6)
    hl_spread = (df['high'] - df['low']).values / (close + 1e-6)
    pressure = (close - df['low']) / (df['high'] - df['low'] + 1e-6)
    
    # 用中间较为剧烈波动的段落进行演化训练
    train_slice = slice(5000, 22000)
    features_train = [ret[train_slice], vol_chg[train_slice], hl_spread[train_slice], pressure[train_slice]]
    ret_train = ret[train_slice]
    
    toolbox.register("evaluate", evaluate_strategy, features=features_train, ret_series=ret_train)
    
    pop = toolbox.population(n=100)
    hof = tools.HallOfFame(3)
    
    print(">>> 启动迭代进化 (50 世代)...")
    NGEN, CXPB, MUTPB = 30, 0.65, 0.35
    
    fitnesses = list(map(toolbox.evaluate, pop))
    for ind, fit in zip(pop, fitnesses):
        ind.fitness.values = fit
        
    for gen in range(1, NGEN + 1):
        offspring = toolbox.select(pop, len(pop))
        offspring = list(map(toolbox.clone, offspring))
        
        for c1, c2 in zip(offspring[::2], offspring[1::2]):
            if random.random() < CXPB:
                toolbox.mate(c1, c2)
                del c1.fitness.values
                del c2.fitness.values
                
        for mutant in offspring:
            if random.random() < MUTPB:
                toolbox.mutate(mutant)
                del mutant.fitness.values
                
        invalid_ind = [ind for ind in offspring if not ind.fitness.valid]
        for ind, fit in zip(invalid_ind, map(toolbox.evaluate, invalid_ind)):
            ind.fitness.values = fit
            
        pop[:] = offspring
        hof.update(pop)
        print(f"Gen {gen:02d} | 最佳 Fitness: {hof[0].fitness.values[0]:.4f} | AST: {hof[0]}")
        
    best = hof[0]
    print("\n>>> 最优策略生成:")
    print("AST:", best)
    with open('/home/da/桌面/ethAI/strategy_engine/best_strategy_ast.txt', 'w') as f:
        f.write(str(best))

if __name__ == '__main__':
    run()
