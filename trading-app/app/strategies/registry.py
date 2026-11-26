"""Discovers Strategy subclasses in app/strategies/builtin.py and user_strategies/*.py."""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from pathlib import Path

from . import builtin
from .base import Strategy

USER_DIR = Path(__file__).resolve().parent.parent.parent / "user_strategies"


def _collect(module) -> dict[str, type[Strategy]]:
    found = {}
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, Strategy) and obj is not Strategy and obj.__module__ == module.__name__:
            found[f"{module.__name__.split('.')[-1]}.{obj.__name__}"] = obj
    return found


def discover(user_dir: Path = USER_DIR) -> tuple[dict[str, type[Strategy]], list[str]]:
    registry = _collect(builtin)
    errors = []
    for path in sorted(user_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        mod_name = f"user_strategies.{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
            registry.update(_collect(module))
        except Exception as exc:  # show broken user files in the UI instead of crashing
            errors.append(f"{path.name}: {exc!r}")
    return registry, errors
