"""Standalone desktop launcher: runs the server in the background and shows the UI in a native window.

Settings (.env), saved strategies and your own strategy files live in:
  macOS:   ~/Library/Application Support/Liquid Strategy Trader/
  others:  ~/.liquid-strategy-trader/
"""
from __future__ import annotations

import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "Liquid Strategy Trader"


def bundle_root() -> Path:
    # PyInstaller unpacks bundled files into sys._MEIPASS; from source, use the project folder.
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def support_dir() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = Path.home() / ".liquid-strategy-trader"
    base.mkdir(parents=True, exist_ok=True)
    return base


def prepare_environment() -> Path:
    home, root = support_dir(), bundle_root()
    sys.path.insert(0, str(root))
    env_file = home / ".env"
    if not env_file.exists() and (root / ".env.example").exists():
        text = (root / ".env.example").read_text().replace(
            "LIQUID_ENDPOINTS_FILE=", f"LIQUID_ENDPOINTS_FILE={home / 'liquid_endpoints.json'}")
        env_file.write_text(text)
        env_file.chmod(0o600)
    strategies = home / "strategies"
    if not strategies.exists():
        strategies.mkdir()
        for example in (root / "user_strategies").glob("*.py"):
            shutil.copy(example, strategies / example.name)
    endpoints = home / "liquid_endpoints.json"
    if not endpoints.exists() and (root / "liquid_endpoints.example.json").exists():
        shutil.copy(root / "liquid_endpoints.example.json", endpoints)
    os.environ.setdefault("ENV_FILE", str(env_file))
    os.environ.setdefault("DATA_DIR", str(home / "data"))
    os.environ.setdefault("USER_STRATEGIES_DIR", str(strategies))
    sys.path.insert(0, str(home))  # lets strategy files import each other
    return home


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int):
    import uvicorn
    from app.main import app

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/api/status", timeout=0.5)
            return server, url
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("The trading server did not start. See the log in the settings folder.")


def main() -> None:
    home = prepare_environment()
    if getattr(sys, "frozen", False):
        log = open(home / "app.log", "a", buffering=1)
        sys.stdout = sys.stderr = log
    headless = "--headless" in sys.argv
    server, url = start_server(free_port())
    print(f"{APP_NAME} running at {url} (settings in {home})", flush=True)
    if headless:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        try:
            import webview  # pywebview: native window (WKWebView on macOS)
        except ImportError:
            webbrowser.open(url)
            while True:
                time.sleep(1)
        window = webview.create_window(APP_NAME, url, width=1320, height=900, min_size=(900, 600))
        webview.start()
    server.should_exit = True
    time.sleep(0.5)


if __name__ == "__main__":
    main()
