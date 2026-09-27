"""Plain data: candles, tickers, trades, timeframes, and number formatting."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

# Monday 1970-01-05 00:00 UTC. Coinbase weeks start on Monday, epoch day 0 was a Thursday.
WEEK_ANCHOR = 4 * 86400


@dataclass(frozen=True)
class Timeframe:
    name: str
    seconds: int
    base: int          # granularity Coinbase serves; candles are merged up when it differs

    @property
    def factor(self) -> int:
        return self.seconds // self.base

    def bucket(self, ts: float) -> int:
        if self.seconds == 604800:
            return int((ts - WEEK_ANCHOR) // self.seconds * self.seconds + WEEK_ANCHOR)
        return int(ts // self.seconds * self.seconds)


TIMEFRAMES = [
    Timeframe("1m", 60, 60),
    Timeframe("5m", 300, 300),
    Timeframe("15m", 900, 900),
    Timeframe("1h", 3600, 3600),
    Timeframe("4h", 14400, 3600),
    Timeframe("6h", 21600, 21600),
    Timeframe("1d", 86400, 86400),
    Timeframe("1w", 604800, 86400),
]
TF_BY_NAME = {tf.name: tf for tf in TIMEFRAMES}


@dataclass
class Candle:
    t: int          # bucket start, unix seconds
    o: float
    h: float
    l: float
    c: float
    v: float

    @property
    def up(self) -> bool:
        return self.c >= self.o


MAX_GAP_FILL = 500


def merge_candles(base: list[Candle], tf: Timeframe) -> list[Candle]:
    """Coinbase candles (oldest first) folded into tf buckets.

    Coinbase leaves out buckets with no trades. Those come back as flat
    zero-volume candles at the previous close, so the x axis stays linear in time."""
    out: list[Candle] = []
    for c in base:
        b = tf.bucket(c.t)
        if out and out[-1].t == b:
            last = out[-1]
            last.h = max(last.h, c.h)
            last.l = min(last.l, c.l)
            last.c = c.c
            last.v += c.v
            continue
        if out:
            prev = out[-1]
            missing = (b - prev.t) // tf.seconds - 1 if tf.seconds != 604800 else 0
            if 0 < missing <= MAX_GAP_FILL:
                for k in range(1, missing + 1):
                    out.append(Candle(prev.t + k * tf.seconds, prev.c, prev.c, prev.c, prev.c, 0.0))
        out.append(Candle(b, c.o, c.h, c.l, c.c, c.v))
    return out


@dataclass
class Series:
    """Candles for one product at one timeframe, oldest first."""
    product: str
    tf: Timeframe
    candles: list[Candle] = field(default_factory=list)
    base: list[Candle] = field(default_factory=list)   # as served, before merging up
    loading: bool = False
    exhausted: bool = False      # no older history on the exchange
    fetched: float = 0.0
    error: str = ""

    @property
    def oldest_base(self) -> int | None:
        return self.base[0].t if self.base else None

    def merge(self, fresh: list[Candle]) -> None:
        """Fold exchange candles in by time (later data wins), then rebuild the
        tf candles from all of them so a bucket split across pages comes out whole."""
        if not fresh:
            return
        by_t = {c.t: c for c in self.base}
        for c in fresh:
            by_t[c.t] = c
        self.base = [by_t[t] for t in sorted(by_t)]
        live_tail = self.candles[-2:] if self.candles else []
        self.candles = merge_candles([Candle(c.t, c.o, c.h, c.l, c.c, c.v) for c in self.base],
                                     self.tf)
        # a candle opened by live trades that the exchange has not published yet
        for c in live_tail:
            if self.candles and c.t > self.candles[-1].t:
                self.candles.append(c)

    def apply_trade(self, price: float, size: float, ts: float) -> None:
        """Move the live candle with a trade, or open the next one."""
        if not self.candles:
            return
        b = self.tf.bucket(ts)
        last = self.candles[-1]
        if b == last.t:
            last.h = max(last.h, price)
            last.l = min(last.l, price)
            last.c = price
            last.v += size
        elif b > last.t:
            self.candles.append(Candle(b, last.c, max(last.c, price), min(last.c, price), price, size))


@dataclass
class Product:
    id: str
    base: str
    quote: str
    quote_increment: str = "0.01"
    status: str = "online"

    @property
    def decimals(self) -> int:
        inc = self.quote_increment
        if "." not in inc:
            return 0
        return len(inc.split(".")[1].rstrip("0")) or 0


@dataclass
class Ticker:
    price: float = 0.0
    open_24h: float = 0.0
    high_24h: float = 0.0
    low_24h: float = 0.0
    volume_24h: float = 0.0
    volume_30d: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    updated: float = 0.0
    last_move: int = 0           # +1 uptick, -1 downtick, for the flash
    moved_at: float = 0.0

    @property
    def change(self) -> float:
        return self.price - self.open_24h if self.open_24h else 0.0

    @property
    def change_pct(self) -> float:
        return (self.price / self.open_24h - 1) * 100 if self.open_24h else 0.0

    def set_price(self, price: float) -> None:
        if self.price and price != self.price:
            self.last_move = 1 if price > self.price else -1
            self.moved_at = time.monotonic()
        self.price = price
        self.updated = time.time()


@dataclass
class Trade:
    t: float
    price: float
    size: float
    buy: bool           # taker bought (price lifted the ask)


# ---------------------------------------------------------------- formatting --

def price_decimals(price: float, max_decimals: int = 8) -> int:
    """Enough decimals to see movement, not so many the column explodes."""
    if price <= 0:
        return 2
    if price >= 1000:
        d = 2
    elif price >= 1:
        d = 4 if price < 10 else 3 if price < 100 else 2
    else:
        d = -math.floor(math.log10(price)) + 3
    return max(0, min(d, max_decimals))


def fmt_price(price: float, decimals: int | None = None) -> str:
    if decimals is None:
        decimals = price_decimals(price)
    return f"{price:,.{decimals}f}"


def fmt_compact(n: float) -> str:
    a = abs(n)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            return f"{n / div:.2f}{suf}"
    if a >= 100:
        return f"{n:.0f}"
    if a >= 1:
        return f"{n:.2f}"
    return f"{n:.4g}"


def fmt_pct(p: float) -> str:
    return f"{p:+.2f}%"


def fmt_size(s: float) -> str:
    if s >= 1000:
        return f"{s:,.0f}"
    if s >= 1:
        return f"{s:.3f}"
    return f"{s:.8f}".rstrip("0").rstrip(".") or "0"


def fmt_amount(a: float) -> str:
    """A token amount as the wallet shows it: every decimal, no trailing zeros."""
    return f"{a:,.8f}".rstrip("0").rstrip(".") or "0"


def fmt_usd(v: float) -> str:
    return f"${v:,.2f}" if v >= 0 else f"-${-v:,.2f}"


SPARK = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float], width: int) -> str:
    if not values or width <= 0:
        return ""
    if len(values) > width:
        step = len(values) / width
        values = [values[min(len(values) - 1, int(i * step + step - 1))] for i in range(width)]
    lo, hi = min(values), max(values)
    if hi - lo <= 0:
        return SPARK[3] * len(values)
    return "".join(SPARK[min(7, int((v - lo) / (hi - lo) * 7.999))] for v in values)
