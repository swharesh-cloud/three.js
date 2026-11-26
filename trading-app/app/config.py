"""Settings loaded from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import secret_store

ROOT = Path(__file__).resolve().parent.parent


def env_file() -> Path:
    return Path(os.environ.get("ENV_FILE", str(ROOT / ".env")))


def _read_dotenv(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


_from_file: set[str] = set()


def _load_dotenv(path: Path) -> None:
    """Load .env values. Values that came from the file are refreshed on every call, so
    settings saved from the app take effect; real environment variables still win."""
    for key, value in _read_dotenv(path).items():
        if key not in os.environ or key in _from_file:
            os.environ[key] = value
            _from_file.add(key)


def save_env(updates: dict[str, str]) -> None:
    """Update or add keys in the .env file, keeping comments and other lines."""
    path = env_file()
    lines = path.read_text().splitlines() if path.exists() else []
    pending = dict(updates)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in pending:
            lines[i] = f"{key}={pending.pop(key)}"
    lines += [f"{k}={v}" for k, v in pending.items()]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    for key, value in updates.items():
        if key not in os.environ or key in _from_file:
            os.environ[key] = value
            _from_file.add(key)


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
    _load_dotenv(env_file())
    env = os.environ.get
    data_dir = Path(env("DATA_DIR", str(ROOT / "data")))
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        trading_mode=env("TRADING_MODE", "paper").lower(),
        live_confirmed=env("LIVE_TRADING_CONFIRM", "") == "I_UNDERSTAND",
        market_data=env("MARKET_DATA", "simulated").lower(),
        liquid_api_base=env("LIQUID_API_BASE", "https://api.liquid.trade").rstrip("/"),
        liquid_api_key=env("LIQUID_API_KEY", "") or secret_store.get("LIQUID_API_KEY"),
        liquid_api_secret=env("LIQUID_API_SECRET", "") or secret_store.get("LIQUID_API_SECRET"),
        liquid_endpoints_file=env("LIQUID_ENDPOINTS_FILE", ""),
        paper_starting_cash=float(env("PAPER_STARTING_CASH", "10000")),
        paper_fee_rate=float(env("PAPER_FEE_RATE", "0.0005")),
        max_order_notional=float(env("MAX_ORDER_NOTIONAL", "1000")),
        max_position_notional=float(env("MAX_POSITION_NOTIONAL", "5000")),
        max_daily_loss=float(env("MAX_DAILY_LOSS", "500")),
        data_dir=data_dir,
    )
