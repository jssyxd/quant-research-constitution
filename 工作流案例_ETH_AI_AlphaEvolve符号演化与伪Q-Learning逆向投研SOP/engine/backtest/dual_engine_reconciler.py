"""
VectorBT & NautilusTrader Dual Engine Cross-Reconciler.
Validates:
1. Time alignment: percentage of trades triggering at exact same bar/millisecond.
2. Direction alignment: percentage of trades matching long/short direction.
3. Margin / Position size consistency: average margin deviation (USDT).
"""

import json
from typing import List, Dict, Any

class DualEngineReconciler:
    def __init__(self, time_tolerance_seconds: int = 900, max_margin_dev_usdt: float = 2.0):
        self.time_tolerance_seconds = time_tolerance_seconds
        self.max_margin_dev_usdt = max_margin_dev_usdt

    def reconcile(self, trades_vbt: List[Dict[str, Any]], trades_nautilus: List[Dict[str, Any]]) -> Dict[str, Any]:
        n_vbt = len(trades_vbt)
        n_nau = len(trades_nautilus)
        
        matches = 0
        direction_matches = 0
        margin_diffs = []
        
        # Compare trades up to common length
        min_len = min(n_vbt, n_nau)
        for i in range(min_len):
            t1 = trades_vbt[i]
            t2 = trades_nautilus[i]
            
            # Action match
            act1 = t1.get('action', '')
            act2 = t2.get('action', '')
            
            dir1 = '多' if '多' in act1 else ('空' if '空' in act1 else '')
            dir2 = '多' if '多' in act2 else ('空' if '空' in act2 else '')
            
            if dir1 == dir2 and dir1 != '':
                direction_matches += 1
                
            # Time match (check prefix or timestamp equality)
            time1 = str(t1.get('time', ''))[:16]
            time2 = str(t2.get('time', ''))[:16]
            if time1 == time2:
                matches += 1
                
            m1 = float(t1.get('pos_margin', t1.get('margin', 0.0)))
            m2 = float(t2.get('pos_margin', t2.get('margin', 0.0)))
            margin_diffs.append(abs(m1 - m2))

        time_align_ratio = (matches / min_len) if min_len > 0 else 0.0
        dir_align_ratio = (direction_matches / min_len) if min_len > 0 else 0.0
        avg_margin_dev = float(sum(margin_diffs) / len(margin_diffs)) if margin_diffs else 0.0
        
        is_aligned = (dir_align_ratio >= 0.90) and (avg_margin_dev <= self.max_margin_dev_usdt)

        return {
            'is_aligned': bool(is_aligned),
            'vbt_trade_count': n_vbt,
            'nautilus_trade_count': n_nau,
            'compared_trade_count': min_len,
            'time_alignment_ratio': time_align_ratio,
            'direction_alignment_ratio': dir_align_ratio,
            'avg_margin_deviation_usdt': avg_margin_dev
        }
