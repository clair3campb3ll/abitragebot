# trading.py
from __future__ import annotations
import argparse
import time
import signal
import requests

from models import VenueBalances
from venues import BitstampVenue, CoinGeckoVenue, SimulatedVenue, PriceFeedError
from bot import TradingBot, now_jhb, in_trading_window
from reporting import append_log, write_trades_csv, print_end_of_day_table

STOP = False

def _handle_sigint(signum, frame):
    global STOP
    STOP = True

def main():
    parser = argparse.ArgumentParser(description="XRP-USD Arbitrage Bot (paper trading) - neat version.")
    parser.add_argument("--mode", choices=["sim", "live"], default="sim")
    parser.add_argument("--capital", type=float, default=1000.0)
    parser.add_argument("--poll", type=float, default=3.0)
    parser.add_argument("--trade-usd", type=float, default=100.0)
    parser.add_argument("--min-edge", type=float, default=0.003)  # 0.3%
    parser.add_argument("--buy-fee", type=float, default=0.0015)   # 0.15%
    parser.add_argument("--sell-fee", type=float, default=0.0015)
    parser.add_argument("--start", type=str, default="09:00")
    parser.add_argument("--end", type=str, default="16:50")
    parser.add_argument("--logfile", type=str, default="trades.log")
    parser.add_argument("--csvfile", type=str, default="trades.csv")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_sigint)

    half = args.capital / 2.0

    # Build venues + balances depending on mode
    if args.mode == "live":
        # Enforce window for live mode
        if not in_trading_window(args.start, args.end):
            print(f"[{now_jhb().strftime('%H:%M:%S')}] Outside trading window. Live mode will not trade.")
            print("Run within the window or use --mode sim.")
            return

        session = requests.Session()
        venues = [BitstampVenue(session), CoinGeckoVenue(session)]
        balances = {
            "BITSTAMP": VenueBalances(usd=half, xrp=0.0),
            "COINGECKO": VenueBalances(usd=half, xrp=0.0),
        }
    else:
        v1 = SimulatedVenue("SIM_A", start_price=1.30, volatility=0.003, venue_bias=-0.0005, seed=1)
        v2 = SimulatedVenue("SIM_B", start_price=1.30, volatility=0.003, venue_bias=+0.0005, seed=2)
        venues = [v1, v2]
        balances = {
            "SIM_A": VenueBalances(usd=half, xrp=0.0),
            "SIM_B": VenueBalances(usd=half, xrp=0.0),
        }

    bot = TradingBot(
        venues=venues,
        balances=balances,
        min_edge=args.min_edge,
        buy_fee_pct=args.buy_fee,
        sell_fee_pct=args.sell_fee,
        trade_usd=args.trade_usd,
    )

    append_log(args.logfile, {
        "event": "START",
        "ts": now_jhb().isoformat(),
        "mode": args.mode,
        "params": vars(args),
        "initial_balances": {k: {"usd": v.usd, "xrp": v.xrp} for k, v in balances.items()},
    })

    print(f"=== XRP-USD Arbitrage Bot (Paper Trading) ===")
    print(f"Mode: {args.mode}")
    print(f"Trading window (JHB): {args.start} -> {args.end}")
    print("Press Ctrl+C to stop.\n")

    while not STOP and (args.mode == "sim" or in_trading_window(args.start, args.end)):
        ts = now_jhb().isoformat()
        try:
            traded, prices, edge = bot.step(ts)
        except PriceFeedError as e:
            append_log(args.logfile, {"event": "PRICE_ERROR", "ts": ts, "error": str(e)})
            time.sleep(args.poll)
            continue

        # Display one status line (live-style)
        price_str = " | ".join(f"{k}={v:.6f}" for k, v in prices.items())
        print(f"[{now_jhb().strftime('%H:%M:%S')}] {price_str} | edge={edge*100:.3f}%   ", end="\r")

        # Log trades (only when it traded)
        if traded:
            t = bot.trades[-1]
            append_log(args.logfile, {"event": "TRADE", **t.__dict__})

        time.sleep(args.poll)

    # End summary
    total_pnl = bot.total_pnl()
    append_log(args.logfile, {
        "event": "END",
        "ts": now_jhb().isoformat(),
        "mode": args.mode,
        "trade_count": len(bot.trades),
        "total_pnl_usd": total_pnl,
        "final_balances": {k: {"usd": v.usd, "xrp": v.xrp} for k, v in balances.items()},
    })

    write_trades_csv(args.csvfile, bot.trades)

    print("\n\n=== SESSION SUMMARY ===")
    print(f"Trades executed: {len(bot.trades)}")
    print(f"Total P/L (USD): {total_pnl:.4f}")
    print("Final balances:")
    for k, v in balances.items():
        print(f"  {k}: USD={v.usd:.4f}, XRP={v.xrp:.6f}")

    print_end_of_day_table(bot.trades)

    print(f"\nLogfile written to: {args.logfile}")
    print(f"CSV written to:     {args.csvfile}")

if __name__ == "__main__":
    main()