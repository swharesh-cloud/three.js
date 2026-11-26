"""Liquid (liquid.trade) REST connector.

Liquid's endpoint paths and field names are loaded from a JSON mapping so they can be
matched to the official API reference without code changes. The defaults below are
placeholders: verify each one against Liquid's developer docs (or your account's API
page) and override them with LIQUID_ENDPOINTS_FILE before enabling live trading.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from .base import Exchange, Order

DEFAULT_ENDPOINTS: dict = {
    "auth_header": "Authorization",
    "auth_scheme": "Bearer",
    "ticker": {"method": "GET", "path": "/v1/markets/{symbol}/ticker", "price_field": "last_price"},
    "candles": {
        "method": "GET",
        "path": "/v1/markets/{symbol}/candles",
        "params": {"interval": "{interval}", "limit": "{limit}"},
        "close_field": "close",
    },
    "markets": {"method": "GET", "path": "/v1/markets", "symbol_field": "symbol"},
    "balances": {"method": "GET", "path": "/v1/account/balances"},
    "positions": {"method": "GET", "path": "/v1/account/positions"},
    "place_order": {"method": "POST", "path": "/v1/orders"},
    "cancel_order": {"method": "DELETE", "path": "/v1/orders/{order_id}"},
    "open_orders": {"method": "GET", "path": "/v1/orders"},
}


class LiquidError(RuntimeError):
    pass


def _dig(data, dotted: str):
    """Read a nested field like 'data.last_price'."""
    for part in dotted.split("."):
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit():
            data = data[int(part)]
        else:
            return None
    return data


class LiquidExchange(Exchange):
    name = "liquid"

    def __init__(self, base_url: str, api_key: str = "", api_secret: str = "",
                 endpoints_file: str = "", client: httpx.AsyncClient | None = None):
        self.base_url = base_url
        self.api_key = api_key
        self.api_secret = api_secret
        self.endpoints = dict(DEFAULT_ENDPOINTS)
        if endpoints_file:
            self.endpoints.update(json.loads(Path(endpoints_file).read_text()))
        self.client = client or httpx.AsyncClient(base_url=base_url, timeout=10.0)

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.api_key:
            scheme = self.endpoints.get("auth_scheme", "")
            headers[self.endpoints.get("auth_header", "Authorization")] = (
                f"{scheme} {self.api_key}".strip()
            )
        return headers

    async def _call(self, name: str, json_body: dict | None = None, **fmt) -> object:
        spec = self.endpoints[name]
        path = spec["path"].format(**fmt)
        params = {k: str(v).format(**fmt) for k, v in spec.get("params", {}).items()}
        resp = await self.client.request(spec["method"], path, params=params or None,
                                         json=json_body, headers=self._headers())
        if resp.status_code >= 400:
            raise LiquidError(f"{name} failed: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json() if resp.content else {}

    async def get_price(self, symbol: str) -> float:
        data = await self._call("ticker", symbol=symbol)
        price = _dig(data, self.endpoints["ticker"].get("price_field", "price"))
        if price is None:
            raise LiquidError(f"No price field in ticker response: {str(data)[:200]}")
        return float(price)

    async def get_candles(self, symbol: str, interval: str = "1m", limit: int = 100) -> list[float]:
        data = await self._call("candles", symbol=symbol, interval=interval, limit=limit)
        rows = data if isinstance(data, list) else _dig(data, "data") or []
        field = self.endpoints["candles"].get("close_field", "close")
        closes = []
        for row in rows:
            value = row[4] if isinstance(row, list) else _dig(row, field)
            if value is not None:
                closes.append(float(value))
        return closes

    async def list_markets(self) -> list[str]:
        data = await self._call("markets")
        rows = data if isinstance(data, list) else _dig(data, "data") or []
        field = self.endpoints["markets"].get("symbol_field", "symbol")
        return [str(_dig(r, field)) for r in rows if _dig(r, field)]

    async def place_order(self, order: Order) -> Order:
        body = {
            "symbol": order.symbol,
            "side": order.side,
            "type": order.type,
            "quantity": order.quantity,
            "client_order_id": order.id,
        }
        if order.type == "limit":
            body["price"] = order.price
        try:
            data = await self._call("place_order", json_body=body)
        except LiquidError as exc:
            order.status, order.reason = "rejected", str(exc)
            return order
        order.status = str(_dig(data, "status") or "open")
        remote_id = _dig(data, "id") or _dig(data, "order_id")
        if remote_id:
            order.id = str(remote_id)
        fill = _dig(data, "average_price") or _dig(data, "fill_price")
        if fill:
            order.fill_price = float(fill)
        return order

    async def cancel_order(self, order_id: str, symbol: str | None = None) -> bool:
        try:
            await self._call("cancel_order", order_id=order_id)
            return True
        except LiquidError:
            return False

    async def get_account(self) -> dict:
        return {
            "exchange": self.name,
            "mode": "live",
            "balances": await self._call("balances"),
            "positions": await self._call("positions"),
        }

    async def close(self) -> None:
        await self.client.aclose()
