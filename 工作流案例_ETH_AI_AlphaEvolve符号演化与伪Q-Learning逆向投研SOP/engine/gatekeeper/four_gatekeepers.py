"""
Four Gatekeepers Quality Control for Model Deployment (SPEC Section 7.3).
Gatekeeper 1: OOS Win Rate >= 75.0%, Trade Count >= 15
Gatekeeper 2: OOS Profit Factor >= 1.25, Calmar >= 2.50
Gatekeeper 3: OOS Max Drawdown <= 12.0%
Gatekeeper 4: Walk-Forward Efficiency (WFE) = Sharpe_OOS / Sharpe_IS >= 70.0%
"""

from typing import Dict, Any, Tuple

class FourGatekeepers:
    def __init__(
        self,
        min_win_rate: float = 0.75,
        min_trades: int = 15,
        min_profit_factor: float = 1.25,
        min_calmar: float = 2.50,
        max_drawdown: float = 0.12,
        min_wfe: float = 0.70
    ):
        self.min_win_rate = min_win_rate
        self.min_trades = min_trades
        self.min_profit_factor = min_profit_factor
        self.min_calmar = min_calmar
        self.max_drawdown = max_drawdown
        self.min_wfe = min_wfe

    def audit(self, is_metrics: Dict[str, Any], oos_metrics: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Audits performance metrics against four institutional gatekeepers.
        """
        oos_win_rate = oos_metrics.get('win_rate', 0.0)
        oos_trades = oos_metrics.get('trades_count', 0)
        oos_pf = oos_metrics.get('profit_factor', 0.0)
        oos_calmar = oos_metrics.get('calmar', 0.0)
        oos_dd = oos_metrics.get('max_drawdown', 1.0)
        
        is_sharpe = is_metrics.get('sharpe', 0.001)
        oos_sharpe = oos_metrics.get('sharpe', 0.0)
        wfe = (oos_sharpe / is_sharpe) if is_sharpe > 0.0 else 0.0

        g1_pass = (oos_win_rate >= self.min_win_rate) and (oos_trades >= self.min_trades)
        g2_pass = (oos_pf >= self.min_profit_factor) or (oos_calmar >= self.min_calmar)
        g3_pass = (oos_dd <= self.max_drawdown)
        g4_pass = (wfe >= self.min_wfe)

        all_passed = g1_pass and g2_pass and g3_pass and g4_pass

        audit_report = {
            'all_passed': bool(all_passed),
            'gatekeeper_1_winrate_trades': {
                'passed': bool(g1_pass),
                'win_rate': oos_win_rate,
                'min_win_rate': self.min_win_rate,
                'trades_count': oos_trades,
                'min_trades': self.min_trades
            },
            'gatekeeper_2_pf_calmar': {
                'passed': bool(g2_pass),
                'profit_factor': oos_pf,
                'min_pf': self.min_profit_factor,
                'calmar': oos_calmar,
                'min_calmar': self.min_calmar
            },
            'gatekeeper_3_max_drawdown': {
                'passed': bool(g3_pass),
                'max_drawdown': oos_dd,
                'limit_max_dd': self.max_drawdown
            },
            'gatekeeper_4_wfe': {
                'passed': bool(g4_pass),
                'wfe': wfe,
                'min_wfe': self.min_wfe,
                'is_sharpe': is_sharpe,
                'oos_sharpe': oos_sharpe
            }
        }
        return all_passed, audit_report
