"""Watchlist, holdings and view settings in ~/.config/coindeck/state.json; the product
list is cached in ~/.cache/coindeck so the add popup opens instantly."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .market import TF_BY_NAME, Product

DEFAULT_WATCHLIST = [
    "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD",
    "ADA-USD", "LINK-USD", "AVAX-USD", "SUI-USD", "LTC-USD",
]


def config_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "coindeck"


def cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "coindeck"


@dataclass
class State:
    watchlist: list[str] = field(default_factory=lambda: list(DEFAULT_WATCHLIST))
    selected: str = "BTC-USD"
    timeframe: str = "1h"
    zoom: int = 1
    mode: str = "candles"
    volume: bool = True
    holdings: dict[str, float] = field(default_factory=dict)    # base currency -> amount owned

    @classmethod
    def load(cls, demo: bool = False) -> "State":
        path = cls.path(demo)
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            return cls()
        st = cls()
        wl = data.get("watchlist")
        if isinstance(wl, list) and all(isinstance(x, str) for x in wl):
            st.watchlist = wl
        if isinstance(data.get("selected"), str):
            st.selected = data["selected"]
        if data.get("timeframe") in TF_BY_NAME:
            st.timeframe = data["timeframe"]
        if isinstance(data.get("zoom"), int):
            st.zoom = data["zoom"]
        if data.get("mode") in ("candles", "line"):
            st.mode = data["mode"]
        if isinstance(data.get("volume"), bool):
            st.volume = data["volume"]
        held = data.get("holdings")
        if isinstance(held, dict):
            st.holdings = {k: float(v) for k, v in held.items()
                           if isinstance(k, str) and isinstance(v, (int, float)) and v > 0}
        return st

    @staticmethod
    def path(demo: bool = False) -> Path:
        return config_dir() / ("state-demo.json" if demo else "state.json")

    def save(self, demo: bool = False) -> None:
        path = self.path(demo)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self), indent=1) + "\n")
            tmp.replace(path)
        except OSError:
            pass


PRODUCTS_MAX_AGE = 7 * 86400


def load_products() -> list[Product] | None:
    path = cache_dir() / "products.json"
    try:
        data = json.loads(path.read_text())
        if time.time() - data["saved"] > PRODUCTS_MAX_AGE:
            return None
        return [Product(**p) for p in data["products"]]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_products(products: list[Product]) -> None:
    path = cache_dir() / "products.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"saved": time.time(),
                                    "products": [asdict(p) for p in products]}))
    except OSError:
        pass
