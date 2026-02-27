# bot.py
from __future__ import annotations
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from typing import List, Tuple

from models import VenueBalances, Trade, Balances
from venues import Venue

JHB_TZ = ZoneInfo("Africa/Johannesburg")

def now_jhb() -> datetime:
    return datetime.now(tz=JHB_TZ)

def in_trading_window(start_hhmm: str, end_hhmm: str, now: datetime | None = None) -> bool:
    now = now or now_jhb()
    sh, sm = map(int, start_hhmm.split(":"))
    eh, em = map(int, end_hhmm.split(":"))
    start_t = dtime(sh, sm)
    end_t = dtime(eh, em)
    return start_t <= now.time() <= end_t

class TradingBot:
    """
    Paper-trading arbitrage bot:
    - fetches prices from two venues
    - if price difference is big enough, buys on cheaper and sells on expensive
    - updates simulated balances and records trades
    """

    def __init__(
        self,
        venues: List[Venue],
        balances: Balances,
        min_edge: float,
        buy_fee_pct: float,
        sell_fee_pct: float,
        trade_usd: float,
    ):
        if len(venues) != 2:
            raise ValueError("This bot expects exactly 2 venues.")
        self.venues = venues
        self.balances = balances
        self.min_edge = min_edge
        self.buy_fee_pct = buy_fee_pct
        self.sell_fee_pct = sell_fee_pct
        self.trade_usd = trade_usd
        self.trades: List[Trade] = []

    def fetch_prices(self) -> dict[str, float]:
        return {v.name: v.fetch_price() for v in self.venues}

    def _simulate_buy(self, venue: str, usd_to_spend: float, price: float) -> float:
        """
        Spend USD + fee to receive XRP.
        Returns XRP bought.
        """
        bal = self.balances[venue]
        fee = usd_to_spend * self.buy_fee_pct
        total = usd_to_spend + fee

        if total > bal.usd:
            usd_to_spend = max(0.0, bal.usd / (1.0 + self.buy_fee_pct))
            fee = usd_to_spend * self.buy_fee_pct
            total = usd_to_spend + fee

        xrp = usd_to_spend / price if price > 0 else 0.0
        bal.usd -= total
        bal.xrp += xrp
        return xrp

    def _simulate_sell(self, venue: str, xrp_to_sell: float, price: float) -> float:
        """
        Sell XRP to receive USD minus fee.
        Returns USD received (net).
        """
        bal = self.balances[venue]
        xrp_to_sell = min(xrp_to_sell, bal.xrp)
        gross = xrp_to_sell * price
        fee = gross * self.sell_fee_pct
        net = gross - fee
        bal.xrp -= xrp_to_sell
        bal.usd += net
        return net

    def step(self, ts: str) -> Tuple[bool, dict[str, float], float]:
        """
        One iteration:
        - fetch prices
        - decide arbitrage
        - execute paper trades if edge > threshold
        Returns (traded?, prices, edge)
        """
        prices = self.fetch_prices()

        # Choose buy/sell venue
        sorted_by_price = sorted(prices.items(), key=lambda kv: kv[1])
        buy_v, buy_price = sorted_by_price[0]
        sell_v, sell_price = sorted_by_price[-1]

        edge = (sell_price - buy_price) / buy_price if buy_price > 0 else 0.0

        if edge <= self.min_edge:
            return False, prices, edge

        # Ensure we have USD on buy venue
        if self.balances[buy_v].usd <= 1.0:
            return False, prices, edge

        usd_to_use = min(self.trade_usd, self.balances[buy_v].usd)
        xrp_bought = self._simulate_buy(buy_v, usd_to_use, buy_price)

        # Instant transfer assumption (for the assignment)
        self.balances[sell_v].xrp += xrp_bought

        usd_received = self._simulate_sell(sell_v, xrp_bought, sell_price)

        # Realized pnl (since we’re USD-in and USD-out)
        pnl = usd_received - usd_to_use

        # Fee estimate (simple)
        fee_est = usd_to_use * (self.buy_fee_pct + self.sell_fee_pct)

        self.trades.append(Trade(
            ts=ts,
            buy_venue=buy_v,
            sell_venue=sell_v,
            buy_price=buy_price,
            sell_price=sell_price,
            usd_spent=usd_to_use,
            xrp_bought=xrp_bought,
            pnl_usd=pnl,
            fee_usd=fee_est
        ))
        return True, prices, edge

    def total_pnl(self) -> float:
        return sum(t.pnl_usd for t in self.trades)