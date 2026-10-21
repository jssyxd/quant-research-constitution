"""
Walk-Forward Optimization (WFO) Matrix Generator.
Default WFO Spec (Section 7.1):
- In-Sample (IS): 90 days (8,640 bars of 15m)
- Out-of-Sample (OOS): 30 days (2,880 bars of 15m)
- Step Size: 30 days forward (2,880 bars)
Strict isolation to prevent look-ahead bias across folds.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Tuple

class WalkForwardMatrix:
    def __init__(self, is_bars: int = 8640, oos_bars: int = 2880, step_bars: int = 2880):
        self.is_bars = is_bars
        self.oos_bars = oos_bars
        self.step_bars = step_bars

    def split(self, total_bars: int) -> List[Dict[str, Tuple[int, int]]]:
        """
        Generates slice indices [(is_start, is_end), (oos_start, oos_end)]
        """
        slices = []
        start = 0
        while start + self.is_bars + self.oos_bars <= total_bars:
            is_start = start
            is_end = is_start + self.is_bars
            oos_start = is_end
            oos_end = oos_start + self.oos_bars
            
            slices.append({
                'is': (is_start, is_end),
                'oos': (oos_start, oos_end)
            })
            start += self.step_bars
            
        return slices
