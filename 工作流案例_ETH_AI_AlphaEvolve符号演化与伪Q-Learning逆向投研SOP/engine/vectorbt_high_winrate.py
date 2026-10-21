import numpy as np
import pandas as pd
import vectorbt as vbt

print(">>> 加载真实全量数据...")
df = pd.read_csv('/home/da/桌面/database/01_raw_lake/cryptodatadownload/bitstamp/Bitstamp_ETHUSDT_1h.csv', skiprows=1)
df = df.iloc[::-1].reset_index(drop=True)
df['date'] = pd.to_datetime(df['date'])
df.set_index('date', inplace=True)

close = df['close']
high = df['high']
low = df['low']
volume = df['Volume ETH']

ret = close.pct_change().fillna(0)
hl_spread = ((high - low) / close).fillna(0)

# 1. 演化出的状态价值结构 (Q-Learning 状态价值评估)
v_arr = np.zeros(len(close))
r_arr = ret.values
hl_arr = hl_spread.values
for t in range(1, len(v_arr)):
    v_arr[t] = 0.88 * v_arr[t-1] + 0.12 * (r_arr[t] * 12.0 + 0.3 * hl_arr[t])
q_val = pd.Series(v_arr, index=close.index)

# 2. 动量与均线突破
rsi = vbt.RSI.run(close, window=14).rsi.fillna(50)
ma20 = close.rolling(20).mean()
std20 = close.rolling(20).std()
zscore = (close - ma20) / (std20 + 1e-6)

# 信号入场：高置信度极值反转或动量共振 (OKX 信号中半个月触发 16 次，平均每天 1 次)
long_entry = (zscore < -1.8) & (q_val > -0.02) & (rsi < 35)
short_entry = (zscore > 1.8) & (q_val < 0.02) & (rsi > 65)

# 平仓：动态回归均值或固定止盈止损
long_exit = close > ma20
short_exit = close < ma20

# 测试集：最近 200 天（约 4800 小时）
test_close = close.iloc[-4800:]
test_long = long_entry.iloc[-4800:]
test_short = short_entry.iloc[-4800:]
test_lexit = long_exit.iloc[-4800:]
test_sexit = short_exit.iloc[-4800:]

pf = vbt.Portfolio.from_signals(
    close=test_close,
    entries=test_long,
    exits=test_lexit,
    short_entries=test_short,
    short_exits=test_sexit,
    sl_stop=0.015,       # 1.5% 硬止损
    tp_stop=0.018,       # 1.8% 止盈
    fees=0.0005,
    init_cash=10000,
    freq='1h'
)

stats = pf.stats()
print("\n" + "="*45)
print("       高胜率均值回归+Q状态 VectorBT 报告")
print("="*45)
print(stats[['Start', 'End', 'Period', 'Total Return [%]', 'Benchmark Return [%]', 
             'Max Drawdown [%]', 'Sharpe Ratio', 'Calmar Ratio', 'Win Rate [%]']])
print(f"总交易笔数: {pf.trades.count()}")
print(f"盈利交易数: {pf.trades.winning.count()}")
print(f"亏损交易数: {pf.trades.losing.count()}")
print(f"胜率: {pf.trades.win_rate() * 100:.2f}%")
print("="*45)
