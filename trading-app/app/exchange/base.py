"""Common exchange interface used by the strategy engine."""
from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict


@dataclass
class Order:
    symbol: str
    side: str  # "buy" | "sell"
    quantity: float
    type: str = "market"  # "market" | "limit"
    price: float | None = None
    strategy_id: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "new"  # new | filled | open | cancelled | rejected
    fill_price: float | None = None
    fee: float = 0.0
    reason: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0
    realized_pnl: float = 0.0


class Exchange(ABC):
    name = "base"

    @abstractmethod
    async def get_price(self, symbol: str) -> float: ...

    async def get_candles(self, symbol: str, interval: str = "1m", limit: int = 100) -> list[float]:
        """Return recent close prices, oldest first. Optional for adapters."""
        return []

    @abstractmethod
    async def place_order(self, order: Order) -> Order: ...

    @abstractmethod
    async def cancel_order(self, order_id: str, symbol: str | None = None) -> bool: ...

    @abstractmethod
    async def get_account(self) -> dict: ...

    async def close(self) -> None:
        return None
