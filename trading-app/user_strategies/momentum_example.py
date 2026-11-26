"""Example user strategy. Copy this file to start your own."""
from app.strategies.base import Param, Strategy


class Momentum(Strategy):
    name = "Momentum (example)"
    description = "Buys after N consecutive rising ticks, exits on a stop-loss or take-profit."
    params = [
        Param("streak", "int", 5, "Consecutive rising ticks needed to enter"),
        Param("stop_loss_pct", "float", 1.0, "Exit if price falls this % below entry"),
        Param("take_profit_pct", "float", 2.0, "Exit if price rises this % above entry"),
    ]

    def warmup(self):
        return self.p["streak"] + 1

    async def on_tick(self, ctx):
        if ctx.position > 0:
            entry = ctx.avg_price
            if ctx.price <= entry * (1 - self.p["stop_loss_pct"] / 100):
                await ctx.sell(ctx.position, reason="stop loss")
            elif ctx.price >= entry * (1 + self.p["take_profit_pct"] / 100):
                await ctx.sell(ctx.position, reason="take profit")
            return
        recent = ctx.prices[-(self.p["streak"] + 1):]
        if all(b > a for a, b in zip(recent, recent[1:])):
            await ctx.buy(self.p["quantity"], reason=f"{self.p['streak']} rising ticks")
