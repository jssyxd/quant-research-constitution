import os
import subprocess

print(">>> 检查 Docker 与 Nautilus Trader 环境...")
try:
    res = subprocess.run(["docker", "--version"], capture_output=True, text=True)
    print("Docker 版本:", res.stdout.strip())
except Exception as e:
    print("Docker 未运行或权限不足:", e)

# 编写 Nautilus Trader 仿真策略骨架
nautilus_strat = """from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.model.data import Bar
from nautilus_trader.model.instruments import InstrumentId

class EthAiAlphaEvolveStrategy(Strategy):
    def __init__(self, config):
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str("ETHUSDT-PERP.BINANCE")
        self.q_state = 0.0

    def on_bar(self, bar: Bar):
        # 实时计算 Q-State 时序差分价值
        ret = (bar.close - bar.open) / bar.open
        self.q_state = 0.90 * self.q_state + 0.10 * (float(ret) * 15.0)
        
        # 产生交易信号
        if self.q_state > 0.05:
            # 提交做多订单
            pass
        elif self.q_state < -0.05:
            # 提交做空订单
            pass
"""
with open("/home/da/桌面/ethAI/strategy_engine/nautilus_eth_strategy.py", "w") as f:
    f.write(nautilus_strat)
print(">>> Nautilus Trader 策略已生成在 strategy_engine/nautilus_eth_strategy.py")
