"""Settings loaded from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass
class Settings:
    trading_mode: str
    live_confirmed: bool
    market_data: str
    liquid_api_base: str
    liquid_api_key: str
    liquid_api_secret: str
    liquid_endpoints_file: str
    paper_starting_cash: float
    paper_fee_rate: float
    max_order_notional: float
    max_position_notional: float
    max_daily_loss: float
    data_dir: Path

    @property
    def is_live(self) -> bool:
        return self.trading_mode == "live" and self.live_confirmed


def load_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    env = os.environ.get
    data_dir = Path(env("DATA_DIR", str(ROOT / "data")))
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        trading_mode=env("TRADING_MODE", "paper").lower(),
        live_confirmed=env("LIVE_TRADING_CONFIRM", "") == "I_UNDERSTAND",
        market_data=env("MARKET_DATA", "simulated").lower(),
        liquid_api_base=env("LIQUID_API_BASE", "https://api.liquid.trade").rstrip("/"),
        liquid_api_key=env("LIQUID_API_KEY", ""),
        liquid_api_secret=env("LIQUID_API_SECRET", ""),
        liquid_endpoints_file=env("LIQUID_ENDPOINTS_FILE", ""),
        paper_starting_cash=float(env("PAPER_STARTING_CASH", "10000")),
        paper_fee_rate=float(env("PAPER_FEE_RATE", "0.0005")),
        max_order_notional=float(env("MAX_ORDER_NOTIONAL", "1000")),
        max_position_notional=float(env("MAX_POSITION_NOTIONAL", "5000")),
        max_daily_loss=float(env("MAX_DAILY_LOSS", "500")),
        data_dir=data_dir,
    )
