"""Stores the Liquid API key/secret in the OS keychain (macOS Keychain) when available,
falling back to the .env file (created with owner-only permissions)."""
from __future__ import annotations

SERVICE = "Liquid Strategy Trader"

try:
    import keyring
    from keyring.errors import KeyringError
except Exception:  # keyring not installed
    keyring = None
    KeyringError = Exception


def _usable() -> bool:
    if keyring is None:
        return False
    try:
        backend = keyring.get_keyring()
        return backend.priority > 0 and "fail" not in type(backend).__module__
    except Exception:
        return False


def get(name: str) -> str:
    if not _usable():
        return ""
    try:
        return keyring.get_password(SERVICE, name) or ""
    except KeyringError:
        return ""


def set(name: str, value: str) -> bool:
    """Returns True if stored in the keychain, False if the caller must use the .env file."""
    if not _usable():
        return False
    try:
        if value:
            keyring.set_password(SERVICE, name, value)
        else:
            try:
                keyring.delete_password(SERVICE, name)
            except Exception:
                pass
        return True
    except KeyringError:
        return False


def backend_name() -> str:
    return "macOS Keychain" if _usable() and "macOS" in type(keyring.get_keyring()).__module__ else (
        "system keychain" if _usable() else ".env file")
