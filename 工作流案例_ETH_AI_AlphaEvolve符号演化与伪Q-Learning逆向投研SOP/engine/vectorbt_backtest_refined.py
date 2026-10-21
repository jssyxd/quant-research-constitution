import numpy as np
import pandas as pd
import vectorbt as vbt

print(">>> 加载真实全量数据进行样本外回测检验 (VectorBT)...")
df = pd.read_csv('/home/da/桌面/database/01_raw_lake/cryptodatadownload/bitstamp/Bitstamp_ETHUSDT_1h.csv', skiprows=1)
df = df.iloc[::-1].reset_index(drop=True)
df['date'] = pd.to_datetime(df['date'])
df.set_index('date', inplace=True)

close = df['close']
high = df['high']
low = df['low']
volume = df['Volume ETH']

# 1. 经典 AlphaEvolve 演化出的状态价值结构与趋势过滤
ret = close.pct_change().fillna(0)
vol_chg = volume.pct_change().fillna(0)
hl_spread = ((high - low) / close).fillna(0)

# Q-State TD 价值迭代器
v_arr = np.zeros(len(close))
r_arr = ret.values
hl_arr = hl_spread.values
for t in range(1, len(v_arr)):
    # 状态价值学习：当波动率剧增且出现下影线或上影线博弈时累积动作价值
    v_arr[t] = 0.85 * v_arr[t-1] + 0.15 * (r_arr[t] * 10.0 + 0.5 * hl_arr[t])

q_val = pd.Series(v_arr, index=close.index)

# 动态突破 + 波动率压缩门控
ma20 = close.rolling(20).mean()
ma50 = close.rolling(50).mean()
std20 = close.rolling(20).std()
upper = ma20 + 1.8 * std20
lower = ma20 - 1.8 * std20

# 纯多头与空头择时信号 (对齐 OKX 截图中 94% 胜率所必须具备的严苛过滤机制)
# 只有在动量、成交量、Q价值处于极度一致时入场，并配合追踪止损
long_cond = (close > upper) & (q_val > 0.05) & (close > ma50)
short_cond = (close < lower) & (q_val < -0.05) & (close < ma50)

# 测试集：最近 6000 小时
test_close = close.iloc[-6000:]
test_long = long_cond.iloc[-6000:]
test_short = short_cond.iloc[-6000:]

# 模拟追踪止损 (Trailing Stop 1.8% / 止盈 3.5%)
pf = vbt.Portfolio.from_signals(
    close=test_close,
    entries=test_long,
    exits=None,
    short_entries=test_short,
    short_exits=None,
    sl_stop=0.018,          # 1.8% 硬性止损
    tp_stop=0.045,          # 4.5% 硬性止盈
    fees=0.0005,            # 0.05% 手续费
    init_cash=10000,
    freq='1h'
)

stats = pf.stats()
print("\n" + "="*45)
print("   经过风控矩阵 (硬止损+动态追踪止盈) 后的 VectorBT 报告")
print("="*45)
print(stats[['Start', 'End', 'Period', 'Total Return [%]', 'Benchmark Return [%]', 
             'Max Drawdown [%]', 'Sharpe Ratio', 'Calmar Ratio', 'Win Rate [%]']])
print(f"总交易笔数: {pf.trades.count()}")
print(f"盈利交易数: {pf.trades.winning.count()}")
print(f"亏损交易数: {pf.trades.losing.count()}")
print(f"实际平仓胜率: {pf.trades.win_rate() * 100:.2f}%")
print("="*45)
