import numpy as np
import pandas as pd
import random
import operator
from deap import base, creator, tools, gp
import json
import warnings
warnings.filterwarnings('ignore')

# 1. 基础算子与保护算子（针对时序特征）
def protected_div(left, right):
    with np.errstate(divide='ignore', invalid='ignore'):
        res = np.where(np.abs(right) > 1e-6, left / right, 1.0)
        res = np.nan_to_num(res, nan=1.0, posinf=1.0, neginf=1.0)
    return res

def ts_delay(x, d=1):
    d = max(1, min(int(abs(d)), 50))
    res = np.empty_like(x)
    res[:d] = x[0]
    res[d:] = x[:-d]
    return res

def ts_delta(x, d=1):
    return x - ts_delay(x, d)

def ts_decay_linear(x, d=10):
    d = max(2, min(int(abs(d)), 50))
    weights = np.arange(1, d + 1, dtype=float)
    weights /= weights.sum()
    s = pd.Series(x)
    res = s.rolling(d, min_periods=1).apply(lambda w: np.dot(w, weights[-len(w):]) / weights[-len(w):].sum(), raw=True).values
    return np.nan_to_num(res, nan=0.0)

def ts_zscore(x, d=20):
    d = max(3, min(int(abs(d)), 100))
    s = pd.Series(x)
    mean = s.rolling(d, min_periods=2).mean()
    std = s.rolling(d, min_periods=2).std().replace(0, 1e-6)
    res = ((s - mean) / std).values
    return np.nan_to_num(res, nan=0.0)

def gate_condition(cond, true_val, false_val):
    return np.where(cond > 0, true_val, false_val)

def q_eval_structure(state_sig, memory_decay, threshold):
    # 模拟在GP变异中涌现的 Q-Learning / TD 估值结构：
    # 构造带有衰减因子的动态博弈状态价值累积
    gamma = 0.85
    decay = np.clip(np.abs(memory_decay), 0.1, 0.99)
    q_val = np.zeros_like(state_sig)
    for t in range(1, len(state_sig)):
        reward_estimate = state_sig[t] - threshold
        q_val[t] = (1 - decay[t]) * q_val[t-1] + decay[t] * (reward_estimate + gamma * state_sig[t-1])
    return q_val

# 2. 构建 DEAP 强类型 PrimitiveSet
pset = gp.PrimitiveSet("MAIN", 6)
pset.renameArguments(ARG0='close', ARG1='volume', ARG2='ret', ARG3='vol_chg', ARG4='hl_spread', ARG5='pressure')

# 数学算子
pset.addPrimitive(np.add, 2)
pset.addPrimitive(np.subtract, 2)
pset.addPrimitive(np.multiply, 2)
pset.addPrimitive(protected_div, 2)
pset.addPrimitive(np.negative, 1)
pset.addPrimitive(np.abs, 1)
pset.addPrimitive(np.sign, 1)

# 时序量化特征算子 (AlphaEvolve核心)
pset.addPrimitive(ts_delay, 1)
pset.addPrimitive(ts_delta, 1)
pset.addPrimitive(ts_decay_linear, 1)
pset.addPrimitive(ts_zscore, 1)
pset.addPrimitive(gate_condition, 3)
pset.addPrimitive(q_eval_structure, 3)

# 终结符
pset.addEphemeralConstant("rand101", lambda: round(random.uniform(-1, 1), 2))

# 3. 进化目标：最大化 Calmar Ratio，夏普比率，重罚最大回撤
creator.create("FitnessMax", base.Fitness, weights=(1.0,))
creator.create("Individual", gp.PrimitiveTree, fitness=creator.FitnessMax)

toolbox = base.Toolbox()
toolbox.register("expr", gp.genHalfAndHalf, pset=pset, min_=2, max_=5)
toolbox.register("individual", tools.initIterate, creator.Individual, toolbox.expr)
toolbox.register("population", tools.initRepeat, list, toolbox.individual)
toolbox.register("compile", gp.compile, pset=pset)

# 4. 评估函数 (高速向量化回测)
def evaluate_strategy(individual, features, ret_series):
    try:
        func = toolbox.compile(expr=individual)
        raw_signal = func(*features)
        
        # 信号标准化与多空离散化
        sig = np.nan_to_num(raw_signal, nan=0.0)
        sig = np.clip(sig, -100, 100)
        
        # 动态阈值开仓 (带缓冲区间防频繁震荡)
        pos = np.zeros_like(sig)
        pos[sig > 0.3] = 1.0
        pos[sig < -0.3] = -1.0
        # 0.3以内保持空仓/平仓
        
        # 策略收益（扣除单边千0.5手续费/滑点）
        trade_chg = np.diff(pos, prepend=0)
        cost = np.abs(trade_chg) * 0.0005
        strat_ret = pos[:-1] * ret_series[1:] - cost[:-1]
        
        if np.std(strat_ret) < 1e-8 or np.sum(np.abs(pos)) < 50:
            return (-999.0,)
        
        cum_ret = np.cumsum(strat_ret)
        peak = np.maximum.accumulate(cum_ret)
        dd = peak - cum_ret
        max_dd = np.max(dd) + 1e-6
        total_pnl = cum_ret[-1]
        
        # 年化收益估算 (以 1h 线算，8760 小时/年)
        annual_ret = np.mean(strat_ret) * 8760
        annual_vol = np.std(strat_ret) * np.sqrt(8760)
        sharpe = annual_ret / (annual_vol + 1e-6)
        calmar = total_pnl / max_dd
        
        # 计算胜率
        trades = strat_ret[trade_chg[:-1] != 0]
        win_rate = np.mean(trades > 0) if len(trades) > 0 else 0
        
        # 核心 Reward 设计：重惩大回撤，奖励卡玛比率与高胜率
        fitness = calmar * 1.5 + sharpe * 0.5 - 5.0 * (max_dd ** 2)
        if win_rate > 0.7:
            fitness += 2.0
            
        return (float(fitness),)
    except Exception as e:
        return (-999.0,)

toolbox.register("evaluate", evaluate_strategy)
toolbox.register("select", tools.selTournament, tournsize=4)
toolbox.register("mate", gp.cxOnePoint)
toolbox.register("mutate", gp.mutUniform, expr=toolbox.expr, pset=pset)

def run_evolution():
    print(">>> 正在加载 ETH 真实 1h 数据...")
    raw_path = '/home/da/桌面/database/01_raw_lake/cryptodatadownload/bitstamp/Bitstamp_ETHUSDT_1h.csv'
    df = pd.read_csv(raw_path, skiprows=1)
    df = df.iloc[::-1].reset_index(drop=True) # 按时间正序
    
    close = df['close'].values.astype(float)
    volume = df['Volume ETH'].values.astype(float)
    ret = np.diff(close, prepend=close[0]) / close
    vol_chg = np.diff(volume, prepend=volume[0]) / (volume + 1e-6)
    hl_spread = (df['high'] - df['low']).values / close
    pressure = (close - df['low']) / (df['high'] - df['low'] + 1e-6)
    
    # 划分训练集（最后 6000 个周期作为样本外测试）
    train_slice = slice(10000, 25000)
    features_train = [
        close[train_slice], volume[train_slice], ret[train_slice],
        vol_chg[train_slice], hl_spread[train_slice], pressure[train_slice]
    ]
    ret_train = ret[train_slice]
    
    toolbox.register("evaluate_train", evaluate_strategy, features=features_train, ret_series=ret_train)
    toolbox.register("evaluate", toolbox.evaluate_train)
    
    pop = toolbox.population(n=60)
    hof = tools.HallOfFame(3)
    
    print(">>> 启动 AlphaEvolve 遗传规划进化循环 (Generations: 15)...")
    CXPB, MUTPB, NGEN = 0.6, 0.3, 15
    
    # 评估初代种群
    fitnesses = list(map(toolbox.evaluate, pop))
    for ind, fit in zip(pop, fitnesses):
        ind.fitness.values = fit
    
    for gen in range(1, NGEN + 1):
        offspring = toolbox.select(pop, len(pop))
        offspring = list(map(toolbox.clone, offspring))
        
        for child1, child2 in zip(offspring[::2], offspring[1::2]):
            if random.random() < CXPB:
                toolbox.mate(child1, child2)
                del child1.fitness.values
                del child2.fitness.values
                
        for mutant in offspring:
            if random.random() < MUTPB:
                toolbox.mutate(mutant)
                del mutant.fitness.values
                
        invalid_ind = [ind for ind in offspring if not ind.fitness.valid]
        fitnesses = map(toolbox.evaluate, invalid_ind)
        for ind, fit in zip(invalid_ind, fitnesses):
            ind.fitness.values = fit
            
        pop[:] = offspring
        hof.update(pop)
        best = hof[0]
        print(f"Gen {gen:02d} | 最佳个体 Fitness: {best.fitness.values[0]:.4f} | 基因树大小: {len(best)}")
        
    print("\n================== 演化收敛完成 ==================")
    best_ind = hof[0]
    print("最优策略语法树 AST:")
    print(best_ind)
    
    with open('/home/da/桌面/ethAI/strategy_engine/best_strategy_ast.txt', 'w') as f:
        f.write(str(best_ind))
    print(">>> 最优策略已持久化到 best_strategy_ast.txt")

if __name__ == "__main__":
    run_evolution()
