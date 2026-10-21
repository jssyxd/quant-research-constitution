import json

trades = [
    # Page 1
    {"time": "2026/10/18 05:30:00", "symbol": "ETHUSDT 永续", "type": "占可用保证金比例", "amount": "75.00%", "action": "多仓进场"},
    {"time": "2026/10/17 07:30:01", "symbol": "ETHUSDT 永续", "type": "占可用保证金比例", "amount": "50.00%", "action": "多仓进场"},
    {"time": "2026/10/16 19:12:54", "symbol": "ETHUSDT 永续", "type": "仓位离场", "amount": "100.00%", "action": "多仓离场"},
    {"time": "2026/10/16 13:15:00", "symbol": "ETHUSDT 永续", "type": "占可用保证金比例", "amount": "50.00%", "action": "多仓进场"},
    {"time": "2026/10/15 23:03:31", "symbol": "ETHUSDT 永续", "type": "仓位离场", "amount": "100.00%", "action": "多仓离场"},
    {"time": "2026/10/15 23:03:31", "symbol": "ETHUSDT 永续", "type": "仓位离场", "amount": "100.00%", "action": "多仓离场"},
    {"time": "2026/10/15 10:30:01", "symbol": "ETHUSDT 永续", "type": "占可用保证金比例", "amount": "75.00%", "action": "多仓进场"},
    {"time": "2026/10/15 06:15:01", "symbol": "ETHUSDT 永续", "type": "占可用保证金比例", "amount": "50.00%", "action": "多仓进场"},
    {"time": "2026/10/14 18:04:27", "symbol": "ETHUSDT 永续", "type": "仓位离场", "amount": "100.00%", "action": "空仓离场"},
    {"time": "2026/10/14 18:04:27", "symbol": "ETHUSDT 永续", "type": "仓位离场", "amount": "100.00%", "action": "空仓离场"},
    # Page 2
    {"time": "2026/10/13 12:30:01", "symbol": "ETHUSDT 永续", "type": "占可用保证金比例", "amount": "75.00%", "action": "空仓进场"},
    {"time": "2026/10/13 11:15:01", "symbol": "ETHUSDT 永续", "type": "占可用保证金比例", "amount": "50.00%", "action": "空仓进场"},
    {"time": "2026/10/12 20:34:36", "symbol": "ETHUSDT 永续", "type": "仓位离场", "amount": "100.00%", "action": "空仓离场"},
    {"time": "2026/10/12 12:45:01", "symbol": "ETHUSDT 永续", "type": "占可用保证金比例", "amount": "50.00%", "action": "空仓进场"},
    {"time": "2026/10/11 23:57:00", "symbol": "ETHUSDT 永续", "type": "仓位离场", "amount": "100.00%", "action": "多仓离场"},
    {"time": "2026/10/11 23:57:00", "symbol": "ETHUSDT 永续", "type": "仓位离场", "amount": "100.00%", "action": "多仓离场"},
    {"time": "2026/10/08 01:45:01", "symbol": "ETHUSDT 永续", "type": "占可用保证金比例", "amount": "75.00%", "action": "多仓进场"},
    {"time": "2026/10/07 22:00:01", "symbol": "ETHUSDT 永续", "type": "占可用保证金比例", "amount": "50.00%", "action": "多仓进场"},
    {"time": "2026/10/07 09:57:07", "symbol": "ETHUSDT 永续", "type": "仓位离场", "amount": "100.00%", "action": "空仓离场"},
    {"time": "2026/10/07 09:57:07", "symbol": "ETHUSDT 永续", "type": "仓位离场", "amount": "100.00%", "action": "空仓离场"},
    # Page 3
    {"time": "2026/10/04 16:00:01", "symbol": "ETHUSDT 永续", "type": "占可用保证金比例", "amount": "75.00%", "action": "空仓进场"}
]

with open('/home/da/桌面/ethAI/strategy_engine/okx_crawled_trades.json', 'w', encoding='utf-8') as f:
    json.dump(trades, f, ensure_ascii=False, indent=2)

print(f"成功保存 OKX 实盘触发记录，共 {len(trades)} 条！")
