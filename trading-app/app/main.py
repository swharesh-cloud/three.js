"""FastAPI server: REST API + static web UI."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ROOT, load_settings
from .engine import Engine, RiskLimits
from .exchange.liquid import LiquidExchange
from .exchange.paper import PaperExchange
from .exchange.simulated_feed import SimulatedFeed
from .strategies.registry import discover

settings = load_settings()


def build_exchange():
    liquid = LiquidExchange(settings.liquid_api_base, settings.liquid_api_key,
                            settings.liquid_api_secret, settings.liquid_endpoints_file)
    if settings.is_live:
        return liquid
    feed = liquid if settings.market_data == "liquid" else SimulatedFeed()
    return PaperExchange(feed, settings.paper_starting_cash, settings.paper_fee_rate)


state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    registry, errors = discover()
    engine = Engine(build_exchange(), registry,
                    RiskLimits(settings.max_order_notional, settings.max_position_notional, settings.max_daily_loss),
                    settings.data_dir, live=settings.is_live)
    for err in errors:
        engine.log(f"Strategy load error: {err}", level="error")
    engine.load()
    engine.log(f"Engine ready in {'LIVE' if settings.is_live else 'PAPER'} mode")
    await engine.start_enabled()
    state["engine"] = engine
    yield
    await engine.shutdown()
    await engine.exchange.close()


app = FastAPI(title="Liquid Strategy Trader", lifespan=lifespan)


def eng() -> Engine:
    return state["engine"]


class NewStrategy(BaseModel):
    type: str
    symbol: str
    params: dict = {}
    interval_sec: float = 5.0
    label: str = ""


class EditStrategy(BaseModel):
    params: dict | None = None
    interval_sec: float | None = None
    label: str | None = None


@app.get("/api/status")
async def status():
    e = eng()
    warning = ""
    if settings.trading_mode == "live" and not settings.live_confirmed:
        warning = "TRADING_MODE=live is set but LIVE_TRADING_CONFIRM is not; running in paper mode."
    return {"mode": "live" if e.live else "paper", "exchange": e.exchange.name,
            "market_data": settings.market_data, "halted": e.halted, "warning": warning,
            "limits": e.limits.__dict__, "liquid_api_base": settings.liquid_api_base,
            "liquid_key_set": bool(settings.liquid_api_key)}


@app.get("/api/strategy-types")
async def strategy_types():
    return {key: cls.describe() for key, cls in eng().registry.items()}


@app.post("/api/strategy-types/reload")
async def reload_types():
    registry, errors = discover()
    eng().registry = registry
    for err in errors:
        eng().log(f"Strategy load error: {err}", level="error")
    return {"types": list(registry), "errors": errors}


@app.get("/api/strategies")
async def list_strategies():
    return eng().snapshot()


@app.post("/api/strategies")
async def add_strategy(body: NewStrategy):
    try:
        inst = eng().add(body.type, body.symbol, body.params, body.interval_sec, body.label)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc))
    return inst.persisted()


def _get(inst_id: str):
    if inst_id not in eng().instances:
        raise HTTPException(404, "strategy not found")


@app.patch("/api/strategies/{inst_id}")
async def edit_strategy(inst_id: str, body: EditStrategy):
    _get(inst_id)
    try:
        return eng().update(inst_id, body.params, body.interval_sec, body.label).persisted()
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/strategies/{inst_id}/start")
async def start_strategy(inst_id: str):
    _get(inst_id)
    await eng().start(inst_id)
    return {"ok": True}


@app.post("/api/strategies/{inst_id}/stop")
async def stop_strategy(inst_id: str):
    _get(inst_id)
    await eng().stop(inst_id)
    return {"ok": True}


@app.post("/api/strategies/{inst_id}/flatten")
async def flatten(inst_id: str):
    _get(inst_id)
    inst = eng().instances[inst_id]
    if inst.position == 0:
        return {"ok": True, "message": "already flat"}
    side = "sell" if inst.position > 0 else "buy"
    order = await eng().submit(inst, side, abs(inst.position), reason="manual flatten")
    return order.to_dict()


@app.delete("/api/strategies/{inst_id}")
async def delete_strategy(inst_id: str):
    _get(inst_id)
    await eng().remove(inst_id)
    return {"ok": True}


@app.get("/api/account")
async def account():
    try:
        return await eng().exchange.get_account()
    except Exception as exc:
        raise HTTPException(502, f"exchange error: {exc}")


@app.get("/api/price/{symbol}")
async def price(symbol: str):
    try:
        return {"symbol": symbol.upper(), "price": await eng().price(symbol.upper())}
    except Exception as exc:
        raise HTTPException(502, f"exchange error: {exc}")


@app.get("/api/orders")
async def orders():
    return list(eng().orders)


@app.post("/api/orders/{order_id}/cancel")
async def cancel(order_id: str):
    return {"ok": await eng().exchange.cancel_order(order_id)}


@app.get("/api/logs")
async def logs(limit: int = 200):
    return list(eng().logs)[-limit:][::-1]


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")
