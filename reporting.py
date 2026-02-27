# reporting.py
from __future__ import annotations
import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import List
from models import Trade

def append_log(logfile: str, record: dict) -> None:
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

def write_trades_csv(csvfile: str, trades: List[Trade]) -> None:
    path = Path(csvfile)
    fieldnames = [
        "ts", "buy_venue", "sell_venue",
        "buy_price", "sell_price",
        "usd_spent", "xrp_bought",
        "fee_usd", "pnl_usd",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for t in trades:
            w.writerow(asdict(t))

def print_end_of_day_table(trades: List[Trade]) -> None:
    if not trades:
        print("\nNo trades executed today.")
        return

    cols = [
        ("Time", 8,  lambda t: t.ts[11:19]),
        ("Buy", 10,  lambda t: t.buy_venue),
        ("Sell", 10, lambda t: t.sell_venue),
        ("BuyPx", 10, lambda t: f"{t.buy_price:.6f}"),
        ("SellPx", 10, lambda t: f"{t.sell_price:.6f}"),
        ("USD", 10,  lambda t: f"{t.usd_spent:.2f}"),
        ("XRP", 12,  lambda t: f"{t.xrp_bought:.6f}"),
        ("Fee", 10,  lambda t: f"{t.fee_usd:.4f}"),
        ("PnL", 10,  lambda t: f"{t.pnl_usd:.4f}"),
    ]

    def line(ch="-"):
        return ch * (sum(w for _, w, _ in cols) + (len(cols) - 1) * 2)

    print("\n=== END-OF-DAY TRADE REPORT ===")
    print(line("="))
    print("  ".join(f"{name:<{width}}" for name, width, _ in cols))
    print(line("-"))
    for t in trades:
        print("  ".join(f"{fmt(t):<{width}}" for _, width, fmt in cols))
    print(line("-"))
    total_pnl = sum(t.pnl_usd for t in trades)
    print(f"Trades: {len(trades)}")
    print(f"Total P/L (USD): {total_pnl:.4f}")
    print(line("="))