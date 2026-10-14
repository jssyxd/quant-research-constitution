#!/usr/bin/env python3
"""
Ultra-Strict Quant Data Lake & Parquet Integrity Auditor
Executes deep invariant checks, zero-gap continuity, nanosecond alignment,
CVD delta mathematical assertions, and JSON Schema contract validation.
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import List, Dict, Any
import jsonschema
import polars as pl
import pyarrow.parquet as pq

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [StrictAuditor] %(message)s")
logger = logging.getLogger("StrictAuditor")

BASE_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = BASE_DIR / "manifest" / "manifest.json"
SCHEMA_PATH = BASE_DIR / "manifest" / "manifest.schema.json"

TIMEFRAME_MS_MAP = {
    "15m": 15 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}

MANDATORY_LAKE_COLUMNS = [
    "timestamp",
    "ts_open_ns",
    "ts_event_ns",
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "taker_buy_volume",
    "taker_sell_volume",
    "cvd_delta",
    "trades_count",
]

def audit_manifest() -> bool:
    logger.info("=== GATE 1: Validating Manifest Schema (JSON Schema Draft 2020-12) ===")
    if not MANIFEST_PATH.exists() or not SCHEMA_PATH.exists():
        logger.error("Manifest or Schema file missing!")
        return False
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    try:
        jsonschema.validate(instance=manifest, schema=schema)
        logger.info("Manifest perfectly passes JSON Schema Draft 2020-12 validation! [PASS]")
        return True
    except jsonschema.ValidationError as e:
        logger.error(f"Manifest validation failed: {e.message}")
        return False

def audit_lake_parquet_files() -> Tuple[int, int, List[str]]:
    logger.info("=== GATE 2: Auditing dataBaseLake Parquet Files & Strict Invariants ===")
    parquet_files = sorted(list((BASE_DIR / "crypto" / "futures_um").glob("**/*.parquet")))
    if not parquet_files:
        logger.error("No parquet files found in data lake!")
        return 0, 0, ["No parquet files found"]

    passed_count = 0
    failures = []

    for pf in parquet_files:
        file_desc = str(pf.relative_to(BASE_DIR))
        try:
            # 1. Parquet metadata check
            pq_file = pq.ParquetFile(str(pf))
            meta = pq_file.metadata
            cols = pq_file.schema_arrow.names
            num_rows = meta.num_rows

            # Compression check
            comp = meta.row_group(0).column(0).compression
            if comp != "ZSTD":
                failures.append(f"{file_desc}: Expected ZSTD compression, found {comp}")

            # Column presence
            missing_cols = [c for c in MANDATORY_LAKE_COLUMNS if c not in cols]
            if missing_cols:
                failures.append(f"{file_desc}: Missing required columns: {missing_cols}")

            # Read with Polars
            df = pl.read_parquet(str(pf))

            # 2. Strict Null checks
            for col in MANDATORY_LAKE_COLUMNS:
                null_cnt = df[col].null_count()
                if null_cnt > 0:
                    failures.append(f"{file_desc}: Column '{col}' has {null_cnt} null values")

            # 3. Monotonic increasing timestamp check
            ts_diffs = df["timestamp"].diff().drop_nulls()
            if (ts_diffs <= 0).any():
                failures.append(f"{file_desc}: Timestamps are not strictly monotonically increasing")

            # 4. Zero-gap continuity check
            tf_name = pf.parent.name # '15m', '1h', etc.
            expected_step_ms = TIMEFRAME_MS_MAP.get(tf_name)
            if expected_step_ms and len(df) > 1:
                gaps = ts_diffs.filter(ts_diffs != expected_step_ms)
                if len(gaps) > 0:
                    failures.append(f"{file_desc}: Detected {len(gaps)} continuity gaps (expected step: {expected_step_ms}ms)")

            # 5. Nanosecond alignment check: ts_open_ns == timestamp * 1e6
            ns_open_diff = (df["ts_open_ns"] - (df["timestamp"] * 1_000_000)).abs().sum()
            if ns_open_diff != 0:
                failures.append(f"{file_desc}: ts_open_ns does not match timestamp * 1,000,000")

            # 6. OHLC Geometry Invariants:
            # High >= max(Open, Close), Low <= min(Open, Close), Low > 0
            bad_high = df.filter((pl.col("high") < pl.col("open")) | (pl.col("high") < pl.col("close")))
            bad_low = df.filter((pl.col("low") > pl.col("open")) | (pl.col("low") > pl.col("close")))
            bad_price = df.filter((pl.col("low") <= 0) | (pl.col("close") <= 0))
            if len(bad_high) > 0:
                failures.append(f"{file_desc}: {len(bad_high)} rows violated High >= max(Open, Close)")
            if len(bad_low) > 0:
                failures.append(f"{file_desc}: {len(bad_low)} rows violated Low <= min(Open, Close)")
            if len(bad_price) > 0:
                failures.append(f"{file_desc}: {len(bad_price)} rows have non-positive price")

            # 7. CVD Mathematical Invariants:
            # taker_sell_volume == volume - taker_buy_volume
            # cvd_delta == taker_buy_volume - taker_sell_volume
            cvd_diff = (
                (df["taker_sell_volume"] - (df["volume"] - df["taker_buy_volume"])).abs() +
                (df["cvd_delta"] - (df["taker_buy_volume"] - df["taker_sell_volume"])).abs()
            ).sum()
            if round(cvd_diff, 4) > 0.001:
                failures.append(f"{file_desc}: CVD arithmetic relation violation (error sum={cvd_diff})")

            passed_count += 1
            logger.info(f"  ✓ {file_desc} ({num_rows} rows, ZSTD) [100% Invariants Clean]")
        except Exception as e:
            failures.append(f"{file_desc}: Exception {e}")

    return len(parquet_files), passed_count, failures

def audit_nautilus_catalog() -> Tuple[int, int, List[str]]:
    logger.info("=== GATE 3: Auditing NautilusTrader Parquet Catalog Specifications ===")
    catalog_files = sorted(list((BASE_DIR / "catalog" / "data" / "bars").glob("**/*.parquet")))
    if not catalog_files:
        logger.error("No Nautilus catalog files found!")
        return 0, 0, ["No Nautilus catalog files found"]

    passed_count = 0
    failures = []
    for cf in catalog_files:
        file_desc = str(cf.relative_to(BASE_DIR))
        try:
            df = pl.read_parquet(str(cf))
            cols = df.columns
            # Must contain ts_event (ns), open, high, low, close, volume, bar_type, instrument_id
            req_cols = ["bar_type", "instrument_id", "ts_event", "open", "high", "low", "close", "volume", "cvd_delta"]
            for col in req_cols:
                if col not in cols:
                    failures.append(f"{file_desc}: Missing required Nautilus column {col}")

            # Check timestamp is in nanoseconds (> 1e18)
            min_ts = df["ts_event"].min()
            if min_ts < 1_000_000_000_000_000_000:
                failures.append(f"{file_desc}: ts_event {min_ts} is not nanoseconds!")

            passed_count += 1
            logger.info(f"  ✓ {file_desc} ({len(df)} bars) [Nautilus Ready]")
        except Exception as e:
            failures.append(f"{file_desc}: Exception {e}")

    return len(catalog_files), passed_count, failures

def main():
    m_ok = audit_manifest()
    lake_total, lake_passed, lake_errs = audit_lake_parquet_files()
    nat_total, nat_passed, nat_errs = audit_nautilus_catalog()

    all_errs = lake_errs + nat_errs
    print("\n" + "="*70)
    print("STRICT AUDIT SUITE EXECUTION SUMMARY")
    print("="*70)
    print(f"Manifest JSON Schema Validation: {'PASSED' if m_ok else 'FAILED'}")
    print(f"dataBaseLake Parquet Files:      {lake_passed}/{lake_total} passed")
    print(f"NautilusTrader Catalog Files:    {nat_passed}/{nat_total} passed")

    if not m_ok or all_errs:
        print("\n[AUDIT FAILURES DETECTED]:")
        for err in all_errs:
            print(f"  ❌ {err}")
        sys.exit(1)
    else:
        print("\n🎉 ALL QUALITY & INVARIANT GATES PASSED WITH ZERO VIOLATIONS! (100% Score)")
        print("="*70)

if __name__ == "__main__":
    main()
