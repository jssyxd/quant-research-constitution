#!/usr/bin/env python3
"""
OKX 15m Candlestick Crawler
Fetches recent 14-day 15-minute historical K-line data for perpetual contracts.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx

DEFAULT_SYMBOLS = [
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
    "BNB-USDT-SWAP",
    "SOL-USDT-SWAP",
]
BASE_URL = "https://www.okx.com"
ENDPOINT = "/api/v5/market/history-candles"
INTERVAL = "15m"
INTERVAL_MS = 15 * 60 * 1000

def fetch_symbol_candles(
    client: httpx.Client,
    symbol: str,
    target_count: int = 1344,
    bar: str = "15m",
) -> List[List[str]]:
    """
    Fetch at least `target_count` completed candles using pagination.
    OKX returns data newest first.
    """
    candles: List[List[str]] = []
    after_cursor: Optional[str] = None
    max_retries = 5
    page = 1

    print(f"[{symbol}] Starting fetch, target = {target_count} bars (14 days)...")

    while len(candles) < target_count + 5:
        url = f"{BASE_URL}{ENDPOINT}"
        params: Dict[str, Any] = {
            "instId": symbol,
            "bar": bar,
            "limit": "100",
        }
        if after_cursor:
            params["after"] = after_cursor

        retries = 0
        success = False
        while retries < max_retries:
            try:
                resp = client.get(url, params=params, timeout=15.0)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == "0":
                        batch = data.get("data", [])
                        if not batch:
                            print(f"[{symbol}] No more candles returned by API.")
                            success = True
                            break
                        candles.extend(batch)
                        # Last item in batch is the oldest in this page
                        after_cursor = batch[-1][0]
                        print(f"[{symbol}] Page {page}: fetched {len(batch)} bars (total so far: {len(candles)})")
                        page += 1
                        success = True
                        break
                    else:
                        print(f"[{symbol}] OKX API Error code {data.get('code')}: {data.get('msg')}")
                elif resp.status_code == 429:
                    print(f"[{symbol}] Rate limited (429), backing off...")
                    time.sleep(2.0 * (retries + 1))
                else:
                    print(f"[{symbol}] HTTP status {resp.status_code}, retrying...")
            except Exception as e:
                print(f"[{symbol}] Network error: {e}, retrying...")

            retries += 1
            time.sleep(1.0 * retries)

        if not success or not after_cursor:
            print(f"[{symbol}] Terminating pagination loop.")
            break

        # Respect OKX rate limit: ~10 requests per 2s -> 200ms sleep
        time.sleep(0.2)

    # Filter only confirmed candles (index 8 is confirm flag "1" or "0")
    # If the first candle is unconfirmed ("0"), remove it
    confirmed_candles = [c for c in candles if len(c) > 8 and c[8] == "1"]
    # De-duplicate by timestamp (index 0)
    seen_ts = set()
    deduped = []
    for c in confirmed_candles:
        ts = c[0]
        if ts not in seen_ts:
            seen_ts.add(ts)
            deduped.append(c)

    # Sort descending by ts first, then take target_count, then sort ascending
    deduped.sort(key=lambda x: int(x[0]), reverse=True)
    target_data = deduped[:target_count]
    # Reverse to chronological order (oldest to newest)
    target_data.sort(key=lambda x: int(x[0]))

    print(f"[{symbol}] Completed fetch. Total valid confirmed bars: {len(target_data)}")
    if target_data:
        start_dt = datetime.fromtimestamp(int(target_data[0][0]) / 1000, tz=timezone.utc).isoformat()
        end_dt = datetime.fromtimestamp(int(target_data[-1][0]) / 1000, tz=timezone.utc).isoformat()
        print(f"[{symbol}] Range: {start_dt} -> {end_dt}")

    return target_data

def main():
    parser = argparse.ArgumentParser(description="Fetch OKX 15m candlestick data")
    parser.add_argument("--symbols", type=str, default=",".join(DEFAULT_SYMBOLS), help="Comma separated symbol list")
    parser.add_argument("--days", type=int, default=14, help="Number of days (default: 14)")
    parser.add_argument("--output-dir", type=str, default="data/raw", help="Output directory for raw JSON")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    target_bars = args.days * 24 * 4  # 15m bars: 4 per hour

    os.makedirs(args.output_dir, exist_ok=True)

    headers = {
        "User-Agent": "Nautilus-Tardis-Pipeline/1.0",
        "Accept": "application/json",
    }
    # Optional OKX credentials if provided
    api_key = os.environ.get("OKX_API_KEY")
    if api_key:
        headers["OK-ACCESS-KEY"] = api_key

    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or os.environ.get("all_proxy") or os.environ.get("ALL_PROXY")
    if not proxy:
        proxy = "http://127.0.0.1:7897"

    with httpx.Client(headers=headers, proxy=proxy, timeout=20.0) as client:
        for symbol in symbols:
            candles = fetch_symbol_candles(client, symbol, target_count=target_bars, bar=INTERVAL)
            output_file = os.path.join(args.output_dir, f"{symbol}_raw.json")
            payload = {
                "symbol": symbol,
                "venue": "OKX",
                "bar": INTERVAL,
                "days": args.days,
                "count": len(candles),
                "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
                "data": candles,
            }
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            print(f"[{symbol}] Saved raw data to {output_file}\n")

if __name__ == "__main__":
    main()
