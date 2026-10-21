from nautilus_trader.trading.strategy import Strategy
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
