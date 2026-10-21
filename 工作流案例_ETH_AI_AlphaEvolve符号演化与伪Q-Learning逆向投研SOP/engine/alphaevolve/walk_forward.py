"""
Purged & Embargoed Walk-Forward Optimization (WFO) Matrix Generator.
Based on Deep Research findings (Purged Cross-Validation / López de Prado):
- In-Sample (IS): e.g. 90 days (8,640 bars of 15m)
- Purge Buffer: 20 bars (removes overlapping event / label horizon)
- Out-of-Sample (OOS): e.g. 30 days (2,880 bars of 15m)
- Embargo Buffer: 10 bars (removes post-event serial correlation)
- Step Size: 30 days forward (2,880 bars)
Strict physical isolation preventing serial correlation leakage across temporal folds.
"""

from typing import List, Dict, Tuple

class PurgedWalkForwardMatrix:
    def __init__(
        self,
        is_bars: int = 8640,
        oos_bars: int = 2880,
        step_bars: int = 2880,
        purge_bars: int = 20,
        embargo_bars: int = 10
    ):
        self.is_bars = is_bars
        self.oos_bars = oos_bars
        self.step_bars = step_bars
        self.purge_bars = purge_bars
        self.embargo_bars = embargo_bars

    def split(self, total_bars: int) -> List[Dict[str, Tuple[int, int]]]:
        """
        Generates purged and embargoed slice indices:
        - IS: [is_start, is_end]
        - Purge: [is_end, is_end + purge_bars] (physically excluded)
        - OOS: [oos_start, oos_end] where oos_start = is_end + purge_bars
        - Embargo: [oos_end, oos_end + embargo_bars] (excluded before next IS)
        """
        slices = []
        start = 0
        min_required = self.is_bars + self.purge_bars + self.oos_bars
        
        while start + min_required <= total_bars:
            is_start = start
            is_end = is_start + self.is_bars
            
            oos_start = is_end + self.purge_bars
            oos_end = oos_start + self.oos_bars
            
            if oos_end > total_bars:
                break
                
            slices.append({
                'is': (is_start, is_end),
                'purge_buffer': (is_end, oos_start),
                'oos': (oos_start, oos_end),
                'embargo_buffer': (oos_end, min(oos_end + self.embargo_bars, total_bars))
            })
            start += self.step_bars
            
        return slices
