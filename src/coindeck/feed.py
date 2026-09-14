"""Coinbase Exchange public market data: REST for history, a websocket for live
prices and trades. No API key. A demo market with the same shape runs offline."""

from __future__ import annotations

import asyncio
import json
import math
import random
import time
import zlib
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from .market import Candle, Product, Ticker, Trade

API = "https://api.exchange.coinbase.com"
WS = "wss://ws-feed.exchange.coinbase.com"
PAGE = 300          # Coinbase returns at most 300 candles per request
USER_AGENT = "coindeck/0.1 (terminal market watcher)"


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def _ts(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return time.time()


def _f(d: dict, k: str) -> float:
    try:
        return float(d.get(k) or 0)
    except (TypeError, ValueError):
        return 0.0


class Client:
    """REST. Requests go one at a time with a small gap: the public limit is
    about 10 a second and a watchlist refresh would otherwise burst past it."""

    demo = False

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(base_url=API, timeout=12,
                                       headers={"User-Agent": USER_AGENT})
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def close(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict | None = None):
        async with self._lock:
            for attempt in range(4):
                wait = self._last + 0.15 - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                r = await self._http.get(path, params=params)
                self._last = time.monotonic()
                if r.status_code == 429:
                    await asyncio.sleep(1.0 + attempt)
                    continue
                r.raise_for_status()
                return r.json()
            r.raise_for_status()
            return r.json()

    async def products(self) -> list[Product]:
        data = await self._get("/products")
        out = [Product(p["id"], p["base_currency"], p["quote_currency"],
                       p.get("quote_increment") or "0.01", p.get("status", ""))
               for p in data
               if p.get("status") == "online" and not p.get("trading_disabled")]
        out.sort(key=lambda p: p.id)
        return out

    async def stats(self) -> dict[str, Ticker]:
        """24h stats for every product in one request."""
        data = await self._get("/products/stats")
        out = {}
        for pid, d in data.items():
            s24 = d.get("stats_24hour") or {}
            s30 = d.get("stats_30day") or {}
            out[pid] = Ticker(price=_f(s24, "last"), open_24h=_f(s24, "open"),
                              high_24h=_f(s24, "high"), low_24h=_f(s24, "low"),
                              volume_24h=_f(s24, "volume"), volume_30d=_f(s30, "volume"),
                              updated=time.time())
        return out

    async def candles(self, product: str, granularity: int, end: float | None = None) -> list[Candle]:
        """One page of up to 300 candles ending at `end` (now by default), oldest first."""
        end = end if end is not None else time.time()
        start = end - PAGE * granularity
        data = await self._get(f"/products/{product}/candles", {
            "granularity": granularity, "start": _iso(start), "end": _iso(end)})
        # [time, low, high, open, close, volume], newest first
        out = [Candle(int(r[0]), float(r[3]), float(r[2]), float(r[1]), float(r[4]), float(r[5]))
               for r in data if len(r) >= 6]
        out.sort(key=lambda c: c.t)
        return out


class Feed:
    """Websocket: `ticker` for every watched product, `matches` for the one on
    the chart. Reconnects with backoff; resubscribes on every connect."""

    def __init__(self, on_ticker: Callable[[str, dict], None],
                 on_trade: Callable[[str, Trade], None],
                 on_status: Callable[[str, str], None]) -> None:
        self.on_ticker = on_ticker
        self.on_trade = on_trade
        self.on_status = on_status
        self.tickers: set[str] = set()
        self.trades: str | None = None
        self._sub_tickers: set[str] = set()
        self._sub_trades: str | None = None
        self._ws = None
        self.status = "connecting"
        self.messages = 0

    def _set_status(self, status: str, detail: str = "") -> None:
        self.status = status
        self.on_status(status, detail)

    def want(self, tickers: set[str], trades: str | None) -> None:
        self.tickers = set(tickers)
        self.trades = trades
        if self._ws is not None:
            asyncio.ensure_future(self._resubscribe())

    async def _send(self, kind: str, channels: list[dict]) -> None:
        if self._ws is None or not channels:
            return
        await self._ws.send(json.dumps({"type": kind, "channels": channels}))

    async def _resubscribe(self) -> None:
        try:
            gone = self._sub_tickers - self.tickers
            new = self.tickers - self._sub_tickers
            unsub, sub = [], []
            if gone:
                unsub.append({"name": "ticker", "product_ids": sorted(gone)})
            if new:
                sub.append({"name": "ticker", "product_ids": sorted(new)})
            if self._sub_trades != self.trades:
                if self._sub_trades:
                    unsub.append({"name": "matches", "product_ids": [self._sub_trades]})
                if self.trades:
                    sub.append({"name": "matches", "product_ids": [self.trades]})
            await self._send("unsubscribe", unsub)
            await self._send("subscribe", sub)
            self._sub_tickers = set(self.tickers)
            self._sub_trades = self.trades
        except Exception:
            pass    # the read loop notices a dead socket and reconnects

    async def run(self) -> None:
        import websockets

        delay = 1.0
        while True:
            self._set_status("connecting")
            try:
                async with websockets.connect(WS, open_timeout=10, ping_interval=20,
                                              max_size=2**22,
                                              user_agent_header=USER_AGENT) as ws:
                    self._ws = ws
                    self._sub_tickers, self._sub_trades = set(), None
                    # one heartbeat a second keeps the read timeout honest on quiet pairs
                    await ws.send(json.dumps({"type": "subscribe", "channels": [
                        {"name": "heartbeat", "product_ids": ["BTC-USD"]}]}))
                    await self._resubscribe()
                    delay = 1.0
                    live = False
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        msg = json.loads(raw)
                        if not live and msg.get("type") in ("subscriptions", "ticker", "heartbeat"):
                            live = True
                            self._set_status("live")
                        self._handle(msg)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._ws = None
                self._set_status("offline", f"{type(exc).__name__}: {exc}"[:120])
            self._ws = None
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)

    def _handle(self, msg: dict) -> None:
        kind = msg.get("type")
        self.messages += 1
        if kind == "ticker":
            self.on_ticker(msg.get("product_id", ""), {
                "price": _f(msg, "price"), "open_24h": _f(msg, "open_24h"),
                "high_24h": _f(msg, "high_24h"), "low_24h": _f(msg, "low_24h"),
                "volume_24h": _f(msg, "volume_24h"), "volume_30d": _f(msg, "volume_30d"),
                "bid": _f(msg, "best_bid"), "ask": _f(msg, "best_ask"),
                "time": _ts(msg.get("time", "")),
            })
        elif kind in ("match", "last_match"):
            # `side` is the maker's side; a sell maker means the taker bought
            self.on_trade(msg.get("product_id", ""), Trade(
                _ts(msg.get("time", "")), _f(msg, "price"), _f(msg, "size"),
                buy=msg.get("side") == "sell"))
        elif kind == "error":
            self.on_status(self.status, str(msg.get("message", "error")))


# ---------------------------------------------------------------------- demo --

DEMO_MARKETS = {
    "BTC": 77000, "ETH": 2500, "SOL": 140, "XRP": 0.52, "DOGE": 0.11, "ADA": 0.38,
    "LINK": 13.2, "AVAX": 24.5, "LTC": 68, "SUI": 1.9, "PEPE": 0.0000092, "SHIB": 0.0000142,
    "HBAR": 0.061, "DOT": 4.4, "UNI": 7.1, "AAVE": 150, "NEAR": 4.2, "APT": 6.3, "ARB": 0.52,
    "OP": 1.45, "ATOM": 4.6, "BCH": 330, "XLM": 0.095, "FIL": 3.4, "ICP": 8.1, "INJ": 19.0,
}


def _hash(seed: int, i: int) -> float:
    h = (seed * 0x9E3779B1 + i * 0x85EBCA77) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 0x2C1B3C6D) & 0xFFFFFFFF
    h ^= h >> 12
    h = (h * 0x297A2D39) & 0xFFFFFFFF
    h ^= h >> 15
    return h / 0x7FFFFFFF - 1.0


def _noise(seed: int, x: float) -> float:
    """Smooth value noise in [-1, 1]."""
    i = math.floor(x)
    f = x - i
    a, b = _hash(seed, i), _hash(seed, i + 1)
    f = f * f * (3 - 2 * f)
    return a + (b - a) * f


def demo_price(base: str, t: float) -> float:
    seed = zlib.crc32(base.encode())
    p0 = DEMO_MARKETS.get(base, 10.0)
    vol = 1.6 if base in ("PEPE", "SHIB", "DOGE") else 1.0
    x = 0.0
    for period, amp in ((86400 * 90, 0.35), (86400 * 14, 0.12), (86400 * 2, 0.05),
                        (3600 * 6, 0.02), (3600, 0.008), (600, 0.003), (60, 0.0012), (8, 0.0004)):
        x += _noise(seed + period, t / period) * amp * vol
    return p0 * math.exp(x)


def demo_pair_price(pid: str, t: float) -> float:
    base, _, quote = pid.partition("-")
    p = demo_price(base, t)
    return p / demo_price("BTC", t) if quote == "BTC" else p


class DemoClient:
    demo = True

    async def close(self) -> None:
        pass

    async def products(self) -> list[Product]:
        out = []
        for base, p in DEMO_MARKETS.items():
            inc = "0.01" if p >= 1 else f"{10 ** (math.floor(math.log10(p)) - 4):.10f}".rstrip("0")
            out.append(Product(f"{base}-USD", base, "USD", inc))
            out.append(Product(f"{base}-USDC", base, "USDC", inc))
            if base != "BTC":
                out.append(Product(f"{base}-BTC", base, "BTC", "0.00000001"))
        out.sort(key=lambda p: p.id)
        return out

    async def stats(self) -> dict[str, Ticker]:
        now = time.time()
        out = {}
        for prod in await self.products():
            samples = [demo_pair_price(prod.id, now - 86400 + i * 900) for i in range(97)]
            price = demo_pair_price(prod.id, now)
            usd = demo_price(prod.base, now)
            share = {"USD": 1.0, "USDC": 0.2, "BTC": 0.05}.get(prod.quote, 0.1)
            vol = 1e8 / usd * share * (1.5 + _noise(zlib.crc32(prod.id.encode()), now / 86400))
            out[prod.id] = Ticker(price=price, open_24h=samples[0], high_24h=max(samples),
                                  low_24h=min(samples), volume_24h=vol, volume_30d=vol * 31,
                                  bid=price * 0.9999, ask=price * 1.0001, updated=now)
        return out

    async def candles(self, product: str, granularity: int, end: float | None = None) -> list[Candle]:
        await asyncio.sleep(0.05)
        end = end if end is not None else time.time()
        first = int((end - PAGE * granularity) // granularity * granularity) + granularity
        seed = zlib.crc32(product.encode())
        out = []
        for t in range(first, int(end) + 1, granularity):
            if t > time.time():
                break
            steps = 10
            pts = [demo_pair_price(product, min(t + granularity * k / steps, time.time()))
                   for k in range(steps + 1)]
            v = granularity / 60 * (2.0 + 1.5 * _noise(seed, t / (granularity * 7))
                                    + abs(pts[-1] - pts[0]) / pts[0] * 400)
            out.append(Candle(t, pts[0], max(pts), min(pts), pts[-1], max(v, 0.1)))
        return out


class DemoFeed(Feed):
    async def run(self) -> None:
        self._set_status("live", "demo market")
        rng = random.Random(7)
        while True:
            now = time.time()
            for pid in sorted(self.tickers):
                price = demo_pair_price(pid, now)
                self.on_ticker(pid, {"price": price, "bid": price * 0.9999, "ask": price * 1.0001,
                                     "time": now})
            if self.trades:
                price = demo_pair_price(self.trades, now)
                for _ in range(rng.randint(0, 3)):
                    size = rng.expovariate(1.0) * 2000 / max(price, 1e-9) * rng.choice((0.1, 1, 1, 5))
                    self.on_trade(self.trades, Trade(now, price * (1 + rng.uniform(-2e-4, 2e-4)),
                                                     size, rng.random() < 0.5))
            self.messages += 1
            await asyncio.sleep(0.25)
