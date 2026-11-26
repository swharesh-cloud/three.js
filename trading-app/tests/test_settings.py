import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment kept\nTRADING_MODE=paper\nMARKET_DATA=simulated\n")
    monkeypatch.setenv("ENV_FILE", str(env))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    for k in ("LIQUID_API_KEY", "LIQUID_API_SECRET", "LIQUID_API_BASE", "LIVE_TRADING_CONFIRM"):
        monkeypatch.delenv(k, raising=False)
    from app import secret_store
    store = {}
    monkeypatch.setattr(secret_store, "get", lambda n: store.get(n, ""))
    monkeypatch.setattr(secret_store, "set", lambda n, v: store.__setitem__(n, v) or True)
    from app import config
    config._from_file.clear()
    from app.main import app
    with TestClient(app) as c:
        c.env_path, c.store = env, store
        yield c
    for k in list(config._from_file):
        os.environ.pop(k, None)
    config._from_file.clear()


def test_save_key_goes_to_keychain_not_file(client):
    r = client.post("/api/settings", json={"liquid_api_base": "https://api.example.test", "api_key": "abcd1234efgh5678"})
    assert r.status_code == 200, r.text
    assert r.json()["api_key"] == "saved, ends in 5678"
    text = client.env_path.read_text()
    assert "abcd1234" not in text and "# comment kept" in text
    assert "LIQUID_API_BASE=https://api.example.test" in text
    assert client.store["LIQUID_API_KEY"] == "abcd1234efgh5678"


def test_live_mode_requires_confirmation(client):
    client.post("/api/settings", json={"trading_mode": "live", "live_confirmed": False})
    assert client.get("/api/status").json()["mode"] == "paper"
    client.post("/api/settings", json={"trading_mode": "live", "live_confirmed": True})
    assert client.get("/api/status").json()["mode"] == "live"
    client.post("/api/settings", json={"trading_mode": "paper"})
    assert client.get("/api/status").json()["mode"] == "paper"


def test_rejects_non_https_and_bad_limits(client):
    assert client.post("/api/settings", json={"liquid_api_base": "http://x"}).status_code == 400
    assert client.post("/api/settings", json={"max_daily_loss": -5}).status_code == 400


def test_strategies_survive_reconnect(client):
    types = client.get("/api/strategy-types").json()
    key = next(k for k, t in types.items() if t["name"] == "Grid")
    client.post("/api/strategies", json={"type": key, "symbol": "ETH-USD"})
    client.post("/api/settings", json={"max_order_notional": 250})
    assert len(client.get("/api/strategies").json()) == 1
    assert client.get("/api/status").json()["limits"]["max_order_notional"] == 250
