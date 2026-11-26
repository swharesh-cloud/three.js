import asyncio

import httpx
import pytest

from app.engine import Engine, RiskLimits
from app.exchange.liquid import LiquidExchange
from app.exchange.base import Order
from app.exchange.paper import PaperExchange
from app.strategies.base import Strategy
from app.strategies.builtin import rsi, sma
from app.strategies.registry import discover


class ScriptedFeed:
    name = "scripted"

    def __init__(self, prices):
        self.prices = list(prices)
        self.i = 0

    async def get_price(self, symbol):
        p = self.prices[min(self.i, len(self.prices) - 1)]
        self.i += 1
        return p

    async def get_candles(self, *a):
        return []


def make_engine(tmp_path, prices, limits=None):
    registry, errors = discover()
    assert not errors
    ex = PaperExchange(ScriptedFeed(prices), starting_cash=10_000, fee_rate=0)
    return Engine(ex, registry, limits or RiskLimits(), tmp_path), ex


def test_indicators():
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert rsi([1, 2, 3, 4, 5], 4) == 100.0
    assert 0 < rsi([5, 4, 5, 4, 5], 4) < 100


def test_registry_finds_builtin_and_user_strategies():
    registry, _ = discover()
    names = {cls.name for cls in registry.values()}
    assert {"SMA crossover", "RSI mean reversion", "Grid", "DCA", "Momentum (example)"} <= names


async def test_paper_fill_and_pnl():
    ex = PaperExchange(ScriptedFeed([100, 110]), starting_cash=1000, fee_rate=0)
    await ex.get_price("X")
    await ex.place_order(Order("X", "buy", 2))
    await ex.get_price("X")
    o = await ex.place_order(Order("X", "sell", 2))
    assert o.status == "filled" and o.fill_price == 110
    assert ex.cash == pytest.approx(1020)
    assert ex.positions["X"].realized_pnl == pytest.approx(20)


async def test_paper_rejects_without_cash():
    ex = PaperExchange(ScriptedFeed([100]), starting_cash=50, fee_rate=0)
    o = await ex.place_order(Order("X", "buy", 1))
    assert o.status == "rejected"


async def test_limit_order_fills_when_crossed():
    ex = PaperExchange(ScriptedFeed([100, 95]), starting_cash=1000, fee_rate=0)
    await ex.get_price("X")
    o = await ex.place_order(Order("X", "buy", 1, type="limit", price=96))
    assert o.status == "open"
    await ex.get_price("X")
    assert o.status == "filled" and o.fill_price == 96


async def test_engine_runs_strategy_and_persists(tmp_path):
    engine, ex = make_engine(tmp_path, [100] * 5 + [101, 102, 103, 104, 105, 106] + [99] * 10)
    key = next(k for k, c in engine.registry.items() if c.name == "Momentum (example)")
    inst = engine.add(key, "btc-usd", {"streak": 3, "quantity": 1, "stop_loss_pct": 1}, interval_sec=0.2)
    assert inst.symbol == "BTC-USD"
    engine.price = lambda s, max_age=0: ex.get_price(s)  # no caching in tests
    await engine.start(inst.id)
    await asyncio.sleep(0.2 * 20)
    await engine.stop(inst.id)
    sides = [o["side"] for o in engine.orders if o["status"] == "filled"]
    assert "buy" in sides and "sell" in sides
    assert inst.position == 0
    # persisted and reloadable
    engine2, _ = make_engine(tmp_path, [100])
    engine2.load()
    assert inst.id in engine2.instances


async def test_risk_limits_block_entries_but_allow_exits(tmp_path):
    engine, ex = make_engine(tmp_path, [100], RiskLimits(max_order_notional=150, max_position_notional=150))
    key = next(iter(engine.registry))
    inst = engine.add(key, "X", {})
    inst.last_price = 100
    assert (await engine.submit(inst, "buy", 2)).status == "rejected"  # 200 > 150
    assert (await engine.submit(inst, "buy", 1)).status == "filled"
    assert (await engine.submit(inst, "buy", 1)).status == "rejected"  # position 200 > 150
    assert (await engine.submit(inst, "sell", 1)).status == "filled"
    assert inst.position == 0


async def test_liquid_adapter_uses_endpoint_mapping():
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path.endswith("/ticker"):
            return httpx.Response(200, json={"last_price": "123.5"})
        if request.url.path == "/v1/orders":
            return httpx.Response(200, json={"id": "abc", "status": "filled", "average_price": "123.4"})
        return httpx.Response(404)

    client = httpx.AsyncClient(base_url="https://example.test", transport=httpx.MockTransport(handler))
    ex = LiquidExchange("https://example.test", api_key="k", client=client)
    assert await ex.get_price("BTC-USD") == 123.5
    o = await ex.place_order(Order("BTC-USD", "buy", 0.1))
    assert o.status == "filled" and o.id == "abc" and o.fill_price == 123.4
    assert seen[0] == ("GET", "/v1/markets/BTC-USD/ticker", "Bearer k")
