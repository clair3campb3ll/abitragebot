# models.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict

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
    pnl_usd: float
    fee_usd: float

Balances = Dict[str, VenueBalances]