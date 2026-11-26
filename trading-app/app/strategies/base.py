"""Base class for strategies.

To add your own strategy, drop a .py file into `user_strategies/` with a subclass of
`Strategy`. It appears in the app's "Add strategy" form automatically (after Reload).

    from app.strategies.base import Strategy, Param

    class MyStrategy(Strategy):
        name = "My strategy"
        description = "Buys when price drops 1% from the last tick."
        params = [Param("drop_pct", "float", 1.0, "Drop that triggers a buy, in %")]

        async def on_tick(self, ctx):
            if len(ctx.prices) >= 2 and ctx.price < ctx.prices[-2] * (1 - self.p["drop_pct"] / 100):
                await ctx.buy(self.p["quantity"])
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Param:
    name: str
    type: str  # "float" | "int" | "str" | "bool"
    default: Any
    help: str = ""
    choices: list = field(default_factory=list)

    def coerce(self, value):
        if value is None or value == "":
            return self.default
        if self.type == "float":
            return float(value)
        if self.type == "int":
            return int(float(value))
        if self.type == "bool":
            return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
        return str(value)


COMMON_PARAMS = [
    Param("quantity", "float", 0.01, "Order size in base units"),
]


class Strategy:
    name = "Base"
    description = ""
    params: list[Param] = []

    def __init__(self, values: dict | None = None):
        values = values or {}
        self.p = {prm.name: prm.coerce(values.get(prm.name)) for prm in self.all_params()}
        self.state: dict = {}

    @classmethod
    def all_params(cls) -> list[Param]:
        own = {p.name for p in cls.params}
        return [p for p in COMMON_PARAMS if p.name not in own] + list(cls.params)

    @classmethod
    def describe(cls) -> dict:
        return {
            "name": cls.name,
            "description": cls.description,
            "params": [p.__dict__ for p in cls.all_params()],
        }

    def warmup(self) -> int:
        """Number of prices needed before on_tick is called."""
        return 1

    async def on_start(self, ctx) -> None:
        return None

    async def on_tick(self, ctx) -> None:
        raise NotImplementedError
