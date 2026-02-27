# venues.py
from __future__ import annotations
import random
import requests

class PriceFeedError(Exception):
    pass

class Venue:
    """Common interface: every venue must provide fetch_price()."""
    name: str

    def fetch_price(self) -> float:
        raise NotImplementedError

class BitstampVenue(Venue):
    name = "BITSTAMP"

    def __init__(self, session: requests.Session, timeout_s: float = 8.0):
        self.session = session
        self.timeout_s = timeout_s
        self.url = "https://www.bitstamp.net/api/v2/ticker/xrpusd/"

    def fetch_price(self) -> float:
        try:
            r = self.session.get(self.url, timeout=self.timeout_s, headers={"User-Agent": "arb-bot/1.0"})
            r.raise_for_status()
            data = r.json()
            return float(data["last"])
        except Exception as e:
            raise PriceFeedError(f"{self.name} fetch failed: {e}") from e

class CoinGeckoVenue(Venue):
    name = "COINGECKO"

    def __init__(self, session: requests.Session, timeout_s: float = 8.0):
        self.session = session
        self.timeout_s = timeout_s
        self.url = "https://api.coingecko.com/api/v3/simple/price?ids=ripple&vs_currencies=usd"

    def fetch_price(self) -> float:
        try:
            r = self.session.get(self.url, timeout=self.timeout_s, headers={"User-Agent": "arb-bot/1.0"})
            r.raise_for_status()
            data = r.json()
            return float(data["ripple"]["usd"])
        except Exception as e:
            raise PriceFeedError(f"{self.name} fetch failed: {e}") from e

class SimulatedVenue(Venue):
    """
    Simulated price feed using random walk.
    venue_bias creates small systematic differences between venues.
    """
    def __init__(
        self,
        name: str,
        start_price: float = 1.30,
        volatility: float = 0.003,
        venue_bias: float = 0.0,
        seed: int | None = None,
    ):
        self.name = name
        self.price = start_price
        self.volatility = volatility
        self.venue_bias = venue_bias
        self.rng = random.Random(seed)

    def fetch_price(self) -> float:
        noise = self.rng.uniform(-self.volatility, self.volatility)
        self.price *= (1.0 + noise)
        self.price = max(self.price, 0.0001)
        return float(self.price * (1.0 + self.venue_bias))