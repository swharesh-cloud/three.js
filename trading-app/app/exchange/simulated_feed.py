"""Offline price feed: geometric random walk per symbol. Used for demos and tests."""
from __future__ import annotations

import math
import random

DEFAULT_PRICES = {"BTC-USD": 95000.0, "ETH-USD": 3500.0, "SOL-USD": 180.0, "AAPL-USD": 230.0}


class SimulatedFeed:
    name = "simulated"

    def __init__(self, seed: int | None = None, volatility: float = 0.002):
        self.rng = random.Random(seed)
        self.vol = volatility
        self.prices: dict[str, float] = dict(DEFAULT_PRICES)

    async def get_price(self, symbol: str) -> float:
        price = self.prices.get(symbol, 100.0)
        price *= math.exp(self.rng.gauss(0, self.vol))
        self.prices[symbol] = price
        return price

    async def get_candles(self, symbol: str, interval: str = "1m", limit: int = 100) -> list[float]:
        return []
