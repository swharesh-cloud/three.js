"""Runs strategy instances, applies risk limits, routes orders, persists state."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .exchange.base import Exchange, Order
from .strategies.base import Strategy


@dataclass
class RiskLimits:
    max_order_notional: float = 1000.0
    max_position_notional: float = 5000.0
    max_daily_loss: float = 500.0


@dataclass
class Instance:
    id: str
    type: str
    symbol: str
    params: dict
    interval_sec: float = 5.0
    label: str = ""
    enabled: bool = False
    # runtime (not persisted except position bookkeeping)
    position: float = 0.0
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    last_price: float | None = None
    indicators: dict = field(default_factory=dict)
    status: str = "stopped"
    error: str = ""

    def persisted(self) -> dict:
        keys = ("id", "type", "symbol", "params", "interval_sec", "label", "enabled",
                "position", "avg_price", "realized_pnl")
        return {k: getattr(self, k) for k in keys}


class Context:
    """What a strategy sees on each tick."""

    def __init__(self, engine: "Engine", inst: Instance, prices: list[float], tick: int):
        self._engine, self._inst = engine, inst
        self.symbol = inst.symbol
        self.prices = prices
        self.price = prices[-1]
        self.tick = tick

    @property
    def position(self) -> float:
        return self._inst.position

    @property
    def avg_price(self) -> float:
        return self._inst.avg_price

    async def buy(self, quantity: float, price: float | None = None, reason: str = "") -> Order:
        return await self._engine.submit(self._inst, "buy", quantity, price, reason)

    async def sell(self, quantity: float, price: float | None = None, reason: str = "") -> Order:
        return await self._engine.submit(self._inst, "sell", quantity, price, reason)

    def set_indicator(self, name: str, value) -> None:
        self._inst.indicators[name] = value

    def log(self, message: str) -> None:
        self._engine.log(message, self._inst.id)


class Engine:
    def __init__(self, exchange: Exchange, registry: dict[str, type[Strategy]],
                 limits: RiskLimits, data_dir: Path, live: bool = False):
        self.exchange = exchange
        self.registry = registry
        self.limits = limits
        self.live = live
        self.state_file = data_dir / ("strategies_live.json" if live else "strategies_paper.json")
        self.instances: dict[str, Instance] = {}
        self.strategies: dict[str, Strategy] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.orders: deque[dict] = deque(maxlen=500)
        self.logs: deque[dict] = deque(maxlen=1000)
        self._price_cache: dict[str, tuple[float, float]] = {}
        self._price_lock = asyncio.Lock()
        self._day = time.strftime("%Y-%m-%d")
        self._day_start_pnl = 0.0
        self.halted = False

    # ---------- persistence ----------
    def load(self) -> None:
        if not self.state_file.exists():
            return
        for raw in json.loads(self.state_file.read_text()):
            inst = Instance(**raw)
            self.instances[inst.id] = inst

    def save(self) -> None:
        self.state_file.write_text(json.dumps([i.persisted() for i in self.instances.values()], indent=2))

    def log(self, message: str, strategy_id: str | None = None, level: str = "info") -> None:
        self.logs.append({"t": time.time(), "strategy_id": strategy_id, "level": level, "message": message})

    # ---------- CRUD ----------
    def add(self, type_key: str, symbol: str, params: dict, interval_sec: float = 5.0, label: str = "") -> Instance:
        if type_key not in self.registry:
            raise ValueError(f"Unknown strategy type {type_key}")
        cls = self.registry[type_key]
        cleaned = cls(params).p  # validates & fills defaults
        inst = Instance(id=uuid.uuid4().hex[:8], type=type_key, symbol=symbol.upper(), params=cleaned,
                        interval_sec=max(0.2, float(interval_sec)), label=label or cls.name)
        self.instances[inst.id] = inst
        self.save()
        self.log(f"Added {inst.label} on {inst.symbol}", inst.id)
        return inst

    def update(self, inst_id: str, params: dict | None = None, interval_sec: float | None = None,
               label: str | None = None) -> Instance:
        inst = self.instances[inst_id]
        if params is not None:
            inst.params = self.registry[inst.type](params).p
        if interval_sec is not None:
            inst.interval_sec = max(0.2, float(interval_sec))
        if label is not None:
            inst.label = label
        self.save()
        return inst

    async def remove(self, inst_id: str) -> None:
        await self.stop(inst_id)
        inst = self.instances.pop(inst_id)
        self.save()
        self.log(f"Removed {inst.label}", inst_id)

    # ---------- run control ----------
    async def start(self, inst_id: str) -> None:
        inst = self.instances[inst_id]
        if inst_id in self.tasks and not self.tasks[inst_id].done():
            return
        if inst.type not in self.registry:
            inst.status, inst.error = "error", f"strategy type {inst.type} not found"
            return
        self.strategies[inst_id] = self.registry[inst.type](inst.params)
        inst.enabled, inst.status, inst.error = True, "warming up", ""
        self.save()
        self.tasks[inst_id] = asyncio.create_task(self._run(inst))
        self.log(f"Started {inst.label}", inst_id)

    async def stop(self, inst_id: str) -> None:
        inst = self.instances[inst_id]
        task = self.tasks.pop(inst_id, None)
        if task:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        inst.enabled, inst.status = False, "stopped"
        self.save()
        self.log(f"Stopped {inst.label}", inst_id)

    async def start_enabled(self) -> None:
        for inst in list(self.instances.values()):
            if inst.enabled:
                await self.start(inst.id)

    async def shutdown(self) -> None:
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    async def price(self, symbol: str, max_age: float = 0.9) -> float:
        async with self._price_lock:
            cached = self._price_cache.get(symbol)
            if cached and time.time() - cached[1] < max_age:
                return cached[0]
            value = await self.exchange.get_price(symbol)
            self._price_cache[symbol] = (value, time.time())
            return value

    async def _run(self, inst: Instance) -> None:
        strategy = self.strategies[inst.id]
        history: deque[float] = deque(maxlen=max(500, strategy.warmup() * 2))
        try:
            history.extend(await self.exchange.get_candles(inst.symbol, "1m", strategy.warmup()))
        except Exception as exc:
            self.log(f"Could not load history: {exc}", inst.id, "warn")
        tick = 0
        await strategy.on_start(None)
        while True:
            try:
                price = await self.price(inst.symbol)
                history.append(price)
                inst.last_price = price
                tick += 1
                if len(history) >= strategy.warmup():
                    inst.status = "running"
                    await strategy.on_tick(Context(self, inst, list(history), tick))
                else:
                    inst.status = f"warming up ({len(history)}/{strategy.warmup()})"
                inst.error = ""
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                inst.status, inst.error = "error", repr(exc)
                self.log(f"Tick error: {exc!r}", inst.id, "error")
            await asyncio.sleep(inst.interval_sec)

    # ---------- orders & risk ----------
    def total_pnl(self) -> float:
        unreal = sum((i.last_price or i.avg_price) * i.position - i.avg_price * i.position
                     for i in self.instances.values())
        return sum(i.realized_pnl for i in self.instances.values()) + unreal

    def _check_risk(self, inst: Instance, side: str, quantity: float, price: float) -> str | None:
        today = time.strftime("%Y-%m-%d")
        if today != self._day:
            self._day, self._day_start_pnl, self.halted = today, self.total_pnl(), False
        reduces = (side == "sell" and inst.position > 0) or (side == "buy" and inst.position < 0)
        if reduces and quantity <= abs(inst.position) + 1e-12:
            return None  # always allow exits
        if self.halted:
            return "trading halted: daily loss limit reached"
        if self.total_pnl() - self._day_start_pnl < -self.limits.max_daily_loss:
            self.halted = True
            self.log("Daily loss limit reached: new entries are blocked until tomorrow", level="error")
            return "trading halted: daily loss limit reached"
        if quantity * price > self.limits.max_order_notional:
            return f"order notional {quantity * price:.2f} > limit {self.limits.max_order_notional}"
        new_pos = inst.position + (quantity if side == "buy" else -quantity)
        if abs(new_pos) * price > self.limits.max_position_notional:
            return f"position notional {abs(new_pos) * price:.2f} > limit {self.limits.max_position_notional}"
        return None

    def _apply_fill(self, inst: Instance, order: Order) -> None:
        qty = order.quantity if order.side == "buy" else -order.quantity
        price = order.fill_price
        if inst.position and (inst.position > 0) != (qty > 0):
            closing = min(abs(qty), abs(inst.position))
            inst.realized_pnl += closing * (price - inst.avg_price) * (1 if inst.position > 0 else -1)
        new_pos = inst.position + qty
        if abs(new_pos) < 1e-12:
            new_pos, inst.avg_price = 0.0, 0.0
        elif inst.position == 0 or (inst.position > 0) != (new_pos > 0):
            inst.avg_price = price
        elif (inst.position > 0) == (qty > 0):
            inst.avg_price = (inst.avg_price * abs(inst.position) + price * abs(qty)) / abs(new_pos)
        inst.position = new_pos
        inst.realized_pnl -= order.fee
        self.save()

    async def submit(self, inst: Instance, side: str, quantity: float, price: float | None = None,
                     reason: str = "") -> Order:
        quantity = float(quantity)
        order = Order(symbol=inst.symbol, side=side, quantity=quantity,
                      type="limit" if price else "market", price=price, strategy_id=inst.id)
        ref_price = price or inst.last_price or await self.price(inst.symbol)
        problem = self._check_risk(inst, side, quantity, ref_price)
        if problem:
            order.status, order.reason = "rejected", problem
        else:
            order = await self.exchange.place_order(order)
            if order.status == "filled" and order.fill_price is None:
                order.fill_price = ref_price
        if order.status == "filled":
            self._apply_fill(inst, order)
        entry = order.to_dict() | {"note": reason, "strategy_label": inst.label}
        self.orders.appendleft(entry)
        level = "warn" if order.status == "rejected" else "info"
        self.log(f"{side.upper()} {quantity} {inst.symbol} -> {order.status}"
                 f"{f' @ {order.fill_price:.4f}' if order.fill_price else ''}"
                 f"{f' ({order.reason})' if order.reason else ''}{f' — {reason}' if reason else ''}",
                 inst.id, level)
        return order

    def snapshot(self) -> list[dict]:
        out = []
        for inst in self.instances.values():
            unreal = ((inst.last_price or inst.avg_price) - inst.avg_price) * inst.position
            out.append(inst.persisted() | {
                "status": inst.status, "error": inst.error, "last_price": inst.last_price,
                "indicators": inst.indicators, "unrealized_pnl": unreal,
                "type_name": self.registry[inst.type].name if inst.type in self.registry else inst.type,
            })
        return out
