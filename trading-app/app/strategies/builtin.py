"""Built-in strategies."""
from __future__ import annotations

from .base import Param, Strategy


def sma(values: list[float], n: int) -> float:
    return sum(values[-n:]) / n


def rsi(values: list[float], n: int) -> float:
    gains = losses = 0.0
    for a, b in zip(values[-n - 1:-1], values[-n:]):
        diff = b - a
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100 - 100 / (1 + rs)


class SmaCrossover(Strategy):
    name = "SMA crossover"
    description = "Goes long when the fast moving average crosses above the slow one; exits on the cross down."
    params = [
        Param("fast", "int", 10, "Fast SMA length (ticks)"),
        Param("slow", "int", 30, "Slow SMA length (ticks)"),
    ]

    def warmup(self) -> int:
        return self.p["slow"] + 1

    async def on_tick(self, ctx):
        prices, fast, slow = ctx.prices, self.p["fast"], self.p["slow"]
        prev_diff = sma(prices[:-1], fast) - sma(prices[:-1], slow)
        diff = sma(prices, fast) - sma(prices, slow)
        if prev_diff <= 0 < diff and ctx.position <= 0:
            await ctx.buy(self.p["quantity"], reason=f"fast SMA crossed above slow")
        elif prev_diff >= 0 > diff and ctx.position > 0:
            await ctx.sell(ctx.position, reason=f"fast SMA crossed below slow")


class RsiReversion(Strategy):
    name = "RSI mean reversion"
    description = "Buys when RSI is oversold and sells the position when it is overbought."
    params = [
        Param("period", "int", 14, "RSI period"),
        Param("oversold", "float", 30, "Buy below this RSI"),
        Param("overbought", "float", 70, "Sell above this RSI"),
    ]

    def warmup(self) -> int:
        return self.p["period"] + 1

    async def on_tick(self, ctx):
        value = rsi(ctx.prices, self.p["period"])
        ctx.set_indicator("rsi", round(value, 2))
        if value < self.p["oversold"] and ctx.position <= 0:
            await ctx.buy(self.p["quantity"], reason=f"RSI {value:.1f} < {self.p['oversold']}")
        elif value > self.p["overbought"] and ctx.position > 0:
            await ctx.sell(ctx.position, reason=f"RSI {value:.1f} > {self.p['overbought']}")


class Grid(Strategy):
    name = "Grid"
    description = "Buys each time price falls one grid step and sells each time it rises one step."
    params = [
        Param("step_pct", "float", 0.5, "Grid spacing in %"),
        Param("max_levels", "int", 5, "Max grid levels held at once"),
    ]

    async def on_tick(self, ctx):
        anchor = self.state.setdefault("anchor", ctx.price)
        step = anchor * self.p["step_pct"] / 100
        levels = self.state.setdefault("levels", 0)
        if ctx.price <= anchor - step and levels < self.p["max_levels"]:
            await ctx.buy(self.p["quantity"], reason=f"grid buy level {levels + 1}")
            self.state.update(anchor=ctx.price, levels=levels + 1)
        elif ctx.price >= anchor + step and levels > 0:
            await ctx.sell(self.p["quantity"], reason=f"grid sell level {levels}")
            self.state.update(anchor=ctx.price, levels=levels - 1)
        elif levels == 0 and ctx.price > anchor:
            self.state["anchor"] = ctx.price  # trail the anchor up while flat


class Dca(Strategy):
    name = "DCA"
    description = "Buys a fixed quantity every N ticks, with optional take-profit on the whole position."
    params = [
        Param("every_ticks", "int", 60, "Buy every N ticks"),
        Param("take_profit_pct", "float", 0.0, "Sell all when up this % over average cost (0 = off)"),
    ]

    async def on_tick(self, ctx):
        tp = self.p["take_profit_pct"]
        if tp > 0 and ctx.position > 0 and ctx.avg_price and ctx.price >= ctx.avg_price * (1 + tp / 100):
            await ctx.sell(ctx.position, reason=f"take profit {tp}%")
            return
        if ctx.tick % self.p["every_ticks"] == 0:
            await ctx.buy(self.p["quantity"], reason="scheduled DCA buy")
