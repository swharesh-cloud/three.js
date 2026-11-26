# Liquid Strategy Trader

A self-hosted trading app for the [Liquid](https://liquid.trade) platform. You add strategies in a web UI, set their parameters, start and stop them, and watch orders, positions and P&L live.

It starts in **paper trading** mode, with simulated fills and a simulated account, so you can try strategies without risking money.

## Quick start

```bash
cd trading-app
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --port 8000
```

Open http://localhost:8000. Pick a strategy type, a symbol and its parameters, then click **Add strategy** and **Start**.

## Adding strategies

**From the UI:** choose any installed strategy type, fill in the parameters, then add it. You can run several instances of the same type on different symbols or with different settings. Each instance tracks its own position and P&L, and can be stopped, edited, flattened or deleted.

**Writing your own:** drop a Python file in `user_strategies/` and click **Reload strategy files**. See `user_strategies/momentum_example.py`:

```python
from app.strategies.base import Param, Strategy

class MyStrategy(Strategy):
    name = "My strategy"
    description = "Shown in the UI"
    params = [Param("threshold", "float", 1.0, "help text")]   # becomes form fields
    def warmup(self): return 20                                  # prices needed before trading
    async def on_tick(self, ctx):
        # ctx.price, ctx.prices (history), ctx.position, ctx.avg_price, ctx.tick
        # await ctx.buy(qty, price=None, reason="..."), await ctx.sell(...)
        # ctx.set_indicator("name", value)  -> shown in the table
        ...
```

`quantity` is added to every strategy automatically.

Built-in strategies: SMA crossover, RSI mean reversion, Grid, DCA.

## Connecting to Liquid

Set these in `.env`:

| Variable | Meaning |
|---|---|
| `LIQUID_API_BASE` | Liquid API base URL |
| `LIQUID_API_KEY` / `LIQUID_API_SECRET` | Your API credentials (never commit `.env`) |
| `LIQUID_ENDPOINTS_FILE` | JSON file mapping endpoint paths and field names (see `liquid_endpoints.example.json`) |
| `MARKET_DATA=liquid` | Paper-trade on real Liquid prices instead of simulated ones |
| `TRADING_MODE=live` **and** `LIVE_TRADING_CONFIRM=I_UNDERSTAND` | Send real orders. Both are required. |

> **Important:** the endpoint paths and field names in `app/exchange/liquid.py` are placeholders. They were not verified against Liquid's API reference, which was unreachable when this was written. Before going live, copy `liquid_endpoints.example.json`, correct every path and field to match Liquid's docs, and point `LIQUID_ENDPOINTS_FILE` at it. Then test with `MARKET_DATA=liquid` in paper mode first. If Liquid uses request signing (HMAC) rather than a bearer token, extend `LiquidExchange._headers`.

## Risk controls

These apply in both modes:

- `MAX_ORDER_NOTIONAL`: the largest single order allowed.
- `MAX_POSITION_NOTIONAL`: the largest position allowed per strategy instance.
- `MAX_DAILY_LOSS`: when hit, new entries are blocked for the rest of the day. Exits are always allowed.
- Deleting a strategy does **not** close its position. Use **Flatten** first.

Strategy instances persist in `data/` and restart automatically if they were running when the server stopped.

## Tests

```bash
python -m pytest -q
```

This software is provided as-is and is not financial advice. Automated trading can lose money quickly.
