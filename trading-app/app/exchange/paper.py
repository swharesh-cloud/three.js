"""Paper trading: real or simulated prices, simulated fills and balances."""
from __future__ import annotations

from .base import Exchange, Order, Position


class PaperExchange(Exchange):
    name = "paper"

    def __init__(self, feed, starting_cash: float = 10000.0, fee_rate: float = 0.0005):
        self.feed = feed
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.fee_rate = fee_rate
        self.positions: dict[str, Position] = {}
        self.open_orders: dict[str, Order] = {}
        self.last_prices: dict[str, float] = {}

    async def get_price(self, symbol: str) -> float:
        price = await self.feed.get_price(symbol)
        self.last_prices[symbol] = price
        await self._match_limits(symbol, price)
        return price

    async def get_candles(self, symbol: str, interval: str = "1m", limit: int = 100) -> list[float]:
        return await self.feed.get_candles(symbol, interval, limit)

    def _fill(self, order: Order, price: float) -> Order:
        qty = order.quantity if order.side == "buy" else -order.quantity
        fee = abs(qty) * price * self.fee_rate
        pos = self.positions.setdefault(order.symbol, Position(order.symbol))
        if order.side == "buy" and self.cash < qty * price + fee:
            order.status, order.reason = "rejected", "insufficient cash"
            return order
        # realize PnL on the part that reduces the position
        if pos.quantity and (pos.quantity > 0) != (qty > 0):
            closing = min(abs(qty), abs(pos.quantity))
            direction = 1 if pos.quantity > 0 else -1
            pos.realized_pnl += closing * (price - pos.avg_price) * direction
        new_qty = pos.quantity + qty
        if new_qty == 0:
            pos.avg_price = 0.0
        elif pos.quantity == 0 or (pos.quantity > 0) != (new_qty > 0):
            pos.avg_price = price
        elif (pos.quantity > 0) == (qty > 0):
            pos.avg_price = (pos.avg_price * abs(pos.quantity) + price * abs(qty)) / abs(new_qty)
        pos.quantity = new_qty
        self.cash -= qty * price + fee
        pos.realized_pnl -= fee
        order.status, order.fill_price, order.fee = "filled", price, fee
        return order

    async def _match_limits(self, symbol: str, price: float) -> None:
        for oid, order in list(self.open_orders.items()):
            if order.symbol != symbol:
                continue
            if (order.side == "buy" and price <= order.price) or (order.side == "sell" and price >= order.price):
                self._fill(order, order.price)
                self.open_orders.pop(oid, None)

    async def place_order(self, order: Order) -> Order:
        if order.quantity <= 0:
            order.status, order.reason = "rejected", "quantity must be positive"
            return order
        if order.type == "limit":
            if not order.price:
                order.status, order.reason = "rejected", "limit order needs a price"
                return order
            order.status = "open"
            self.open_orders[order.id] = order
            return order
        price = self.last_prices.get(order.symbol) or await self.get_price(order.symbol)
        return self._fill(order, price)

    async def cancel_order(self, order_id: str, symbol: str | None = None) -> bool:
        order = self.open_orders.pop(order_id, None)
        if order:
            order.status = "cancelled"
        return order is not None

    def equity(self) -> float:
        return self.cash + sum(p.quantity * self.last_prices.get(s, p.avg_price) for s, p in self.positions.items())

    async def get_account(self) -> dict:
        positions = []
        for s, p in self.positions.items():
            if p.quantity == 0 and p.realized_pnl == 0:
                continue
            mark = self.last_prices.get(s, p.avg_price)
            positions.append({
                "symbol": s, "quantity": p.quantity, "avg_price": p.avg_price, "mark_price": mark,
                "unrealized_pnl": (mark - p.avg_price) * p.quantity, "realized_pnl": p.realized_pnl,
            })
        equity = self.equity()
        return {
            "exchange": f"paper ({getattr(self.feed, 'name', 'feed')} prices)",
            "mode": "paper", "cash": self.cash, "equity": equity,
            "pnl": equity - self.starting_cash, "positions": positions,
            "open_orders": [o.to_dict() for o in self.open_orders.values()],
        }
