"""FastAPI server: REST API + static web UI."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import secret_store
from .config import ROOT, load_settings, save_env
from .engine import Engine, RiskLimits
from .exchange.liquid import LiquidExchange
from .exchange.paper import PaperExchange
from .exchange.simulated_feed import SimulatedFeed
from .strategies.registry import discover

state: dict = {}


def liquid_client(settings) -> LiquidExchange:
    return LiquidExchange(settings.liquid_api_base, settings.liquid_api_key,
                          settings.liquid_api_secret, settings.liquid_endpoints_file)


def build_exchange(settings):
    if settings.is_live:
        return liquid_client(settings)
    feed = liquid_client(settings) if settings.market_data == "liquid" else SimulatedFeed()
    return PaperExchange(feed, settings.paper_starting_cash, settings.paper_fee_rate)


async def start_engine() -> Engine:
    settings = load_settings()
    registry, errors = discover()
    engine = Engine(build_exchange(settings), registry,
                    RiskLimits(settings.max_order_notional, settings.max_position_notional, settings.max_daily_loss),
                    settings.data_dir, live=settings.is_live)
    for err in errors:
        engine.log(f"Strategy load error: {err}", level="error")
    engine.load()
    engine.log(f"Engine ready in {'LIVE' if settings.is_live else 'PAPER'} mode")
    await engine.start_enabled()
    state["engine"], state["settings"] = engine, settings
    return engine


async def stop_engine() -> None:
    engine = state.get("engine")
    if engine:
        await engine.shutdown()
        await engine.exchange.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_engine()
    yield
    await stop_engine()


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
    e, settings = eng(), state["settings"]
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


def _mask(value: str) -> str:
    return f"saved, ends in {value[-4:]}" if len(value) >= 8 else ("saved" if value else "")


@app.get("/api/settings")
async def get_settings():
    s = state["settings"]
    return {
        "liquid_api_base": s.liquid_api_base, "api_key": _mask(s.liquid_api_key),
        "api_secret": _mask(s.liquid_api_secret), "key_storage": secret_store.backend_name(),
        "market_data": s.market_data, "trading_mode": s.trading_mode, "live_confirmed": s.live_confirmed,
        "endpoints_file": s.liquid_endpoints_file,
        "max_order_notional": s.max_order_notional, "max_position_notional": s.max_position_notional,
        "max_daily_loss": s.max_daily_loss,
    }


class SettingsIn(BaseModel):
    liquid_api_base: str | None = None
    api_key: str | None = None      # None or "" = keep current; "-" = remove
    api_secret: str | None = None
    endpoints_file: str | None = None
    market_data: str | None = None  # simulated | liquid
    trading_mode: str | None = None  # paper | live
    live_confirmed: bool | None = None
    max_order_notional: float | None = None
    max_position_notional: float | None = None
    max_daily_loss: float | None = None


@app.post("/api/settings")
async def save_settings(body: SettingsIn):
    updates: dict[str, str] = {}
    if body.liquid_api_base is not None:
        base = body.liquid_api_base.strip().rstrip("/")
        if not base.startswith("https://"):
            raise HTTPException(400, "The API address must start with https://")
        updates["LIQUID_API_BASE"] = base
    for field, env_key in (("api_key", "LIQUID_API_KEY"), ("api_secret", "LIQUID_API_SECRET")):
        value = getattr(body, field)
        if value:
            value = "" if value == "-" else value.strip()
            if secret_store.set(env_key, value):
                updates[env_key] = ""  # keep it out of the file when the keychain holds it
            else:
                updates[env_key] = value
    if body.endpoints_file is not None:
        updates["LIQUID_ENDPOINTS_FILE"] = body.endpoints_file.strip()
    if body.market_data is not None:
        if body.market_data not in ("simulated", "liquid"):
            raise HTTPException(400, "market_data must be simulated or liquid")
        updates["MARKET_DATA"] = body.market_data
    if body.trading_mode is not None:
        if body.trading_mode not in ("paper", "live"):
            raise HTTPException(400, "trading_mode must be paper or live")
        updates["TRADING_MODE"] = body.trading_mode
        updates["LIVE_TRADING_CONFIRM"] = "I_UNDERSTAND" if body.trading_mode == "live" and body.live_confirmed else ""
    for field, env_key in (("max_order_notional", "MAX_ORDER_NOTIONAL"),
                           ("max_position_notional", "MAX_POSITION_NOTIONAL"), ("max_daily_loss", "MAX_DAILY_LOSS")):
        value = getattr(body, field)
        if value is not None:
            if value <= 0:
                raise HTTPException(400, f"{field} must be more than 0")
            updates[env_key] = str(value)
    save_env(updates)
    await stop_engine()
    await start_engine()
    return await get_settings()


@app.post("/api/settings/test")
async def test_connection(symbol: str = "BTC-USD"):
    """Checks the saved Liquid settings without placing any order."""
    client = liquid_client(load_settings())
    result = {"price": None, "account": None}
    try:
        result["price"] = {"ok": True, "symbol": symbol, "value": await client.get_price(symbol)}
    except Exception as exc:
        result["price"] = {"ok": False, "error": str(exc)[:300]}
    try:
        balances = await client._call("balances")
        result["account"] = {"ok": True, "preview": str(balances)[:300]}
    except Exception as exc:
        result["account"] = {"ok": False, "error": str(exc)[:300]}
    finally:
        await client.close()
    return result


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")
