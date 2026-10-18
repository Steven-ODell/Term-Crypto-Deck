"""The paper trader's loop, apart from any screen so it keeps running while the
chart page is up. Prices are polled every few seconds for stops and the P&L
line; on every candle close the six coins are rescanned, an open position exits
on the opposite cross, and a flat account takes the best signal.

Nothing runs until start(): the first time the Cipher page opens, or at launch
when the saved account has an open position."""

from __future__ import annotations

import json
import math
import os
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from rich.text import Text

from .coinbase import DemoMarket, Market
from .paper import COINS, PERPS, Config, Paper, Quote, Skip
from .strategy import Read, exit_now, pick, read_last

TF = {"5m": 300, "15m": 900, "1h": 3600, "6h": 21600}
GREEN, PINK, PURPLE, CYAN, DIM = "#5fd75f", "#ff5ea0", "#b07cf5", "#5ef1ff", "#7a7a7a"
FRESH = 120         # only trade a candle that closed this many seconds ago or less
SCAN_DELAY = 8      # Coinbase publishes a candle a few seconds after it closes


def data_dir() -> Path:
    # still named cipherdeck: the paper account from before the merge lives here
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(base) / "cipherdeck"


def money(x: float, sign: bool = False) -> str:
    s = f"{abs(x):,.2f}"
    if sign:
        return ("+$" if x >= 0 else "-$") + s
    return ("-$" if x < 0 else "$") + s


def px(x: float) -> str:
    if x <= 0 or math.isnan(x):
        return "-"
    d = 2 if x >= 100 else 3 if x >= 10 else 4 if x >= 1 else 5
    return f"{x:,.{d}f}"


def hm(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def dur(s: float) -> str:
    s = int(s)
    return f"{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"


class Bot:
    def __init__(self, tf: str = "15m", cfg: Config | None = None, demo: bool = False,
                 reset: bool = False) -> None:
        self.demo = demo
        self.tf_name = tf
        self.tf = TF[tf]
        self.cfg = cfg or Config()
        self.reset_first = reset
        d = data_dir()
        self.state_path = d / ("paper-demo.json" if demo else "paper.json")
        self.log_path = d / ("events-demo.log" if demo else "events.log")
        self.market = None
        self.acct = Paper(self.cfg)       # replaced by the saved account in start()
        self.reads: dict[str, Read] = {}
        self.spot: dict[str, Quote] = {}
        self.perp: dict[str, Quote] = {}
        self.acted_t = 0            # newest candle already traded on
        self.next_scan = math.inf     # boot() runs the first scan
        self.paused = False
        self.feed = "starting"
        self.reset_armed = 0.0
        self.busy = False
        self.started = False
        self.app = None
        self.lines: deque[Text] = deque(maxlen=2000)
        self.sink = None            # the page's log, written to as lines arrive

    def has_open_position(self) -> bool:
        """A saved account holding something: coindeck starts the bot at launch
        then, so its stop is watched even if the Cipher page is never opened."""
        if self.demo or self.reset_first or not self.state_path.exists():
            return False
        try:
            return bool(json.loads(self.state_path.read_text()).get("position"))
        except (OSError, ValueError):
            return False

    def start(self, app) -> None:
        if self.started:
            return
        self.started = True
        self.app = app
        self.market = DemoMarket() if self.demo else Market()
        if self.reset_first or self.demo:
            self.state_path.unlink(missing_ok=True)
        self.acct = Paper.load(self.cfg, self.state_path)
        mode = "DEMO market" if self.demo else "Coinbase live prices"
        self.say(f"paper account {money(self.acct.equity(None))}, {self.tf_name} candles, {mode}", PURPLE)
        if self.acct.position:
            p = self.acct.position
            self.say(f"resumed open {p.side} {p.coin} from {hm(p.opened)}", PURPLE)
        app.run_worker(self.boot(), group="cipher-boot", exclusive=True)
        app.set_interval(1.0 if self.demo else 5.0, self._poll)
        app.set_interval(1.0, self.tick)

    async def boot(self) -> None:
        try:
            self.cfg.base_inc.update(await self.market.base_increments(COINS))
        except Exception as e:     # sizes fall back to unrounded
            self.say(f"couldn't load size steps: {e}", PINK)
        await self.scan()

    async def close(self) -> None:
        if self.market is not None:
            await self.market.close()

    # -------------------------------------------------------------- loop --

    def tick(self) -> None:
        if time.time() >= self.next_scan and not self.busy:
            self.run_scan()

    def schedule_next(self) -> None:
        if self.demo:
            self.next_scan = time.time() + 1
            return
        now = time.time()
        self.next_scan = (now // self.tf + 1) * self.tf + SCAN_DELAY

    def run_scan(self) -> None:
        self.app.run_worker(self.scan(), group="cipher-scan", exclusive=True)

    async def scan(self) -> None:
        self.busy = True
        self.schedule_next()
        try:
            reads = {}
            for c in COINS:
                candles = await self.market.candles(c, self.tf, 250)
                if len(candles) > 80:
                    reads[c] = read_last(c, candles)
            self.reads = reads
            self.feed = "live"
        except Exception as e:
            self.feed = "error"
            self.say(f"scan failed: {e}", PINK)
            self.next_scan = time.time() + 20
            self.busy = False
            return
        try:
            await self.decide()
        except Exception as e:
            self.say(f"order step failed: {e}", PINK)
        self.busy = False

    async def decide(self) -> None:
        if not self.reads:
            return
        newest = max(r.t for r in self.reads.values())
        fresh = self.demo or time.time() - (newest + self.tf) <= FRESH
        sigs = [r for r in self.reads.values() if r.signal]
        if sigs:
            self.say("signals: " + ", ".join(f"{r.coin} {r.signal} {r.score:.0f}"
                                             for r in sorted(sigs, key=lambda r: -r.score)), DIM)
        if newest <= self.acted_t or not fresh:
            return
        self.acted_t = newest
        p = self.acct.position
        if p and (r := self.reads.get(p.coin)) and exit_now(p.side, r):
            q = await self.quote(p.coin, p.venue)
            self.closed(self.acct.close(q, time.time(), "cross"))
        if self.acct.position or self.paused:
            return
        best = pick(list(self.reads.values()), set(PERPS))
        if not best:
            return
        venue = "spot" if best.signal == "long" else "perp"
        q = await self.quote(best.coin, venue)
        try:
            pos = self.acct.open(best.coin, best.signal, q, best.score, time.time())
        except Skip as e:
            self.say(f"skipped {best.coin} {best.signal}: {e}", DIM)
            return
        what = f"{pos.contracts} contract{'s' * (pos.contracts > 1)} ({pos.qty:,.0f} {pos.coin})" \
            if pos.venue == "perp" else f"{pos.qty:,.4g} {pos.coin}"
        color = GREEN if pos.side == "long" else PINK
        self.say(f"OPEN {pos.side.upper()} {what} @ {px(pos.entry)} on {pos.venue}, "
                 f"stop {px(pos.stop)}, score {pos.score:.0f}, fee {money(pos.fee_in)}", color)

    async def quote(self, coin: str, venue: str) -> Quote:
        q = await (self.market.perp(coin) if venue == "perp" else self.market.spot(coin))
        (self.perp if venue == "perp" else self.spot)[coin] = q
        return q

    def _poll(self) -> None:
        self.app.run_worker(self.poll(), group="cipher-poll", exclusive=True)

    async def poll(self) -> None:
        try:
            for c in COINS:
                self.spot[c] = await self.market.spot(c)
            for c in PERPS:
                self.perp[c] = await self.market.perp(c)
        except Exception as e:
            self.feed = "error"
            self.say(f"price poll failed: {e}", PINK)
            return
        p = self.acct.position
        if p:
            q = self.pos_quote()
            if q and (why := self.acct.stop_hit(q)):
                self.closed(self.acct.close(q, time.time(), why))

    def pos_quote(self) -> Quote | None:
        p = self.acct.position
        if not p:
            return None
        return (self.perp if p.venue == "perp" else self.spot).get(p.coin)

    def closed(self, t) -> None:
        color = GREEN if t.pnl > 0 else PINK
        self.say(f"CLOSE {t.side} {t.coin} @ {px(t.exit)} ({t.reason}) {money(t.pnl, True)} "
                 f"after fees {money(t.fees)}, held {dur(t.closed - t.opened)}", color)

    # ----------------------------------------------------------- actions --

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.say("paused: no new entries (stops and exits still run)" if self.paused
                 else "resumed: taking new entries", PURPLE)

    def close_now(self) -> None:
        self.app.run_worker(self._close_now(), group="cipher-manual", exclusive=True)

    async def _close_now(self) -> None:
        p = self.acct.position
        if not p:
            self.say("no open position", DIM)
            return
        q = await self.quote(p.coin, p.venue)
        self.closed(self.acct.close(q, time.time(), "manual"))

    def scan_now(self) -> None:
        if not self.busy:
            self.say("scanning now (trades only act on a fresh candle)", DIM)
            self.run_scan()

    def reset(self) -> None:
        now = time.time()
        if now - self.reset_armed > 4:
            self.reset_armed = now
            self.say("press R again within 4 seconds to wipe the paper account", PINK)
            return
        self.reset_armed = 0
        self.acct = Paper(self.cfg, self.state_path)
        self.acct.save()
        self.acted_t = 0
        self.say(f"paper account reset to {money(self.cfg.balance)}", PURPLE)

    # ------------------------------------------------------------ output --

    def say(self, msg: str, color: str = "") -> None:
        ts = time.time()
        line = Text(datetime.fromtimestamp(ts).strftime("%H:%M:%S "), style=DIM)
        line.append(msg, style=color or None)
        self.lines.append(line)
        if self.sink is not None:
            try:
                self.sink(line)
            except Exception:
                pass
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a") as f:
                f.write(f"{datetime.fromtimestamp(ts):%Y-%m-%d %H:%M:%S} {msg}\n")
        except OSError:
            pass

    def status(self) -> Text:
        """One line for coindeck's command bar while the chart page is up."""
        t = Text()
        if not self.started:
            return t
        p = self.acct.position
        t.append("cipher ", style=PURPLE)
        if p:
            t.append(f"{p.side} {p.coin}", style=GREEN if p.side == "long" else PINK)
            if q := self.pos_quote():
                u = self.acct.unrealized(q)
                t.append(f" {money(u, True)}", style=GREEN if u > 0 else PINK)
        else:
            t.append("flat", style=DIM)
        if self.paused:
            t.append(" paused", style=PINK)
        return t
