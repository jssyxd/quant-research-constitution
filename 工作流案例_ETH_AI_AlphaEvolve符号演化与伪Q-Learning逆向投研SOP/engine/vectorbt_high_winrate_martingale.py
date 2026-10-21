import numpy as np
import pandas as pd
import vectorbt as vbt

print(">>> 模拟‘允许多次加仓’(75%委托)下的择时跟踪...")
df = pd.read_csv('/home/da/桌面/database/01_raw_lake/cryptodatadownload/bitstamp/Bitstamp_ETHUSDT_1h.csv', skiprows=1)
df = df.iloc[::-1].reset_index(drop=True)
df['date'] = pd.to_datetime(df['date'])
df.set_index('date', inplace=True)

close = df['close']
high = df['high']
low = df['low']
ret = close.pct_change().fillna(0)
hl_spread = ((high - low) / close).fillna(0)

# Q-Value 状态评价
v_arr = np.zeros(len(close))
r_arr = ret.values
hl_arr = hl_spread.values
for t in range(1, len(v_arr)):
    v_arr[t] = 0.90 * v_arr[t-1] + 0.10 * (r_arr[t] * 15.0 + 0.2 * hl_arr[t])
q_val = pd.Series(v_arr, index=close.index)

rsi = vbt.RSI.run(close, window=14).rsi.fillna(50)
ma20 = close.rolling(20).mean()
std20 = close.rolling(20).std()
zscore = (close - ma20) / (std20 + 1e-6)

# 严苛信号：低波回踩但Q状态积极
long_entry = (zscore < -1.5) & (q_val > -0.01) & (rsi < 40)
short_entry = (zscore > 1.5) & (q_val < 0.01) & (rsi > 60)

# 止盈：0.9% 快速止盈 (高频剥头皮高胜率)，止损 3.0%
test_close = close.iloc[-3000:]
test_long = long_entry.iloc[-3000:]
test_short = short_entry.iloc[-3000:]

pf = vbt.Portfolio.from_signals(
    close=test_close,
    entries=test_long,
    exits=None,
    short_entries=test_short,
    short_exits=None,
    tp_stop=0.009,       # 0.9% 止盈
    sl_stop=0.025,       # 2.5% 止损
    fees=0.0004,
    init_cash=10000,
    freq='1h'
)

stats = pf.stats()
print("\n" + "="*45)
print("     高频剥头皮 + Q-State 价值评估报告")
print("="*45)
print(stats[['Start', 'End', 'Period', 'Total Return [%]', 'Benchmark Return [%]', 
             'Max Drawdown [%]', 'Sharpe Ratio', 'Calmar Ratio', 'Win Rate [%]']])
print(f"总交易笔数: {pf.trades.count()}")
print(f"盈利交易数: {pf.trades.winning.count()}")
print(f"亏损交易数: {pf.trades.losing.count()}")
print(f"平仓胜率: {pf.trades.win_rate() * 100:.2f}%")
print("="*45)
