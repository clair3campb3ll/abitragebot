#!/usr/bin/env python3
"""
Crypto Arbitrage Trading Bot (Paper Trading) - Menu Mode
- CLI based
- Option 1: Simulated venues (random-walk prices)
- Option 2: Real-time venues (Coinbase + Bitstamp) ONLY if inside trading window
- Simulates balances and trades, logs all trades to a logfile, outputs CSV + terminal report
"""

from __future__ import annotations

import argparse, csv, json, random, signal, time
from dataclasses import dataclass, asdict
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

# DATA STRUCTURES

@dataclass
class VenueBalances:
    usd: float
    xrp: float


@dataclass
class Trade:
    ts: str
    buy_venue: str
    sell_venue: str
    buy_price: float
    sell_price: float
    usd_spent: float
    xrp_bought: float
    fees_usd_est: float
    pnl_usd: float


# Exception
class PriceFeedError(Exception):
    """Raised when a venue price cannot be fetched or parsed."""


# VENUE IMPLEMENTATIONS

class Venue:
    name: str

    def fetch_price(self) -> float:
        raise NotImplementedError


class CoinbaseVenue(Venue):
    # Connects to real-time data feed from Coinbase API for XRP-USD spot price
    name = "COINBASE"

    def __init__(self, session: requests.Session, timeout_s: float = 5.0):
        self.session = session
        self.timeout_s = timeout_s
        self.url = "https://api.coinbase.com/v2/prices/XRP-USD/spot"

    def fetch_price(self) -> float:
        try:
            r = self.session.get(self.url, timeout=self.timeout_s)
            r.raise_for_status()
            data = r.json()
            return float(data["data"]["amount"])
        except Exception as e:
            raise PriceFeedError(f"{self.name} price fetch failed: {e}") from e


class BitstampVenue(Venue):
    # Connects to real-time data feed from Bitstamp API for XRP-USD spot price
    name = "BITSTAMP"

    def __init__(self, session: requests.Session, timeout_s: float = 5.0):
        self.session = session
        self.timeout_s = timeout_s
        self.url = "https://www.bitstamp.net/api/v2/ticker/xrpusd/"

    def fetch_price(self) -> float:
        try:
            r = self.session.get(self.url, timeout=self.timeout_s)
            r.raise_for_status()
            data = r.json()
            return float(data["last"])
        except Exception as e:
            raise PriceFeedError(f"{self.name} price fetch failed: {e}") from e

# SIMULATED VENUE FOR TESTING (RANDOM WALK)
class SimulatedVenue(Venue):
    """
    Simulated venue using a random walk around a base price.
    - Each venue can have a small bias/spread so mispricings happen sometimes.
    """
    def __init__(
        self,
        name: str,
        start_price: float = 1.30,
        drift: float = 0.0,
        volatility: float = 0.002,  
        venue_bias: float = 0.0,     # constant +/- adjustment
        seed: int | None = None
    ):
        self.name = name
        self.price = start_price
        self.drift = drift
        self.volatility = volatility
        self.venue_bias = venue_bias
        self.rng = random.Random(seed)

    def fetch_price(self) -> float:
        # Random walk: price *= (1 + drift + noise)
        noise = self.rng.uniform(-self.volatility, self.volatility)
        self.price *= (1.0 + self.drift + noise)

        # Can't go negative
        self.price = max(self.price, 0.0001)

        # Venue bias can create small consistent differences between venues
        return float(self.price * (1.0 + self.venue_bias))


# TIME UTILITIES

JHB_TZ = ZoneInfo("Africa/Johannesburg")

def now_jhb() -> datetime:
    return datetime.now(tz=JHB_TZ)

def in_trading_window(start_hhmm: str, end_hhmm: str, now: datetime | None = None) -> bool:
    # Checks if current time in JHB is within the specified window
    now = now or now_jhb()
    sh, sm = map(int, start_hhmm.split(":"))
    eh, em = map(int, end_hhmm.split(":"))
    start_t = dtime(sh, sm)
    end_t = dtime(eh, em)
    return start_t <= now.time() <= end_t

def append_log(logfile: str, record: dict) -> None:
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# OUTPUT (CSV + report)

def write_trades_csv(csvfile: str, trades: list[Trade]) -> None:
    path = Path(csvfile)
    fieldnames = [
        "ts", "buy_venue", "sell_venue",
        "buy_price", "sell_price",
        "usd_spent", "xrp_bought",
        "fees_usd_est", "pnl_usd"
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for t in trades:
            w.writerow(asdict(t))

def print_end_of_day_table(trades: list[Trade]) -> None:
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
        ("PnL(USD)", 10, lambda t: f"{t.pnl_usd:.4f}"),
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
    avg_pnl = total_pnl / len(trades)
    print(f"Trades: {len(trades)}")
    print(f"Total P/L (USD): {total_pnl:.4f}")
    print(f"Avg P/L per trade (USD): {avg_pnl:.4f}")
    print(line("="))


# TRADING

def estimate_fees_usd(usd_notional: float, buy_fee_pct: float, sell_fee_pct: float) -> float:
    # Estimates total fees in USD for a trade of the given amount and fee percentages
    return usd_notional * (buy_fee_pct + sell_fee_pct) 

def simulate_buy(bal: VenueBalances, usd_to_spend: float, price: float, fee_pct: float) -> tuple[VenueBalances, float]:
    # Simulates buying XRP with USD on a venue, accounting for fees and balance limits
    if usd_to_spend <= 0:
        return bal, 0.0

    fee = usd_to_spend * fee_pct
    total_cost = usd_to_spend + fee

    if total_cost > bal.usd:
        usd_to_spend = max(0.0, bal.usd / (1.0 + fee_pct))
        fee = usd_to_spend * fee_pct
        total_cost = usd_to_spend + fee

    xrp = usd_to_spend / price
    return VenueBalances(usd=bal.usd - total_cost, xrp=bal.xrp + xrp), xrp

def simulate_sell(bal: VenueBalances, xrp_to_sell: float, price: float, fee_pct: float) -> tuple[VenueBalances, float]:
    # Simulates selling XRP for USD on a venue, accounting for fees and balance limits
    if xrp_to_sell <= 0:
        return bal, 0.0

    if xrp_to_sell > bal.xrp:
        xrp_to_sell = bal.xrp

    gross = xrp_to_sell * price
    fee = gross * fee_pct
    net = gross - fee
    return VenueBalances(usd=bal.usd + net, xrp=bal.xrp - xrp_to_sell), net


# SELECT MODE (SIMULATED vs LIVE)

def choose_mode_interactive() -> str:
    print("Choose mode:")
    print("  1) Simulated venues (random-walk prices)")
    print("  2) Real-time venues via API (Coinbase + Bitstamp) (only trades inside window)")
    while True:
        choice = input("Enter 1 or 2: ").strip()
        if choice == "1":
            return "sim"
        if choice == "2":
            return "live"
        print("Invalid choice. Please enter 1 or 2.")


# MAIN

STOP = False

def _handle_sigint(signum, frame):
    global STOP
    STOP = True

def main():
    # Command-line arguments
    parser = argparse.ArgumentParser(description="Paper crypto arbitrage bot (XRP-USD) with sim/live mode selection.")
    parser.add_argument("--capital", type=float, default=1000.0)
    parser.add_argument("--poll", type=float, default=3.0)
    parser.add_argument("--trade-usd", type=float, default=100.0)
    parser.add_argument("--min-edge", type=float, default=0.003)   # 0.3%
    parser.add_argument("--buy-fee", type=float, default=0.0015)    # 0.15%
    parser.add_argument("--sell-fee", type=float, default=0.0015)
    parser.add_argument("--start", type=str, default="09:00")
    parser.add_argument("--end", type=str, default="16:50")
    parser.add_argument("--logfile", type=str, default="trades.log")
    parser.add_argument("--csvfile", type=str, default="trades.csv")
    parser.add_argument("--mode", type=str, choices=["sim", "live"], default=None,
                        help="Optional: skip menu and choose 'sim' or 'live' directly.")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_sigint)

    mode = args.mode or choose_mode_interactive()

    # Split starting capital across venues
    half = args.capital / 2.0
    balances = {
        "VENUE_A": VenueBalances(usd=half, xrp=0.0),
        "VENUE_B": VenueBalances(usd=half, xrp=0.0),
    }

    trades: list[Trade] = []

    # Build venues depending on mode
    if mode == "live":
        session = requests.Session()
        venues: list[Venue] = [CoinbaseVenue(session), BitstampVenue(session)]
        balances = {
            "COINBASE": VenueBalances(usd=half, xrp=0.0),
            "BITSTAMP": VenueBalances(usd=half, xrp=0.0),
        }
        print("\nMode: REAL-TIME API (Coinbase + Bitstamp)")
    else:
        # Simulated - give each venue a slight bias so opportunities exist sometimes
        v1 = SimulatedVenue("SIM_A", start_price=1.30, volatility=0.003, venue_bias=-0.0005, seed=1)
        v2 = SimulatedVenue("SIM_B", start_price=1.30, volatility=0.003, venue_bias=+0.0005, seed=2)
        venues = [v1, v2]
        balances = {
            "SIM_A": VenueBalances(usd=half, xrp=0.0),
            "SIM_B": VenueBalances(usd=half, xrp=0.0),
        }
        print("\nMode: SIMULATED VENUES")

    # Log START
    append_log(args.logfile, {
        "event": "START",
        "ts": now_jhb().isoformat(),
        "mode": mode,
        "params": vars(args),
        "initial_balances": {k: asdict(v) for k, v in balances.items()},
    })

    print("\n=== XRP-USD Arbitrage Bot (Paper Trading) ===")
    print(f"Trading window (JHB): {args.start} -> {args.end}")
    print("Press Ctrl+C to stop.\n")

    # if LIVE mode and outside window: doesn't run
    # if SIM mode: allow running anytime 
    if mode == "live" and not in_trading_window(args.start, args.end):
        n = now_jhb()
        print(f"[{n.strftime('%H:%M:%S')}] Outside trading window. Live mode will not trade.")
        print("Tip: run during the window or use simulated mode.")
        # END + summary output (no trades)
        end_ts = now_jhb().isoformat()
        append_log(args.logfile, {
            "event": "END",
            "ts": end_ts,
            "mode": mode,
            "trade_count": 0,
            "total_pnl_usd": 0.0,
            "final_balances": {k: asdict(v) for k, v in balances.items()},
        })
        write_trades_csv(args.csvfile, trades)
        print("\n=== SESSION SUMMARY ===")
        print("Trades executed: 0")
        print("Total P/L (USD): 0.0000")
        for k, v in balances.items():
            print(f"  {k}: USD={v.usd:.4f}, XRP={v.xrp:.6f}")
        print(f"\nLogfile written to: {args.logfile}")
        print(f"CSV written to:     {args.csvfile}")
        return

    print("Trading started.\n")

    while not STOP and (mode == "sim" or in_trading_window(args.start, args.end)):
        # Fetch prices from venues, handle errors, log price fetch failures
        ts = now_jhb().isoformat()

        prices: dict[str, float] = {}
        try:
            for v in venues:
                prices[v.name] = v.fetch_price()
        except PriceFeedError as e:
            append_log(args.logfile, {"event": "PRICE_ERROR", "ts": ts, "error": str(e)})
            time.sleep(args.poll)
            continue

        # Pick buy/sell venues by cheapest/most expensive
        sorted_by_price = sorted(prices.items(), key=lambda kv: kv[1])
        buy_v, buy_price = sorted_by_price[0]
        sell_v, sell_price = sorted_by_price[-1]

        edge = (sell_price - buy_price) / buy_price  # threshold logic
        fees_est = estimate_fees_usd(args.trade_usd, args.buy_fee, args.sell_fee)

        print(
            f"[{now_jhb().strftime('%H:%M:%S')}] "
            f"{' | '.join(f'{k}={v:.6f}' for k, v in prices.items())} | "
            f"Buy {buy_v} @ {buy_price:.6f} -> Sell {sell_v} @ {sell_price:.6f} | "
            f"edge={edge*100:.3f}%   ",
            end="\r"
        )

        if edge > args.min_edge: # only trade if edge exceeds threshold
            
            if balances[buy_v].usd <= 1.0:
                append_log(args.logfile, {
                    "event": "SKIP",
                    "ts": ts,
                    "reason": "Insufficient USD on buy venue",
                    "buy_venue": buy_v,
                    "sell_venue": sell_v
                })
                time.sleep(args.poll)
                continue

            usd_to_use = min(args.trade_usd, balances[buy_v].usd)

            pre_buy = balances[buy_v]
            # Simulate buy and update balances
            balances[buy_v], xrp_bought = simulate_buy(pre_buy, usd_to_use, buy_price, args.buy_fee)

            # Instant transfer
            balances[sell_v].xrp += xrp_bought

            pre_sell = balances[sell_v]
            balances[sell_v], usd_received = simulate_sell(pre_sell, xrp_bought, sell_price, args.sell_fee)

            pnl = usd_received - usd_to_use

            trade = Trade(
                ts=ts,
                buy_venue=buy_v,
                sell_venue=sell_v,
                buy_price=buy_price,
                sell_price=sell_price,
                usd_spent=usd_to_use,
                xrp_bought=xrp_bought,
                fees_usd_est=fees_est,
                pnl_usd=pnl
            )
            trades.append(trade)

            append_log(args.logfile, {
                "event": "TRADE",
                **asdict(trade),
                "mode": mode,
                "balances": {k: asdict(v) for k, v in balances.items()},
            })

        time.sleep(args.poll)

    # End / summary
    end_ts = now_jhb().isoformat()
    total_pnl = sum(t.pnl_usd for t in trades)

    append_log(args.logfile, {
        "event": "END",
        "ts": end_ts,
        "mode": mode,
        "trade_count": len(trades),
        "total_pnl_usd": total_pnl,
        "final_balances": {k: asdict(v) for k, v in balances.items()},
    })

    write_trades_csv(args.csvfile, trades)

    print("\n\n=== SESSION SUMMARY ===")
    print(f"Mode: {mode}")
    print(f"Trades executed: {len(trades)}")
    print(f"Total P/L (USD): {total_pnl:.4f}")
    print("Final balances:")
    for k, v in balances.items():
        print(f"  {k}: USD={v.usd:.4f}, XRP={v.xrp:.6f}")

    print_end_of_day_table(trades)

    print(f"\nLogfile written to: {args.logfile}")
    print(f"CSV written to:     {args.csvfile}")


if __name__ == "__main__":
    main()