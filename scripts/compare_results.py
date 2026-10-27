#!/usr/bin/env python3
"""Compare experiment metrics between two runs."""
import json
from pathlib import Path

def load_metrics(path: Path) -> dict:
    return json.loads(path.read_text())

def main(exp1: str, exp2: str):
    m1 = load_metrics(Path(f"quant-research-constitution/experiments/{exp1}/metrics.json"))
    m2 = load_metrics(Path(f"quant-research-constitution/experiments/{exp2}/metrics.json"))

    print(f"Comparing {exp1} vs {exp2}:")
    for key in ["cumulative_pnl_pct", "win_rate", "total_trades"]:
        v1 = m1.get(key)
        v2 = m2.get(key)
        status = "✅" if v1 == v2 else "❌"
        print(f"{status} {key}: {v1} → {v2}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python compare_results.py exp_001 exp_002")
        exit(1)
    main(sys.argv[1], sys.argv[2])
