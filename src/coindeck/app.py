"""The interface: watchlist, market stats and a trade tape on the left, the
chart on the right, a command bar underneath. lazygit style."""

from __future__ import annotations

import asyncio
import math
import subprocess
import time
from collections import deque

from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen

from . import config as cfgmod
from .chart import Chart
from .feed import Client, DemoClient, DemoFeed, Feed
from .market import (
    TF_BY_NAME, TIMEFRAMES, Product, Series, Ticker, Timeframe, Trade,
    fmt_compact, fmt_pct, fmt_price, fmt_size, price_decimals, sparkline,
)
from .screens import AddScreen, MenuScreen, help_rows
from .widgets import (
    C_ACCENT, C_AMBER, C_FOCUS, C_GREEN, C_GREY, C_RED, DIM, CommandBar, LinesView, PanelList, Row,
)

SPIN = "|/-\\"
PANELS = ("watchlist", "market", "trades", "chart")
FLASH_SECONDS = 0.8
SPARK_TF = TF_BY_NAME["1h"]


def _title(num: int, name: str, extra: Text | str = "") -> Text:
    t = Text(f"[{num}]─{name}")
    if extra:
        t.append(" ─ ")
        t.append_text(extra if isinstance(extra, Text) else Text(extra))
    return t


def _ago(ts: float) -> str:
    if not ts:
        return "never"
    d = time.time() - ts
    if d < 5:
        return "just now"
    if d < 60:
        return f"{int(d)}s ago"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    return f"{int(d // 3600)} h ago"


class CoinDeck(App):
    CSS_PATH = "coindeck.tcss"
    TITLE = "coindeck"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("q", "quit_app", show=False),
        Binding("ctrl+c,ctrl+q", "quit_app", show=False, priority=True),
        Binding("1", "focus_panel('watchlist')", show=False),
        Binding("2", "focus_panel('market')", show=False),
        Binding("3", "focus_panel('trades')", show=False),
        Binding("0", "focus_panel('chart')", show=False),
        Binding("tab", "cycle(1)", show=False),
        Binding("shift+tab", "cycle(-1)", show=False),
        Binding("j,down", "move(1)", show=False),
        Binding("k,up", "move(-1)", show=False),
        Binding("g,home", "top", show=False),
        Binding("G,end", "bottom", show=False),
        Binding("J", "reorder(1)", show=False),
        Binding("K", "reorder(-1)", show=False),
        Binding("h,left", "cursor(-1)", show=False),
        Binding("l,right", "cursor(1)", show=False),
        Binding("H,ctrl+u,pageup", "pan(1)", show=False),
        Binding("L,ctrl+d,pagedown", "pan(-1)", show=False),
        Binding("left_square_bracket", "timeframe(-1)", show=False),
        Binding("right_square_bracket,t", "timeframe(1)", show=False),
        Binding("minus", "zoom(-1)", show=False),
        Binding("plus,equals_sign", "zoom(1)", show=False),
        Binding("c", "mode", show=False),
        Binding("v", "volume", show=False),
        Binding("f", "fullscreen", show=False),
        Binding("a", "add", show=False),
        Binding("d,x", "remove", show=False),
        Binding("enter", "enter", show=False),
        Binding("escape", "escape", show=False),
        Binding("y", "copy", show=False),
        Binding("o", "open", show=False),
        Binding("r", "reload", show=False),
        Binding("question_mark", "help", show=False),
    ]

    def __init__(self, demo: bool = False) -> None:
        super().__init__(ansi_color=True)
        self.demo = demo
        self.state = cfgmod.State.load(demo)
        self.client = DemoClient() if demo else Client()
        feed_cls = DemoFeed if demo else Feed
        self.feed = feed_cls(self._on_ticker, self._on_trade, self._on_feed_status)
        self.products: dict[str, Product] = {}
        self.tickers: dict[str, Ticker] = {}
        self.series: dict[tuple[str, str], Series] = {}
        self.trades: deque[Trade] = deque(maxlen=400)
        self.tf: Timeframe = TF_BY_NAME[self.state.timeframe]
        self.selected: str | None = None
        self.feed_status = "connecting"
        self.feed_detail = ""
        self.stats_at = 0.0
        self.stats_error = ""
        self._dirty = {"watchlist": True, "market": True, "trades": True, "chart": True}
        self._ticks = 0
        self._flash_until = 0.0
        self._last_focus = "watchlist"
        self._fullscreen = False

    # -------------------------------------------------------------- layout --

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield PanelList(id="watchlist", classes="panel", empty="empty: add a pair with a")
                yield LinesView(id="market", classes="panel", empty="no pair selected")
                yield LinesView(id="trades", classes="panel", empty="waiting for trades…")
            yield Chart(id="chart", classes="panel")
        yield CommandBar(id="bar")

    def on_mount(self) -> None:
        self.p_watch = self.query_one("#watchlist", PanelList)
        self.p_market = self.query_one("#market", LinesView)
        self.p_trades = self.query_one("#trades", LinesView)
        self.p_chart = self.query_one("#chart", Chart)
        self.bar = self.query_one("#bar", CommandBar)

        self.p_chart.zoom = max(0, min(2, self.state.zoom))
        self.p_chart.mode = self.state.mode
        self.p_chart.volume = self.state.volume

        cached = None if self.demo else cfgmod.load_products()
        if cached:
            self.products = {p.id: p for p in cached}

        self.refresh_watchlist()
        if self.state.selected in self.state.watchlist:
            self.p_watch.select_key(self.state.selected)
        self._select(self.p_watch.selected_key)
        self.p_watch.focus()
        self.update_bar()
        self._layout_for(self.size.width)

        self.run_worker(self.feed.run(), group="feed", exclusive=True)
        self._bootstrap(need_products=not cached)
        self.set_interval(0.2, self.tick)
        self.set_interval(60, lambda: self.run_worker(self._refresh_stats(), group="stats",
                                                      exclusive=True))
        self.set_interval(20, self._refresh_active)
        self.set_interval(600, lambda: self.run_worker(self._refresh_sparks(), group="sparks",
                                                       exclusive=True))

    def on_resize(self, event) -> None:
        self._layout_for(event.size.width)

    def _layout_for(self, width: int) -> None:
        self.screen.set_class(width < 110, "narrow")
        self.screen.set_class(width < 72, "tiny")
        self.mark("watchlist", "chart")

    # ---------------------------------------------------------------- data --

    @work(group="bootstrap")
    async def _bootstrap(self, need_products: bool) -> None:
        if need_products:
            try:
                prods = await self.client.products()
                self.products = {p.id: p for p in prods}
                if not self.demo:
                    cfgmod.save_products(prods)
            except Exception as exc:
                self.flash(f"could not load the market list: {self._err(exc)}", error=True)
        await self._refresh_stats()
        self.mark("chart", "market", "watchlist")
        await self._refresh_sparks()

    async def _refresh_stats(self) -> None:
        try:
            stats = await self.client.stats()
        except Exception as exc:
            self.stats_error = self._err(exc)
            return
        self.stats_error = ""
        self.stats_at = time.time()
        for pid, fresh in stats.items():
            t = self.tickers.get(pid)
            if t is None:
                self.tickers[pid] = fresh
                continue
            # a websocket price is newer than the REST snapshot
            if not t.price or time.time() - t.updated > 90:
                t.price = fresh.price
            t.open_24h, t.high_24h, t.low_24h = fresh.open_24h, fresh.high_24h, fresh.low_24h
            t.volume_24h, t.volume_30d = fresh.volume_24h, fresh.volume_30d
        if self.selected and self.p_chart.series and not self.p_chart.series.candles:
            self.p_chart.decimals = self.decimals_for(self.selected)
        self.mark("watchlist", "market")

    async def _refresh_sparks(self) -> None:
        for pid in list(self.state.watchlist):
            s = self.series.get((pid, SPARK_TF.name))
            if s and s.candles and time.time() - s.fetched < 300:
                continue
            await self._fetch_latest(pid, SPARK_TF, quiet=True)
            self.mark("watchlist")

    def _refresh_active(self) -> None:
        if not self.selected:
            return
        s = self.series.get((self.selected, self.tf.name))
        if s is None or not s.candles:
            if s is None or not s.loading:
                self.load_series(self.selected, self.tf)
            return
        if not s.loading:
            self.run_worker(self._fetch_latest(self.selected, self.tf), group="latest")

    async def _fetch_latest(self, pid: str, tf: Timeframe, quiet: bool = False) -> None:
        s = self.series.setdefault((pid, tf.name), Series(pid, tf))
        if s.loading:
            return
        s.loading = True
        try:
            page = await self.client.candles(pid, tf.base)
            s.merge(page)
            s.fetched = time.time()
            s.error = ""
        except Exception as exc:
            s.error = self._err(exc)
            if not quiet:
                self.flash(f"{pid}: {s.error}", error=True)
        finally:
            s.loading = False
        self._series_changed(s)

    @work(group="series", exclusive=True)
    async def load_series(self, pid: str, tf: Timeframe, force: bool = False) -> None:
        key = (pid, tf.name)
        s = self.series.setdefault(key, Series(pid, tf))
        if s.candles and not force and time.time() - s.fetched < 20:
            return
        if s.loading and not force:
            return
        # merged timeframes need several exchange pages for a useful screenful
        pages = 1 if tf.factor == 1 else min(4, math.ceil(180 * tf.factor / 300))
        if s.candles and not force:
            pages = 1
        s.loading = True
        s.error = ""
        self.mark("chart")
        try:
            end = None
            for i in range(pages):
                page = await self.client.candles(pid, tf.base, end)
                if not page:
                    if i > 0:
                        s.exhausted = True
                    break
                s.merge(page)
                s.fetched = time.time()
                end = page[0].t
                self._series_changed(s)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            s.error = self._err(exc)
        finally:
            s.loading = False
        self._series_changed(s)

    @work(group="history", exclusive=True)
    async def load_history(self, pid: str, tf: Timeframe) -> None:
        s = self.series.get((pid, tf.name))
        if s is None or s.loading or s.exhausted or not s.base:
            return
        s.loading = True
        self.mark("chart")
        try:
            page = await self.client.candles(pid, tf.base, s.oldest_base)
            page = [c for c in page if c.t < (s.oldest_base or 0)]
            if not page:
                s.exhausted = True
                self.flash(f"{pid} {tf.name}: that is all the history Coinbase has")
            else:
                s.merge(page)
        except Exception as exc:
            self.flash(f"history: {self._err(exc)}", error=True)
        finally:
            s.loading = False
        self._series_changed(s)

    def _series_changed(self, s: Series) -> None:
        if s.product == self.selected and s.tf == self.tf and self.p_chart.series is s:
            if s.candles and self.p_chart.decimals != self.decimals_for(s.product):
                self.p_chart.decimals = self.decimals_for(s.product)
            self.p_chart.message = self._chart_message(s)
            self.p_chart.changed()
            self.mark("chart", "market")
        if s.tf == SPARK_TF:
            self.mark("watchlist")

    def _chart_message(self, s: Series) -> str:
        if s.error:
            return f"could not load {s.product} {s.tf.name}: {s.error}   (r retries)"
        if s.loading or not s.fetched:
            return f"loading {s.product} {s.tf.name}…"
        return f"no {s.tf.name} candles for {s.product}"

    @staticmethod
    def _err(exc: Exception) -> str:
        msg = str(exc) or type(exc).__name__
        if "ConnectError" in type(exc).__name__ or "Name or service" in msg:
            return "offline (cannot reach api.exchange.coinbase.com)"
        return msg.splitlines()[0][:100]

    def decimals_for(self, pid: str) -> int:
        t = self.tickers.get(pid)
        price = t.price if t and t.price else 0.0
        if not price:
            s = self.series.get((pid, self.tf.name)) or self.series.get((pid, SPARK_TF.name))
            if s and s.candles:
                price = s.candles[-1].c
        guess = price_decimals(price) if price else 2
        prod = self.products.get(pid)
        if prod:
            return min(prod.decimals, guess + 1)
        return guess

    # ---------------------------------------------------------------- live --

    def _on_ticker(self, pid: str, d: dict) -> None:
        t = self.tickers.setdefault(pid, Ticker())
        if d.get("price"):
            t.set_price(d["price"])
        for k in ("open_24h", "high_24h", "low_24h", "volume_24h", "volume_30d", "bid", "ask"):
            if d.get(k):
                setattr(t, k, d[k])
        if t.price:
            if t.high_24h and t.price > t.high_24h:
                t.high_24h = t.price
            if t.low_24h and t.price < t.low_24h:
                t.low_24h = t.price
        ts = d.get("time") or time.time()
        for tf in {self.tf, SPARK_TF}:
            s = self.series.get((pid, tf.name))
            if s is not None and d.get("price"):
                s.apply_trade(d["price"], 0.0, ts)
        self.mark("watchlist")
        if pid == self.selected:
            self.mark("market", "chart")

    def _on_trade(self, pid: str, tr: Trade) -> None:
        if pid != self.selected or not tr.price:
            return
        self.trades.appendleft(tr)
        s = self.series.get((pid, self.tf.name))
        if s is not None:
            s.apply_trade(tr.price, tr.size, tr.t)
        self.mark("trades", "chart")

    def _on_feed_status(self, status: str, detail: str) -> None:
        self.feed_status = status
        self.feed_detail = detail
        self.update_bar()

    def _subscribe(self) -> None:
        self.feed.want(set(self.state.watchlist), self.selected)

    # ---------------------------------------------------------------- tick --

    def mark(self, *panels: str) -> None:
        for p in panels:
            self._dirty[p] = True

    def tick(self) -> None:
        self._ticks += 1
        now = time.monotonic()
        if self._flash_until and now > self._flash_until:
            self._flash_until = 0.0
            self.bar.clear_flash()
            self.update_bar()
        # price flashes fade on their own
        if any(now - t.moved_at < FLASH_SECONDS + 0.3 for pid in self.state.watchlist
               if (t := self.tickers.get(pid))):
            self._dirty["watchlist"] = True
        if self._dirty["watchlist"]:
            self.refresh_watchlist()
        if self._dirty["market"]:
            self.refresh_market()
        if self._dirty["trades"] or self._ticks % 5 == 0:
            self.refresh_trades()
        s = self.p_chart.series
        if self._dirty["chart"] or (s is not None and s.loading and self._ticks % 2 == 0):
            self._dirty["chart"] = False
            if s is not None:
                self.p_chart.message = self._chart_message(s)
            self.p_chart.changed()      # keeps a panned-back view still when a live candle opens
            self.refresh_chart_title()

    # ----------------------------------------------------------- watchlist --

    def refresh_watchlist(self) -> None:
        self._dirty["watchlist"] = False
        width = self.p_watch.size.width or 40
        spark_w = max(0, min(14, width - 30))
        if spark_w < 6:
            spark_w = 0
        now = time.monotonic()
        rows = []
        for pid in self.state.watchlist:
            prod = self.products.get(pid)
            base, _, quote = pid.partition("-")
            t = self.tickers.get(pid)
            left = Text(" ")
            left.append(base.ljust(6), style=Style(bold=True))
            if quote != "USD":
                left.append("-" + quote, style=DIM)
            right = Text()
            if t and t.price:
                dec = min(prod.decimals, price_decimals(t.price) + 1) if prod else price_decimals(t.price)
                flash = now - t.moved_at < FLASH_SECONDS
                pstyle = Style(color=C_GREEN if t.last_move > 0 else C_RED, bold=True) if flash else None
                right.append(fmt_price(t.price, dec), style=pstyle)
                pct = t.change_pct
                colour = C_GREEN if pct >= 0 else C_RED
                s = self.series.get((pid, SPARK_TF.name))
                if spark_w:
                    closes = [c.c for c in s.candles[-24:]] if s and s.candles else []
                    right.append(" ")
                    right.append(sparkline(closes, spark_w).rjust(spark_w),
                                 style=Style(color=colour, dim=True))
                right.append(" ")
                right.append(fmt_pct(pct).rjust(7) if t.open_24h else "".rjust(7),
                             style=Style(color=colour))
            else:
                right.append("…", style=DIM)
            rows.append(Row(left, right, key=pid))
        self.p_watch.set_rows(rows)
        if self.screen.has_class("narrow"):
            self.p_watch.styles.height = "1fr"
        else:
            room = self.size.height - 1 - 9 - 10
            self.p_watch.styles.height = max(5, min(len(rows) + 2, room))
        self.refresh_titles()

    def on_panel_list_highlighted(self, event: PanelList.Highlighted) -> None:
        if event.panel is self.p_watch:
            self._select(event.key)

    def on_panel_list_activated(self, event: PanelList.Activated) -> None:
        if event.panel is self.p_watch:
            self.p_chart.focus()

    def _select(self, pid: str | None) -> None:
        if pid == self.selected and self.p_chart.series is not None:
            return
        self.selected = pid
        self.trades.clear()
        self._subscribe()
        if pid is None:
            self.p_chart.show(None, message="the watchlist is empty: press a to add a pair")
        else:
            self.state.selected = pid
            s = self.series.setdefault((pid, self.tf.name), Series(pid, self.tf))
            self.p_chart.show(s, self.decimals_for(pid), self._chart_message(s))
            self.load_series(pid, self.tf)
        self.mark("market", "trades", "chart")

    # ---------------------------------------------------------- side panels --

    def refresh_market(self) -> None:
        self._dirty["market"] = False
        pid = self.selected
        width = self.p_market.size.width or 40
        if not pid:
            self.p_market.set_lines([])
            return
        t = self.tickers.get(pid)
        prod = self.products.get(pid)
        dec = self.decimals_for(pid)
        base, _, quote = pid.partition("-")
        lines: list[Text] = []

        def kv(k: str, v: Text | str) -> None:
            line = Text(" ")
            line.append(f"{k:<9}", style=DIM)
            line.append_text(v if isinstance(v, Text) else Text(v))
            lines.append(line)

        if not t or not t.price:
            kv("last", Text("waiting…", style=DIM))
        else:
            up = t.change >= 0
            colour = Style(color=C_GREEN if up else C_RED)
            v = Text(fmt_price(t.price, dec), style=Style(bold=True))
            lines_change = Text(("▲ " if up else "▼ ") + fmt_price(abs(t.change), dec) + "  ", style=colour)
            lines_change.append(fmt_pct(t.change_pct), style=colour)
            kv("last", v)
            kv("24h", lines_change if t.open_24h else Text("…", style=DIM))
            kv("high", fmt_price(t.high_24h, dec) if t.high_24h else "…")
            kv("low", fmt_price(t.low_24h, dec) if t.low_24h else "…")
            if t.high_24h > t.low_24h > 0:
                bar_w = max(6, width - 17)
                pos = (t.price - t.low_24h) / (t.high_24h - t.low_24h)
                pos = max(0.0, min(1.0, pos))
                at = min(bar_w - 1, int(pos * bar_w))
                bar = Text()
                bar.append("━" * at, style=Style(color=C_RED, dim=True))
                bar.append("●", style=Style(color=C_ACCENT, bold=True))
                bar.append("━" * (bar_w - at - 1), style=Style(color=C_GREEN, dim=True))
                bar.append(f" {pos * 100:3.0f}%", style=DIM)
                kv("range", bar)
            vol = Text(f"{fmt_compact(t.volume_24h)} {base}")
            if t.price and quote in ("USD", "USDC", "USDT"):
                vol.append(f"  ${fmt_compact(t.volume_24h * t.price)}", style=DIM)
            kv("volume", vol)
            if t.bid and t.ask:
                spread = t.ask - t.bid
                sp = Text(f"{fmt_price(t.bid, dec)} / {fmt_price(t.ask, dec)}")
                pct = spread / t.price * 100
                sp.append(f"  {pct:.3f}%" if pct >= 0.001 else f"  {fmt_price(spread, dec)}", style=DIM)
                kv("bid ask", sp)
            else:
                kv("30d vol", f"{fmt_compact(t.volume_30d)} {base}")
        if prod is None and self.products:
            lines.append(Text(" not listed on Coinbase any more?", style=Style(color=C_AMBER)))
        self.p_market.set_lines(lines)
        self.refresh_titles()

    def refresh_trades(self) -> None:
        self._dirty["trades"] = False
        if not self.selected:
            self.p_trades.set_lines([])
            return
        dec = self.decimals_for(self.selected)
        big = 25_000
        lines = []
        usd_quote = self.selected.split("-")[1] in ("USD", "USDC", "USDT")
        for tr in list(self.trades)[:200]:
            colour = C_GREEN if tr.buy else C_RED
            line = Text(" ")
            line.append(time.strftime("%H:%M:%S", time.localtime(tr.t)), style=DIM)
            line.append("  ")
            line.append(fmt_price(tr.price, dec).rjust(11), style=Style(color=colour))
            notional = tr.price * tr.size
            is_big = usd_quote and notional >= big
            line.append(" ")
            line.append(fmt_size(tr.size).rjust(9), style=Style(bold=True) if is_big else DIM)
            if is_big:
                line.append(f" ${fmt_compact(notional)}", style=Style(color=C_AMBER))
            lines.append(line)
        self.p_trades.empty = "waiting for trades…" if self.feed_status == "live" else \
            f"trades need the live feed ({self.feed_status})"
        self.p_trades.set_lines(lines)
        self.refresh_titles()

    # -------------------------------------------------------------- titles --

    def refresh_titles(self) -> None:
        n = len(self.state.watchlist)
        self.p_watch.border_title = _title(1, "Watchlist")
        self.p_watch.border_subtitle = Text(
            f"{self.p_watch.selectable_index} of {n}" if n else "")
        self.p_market.border_title = _title(2, "Market", self.selected or "")
        self.p_market.border_subtitle = Text(
            f"24h stats {_ago(self.stats_at)}" if self.stats_at and not self.stats_error
            else ("stats: " + self.stats_error if self.stats_error else ""))
        recent = sum(1 for tr in self.trades if time.time() - tr.t < 60)
        self.p_trades.border_title = _title(3, "Trades")
        self.p_trades.border_subtitle = Text(f"{recent}/min" if self.trades else "")

    def refresh_chart_title(self) -> None:
        s = self.p_chart.series
        extra = Text()
        if self.selected:
            extra.append(self.selected)
            extra.append(f" {self.p_chart.mode}")
            if s is not None and s.loading:
                extra.append(" loading " + SPIN[self._ticks % 4], style=Style(color=C_AMBER))
        self.p_chart.border_title = _title(0, "Chart", extra)
        strip = Text()
        for tf in TIMEFRAMES:
            if tf is self.tf:
                strip.append(f"[{tf.name}]", style=Style(color=C_FOCUS, bold=True))
            else:
                strip.append(f" {tf.name} ", style=DIM)
        if s is not None and s.candles:
            strip.append(f"  {len(s.candles)} candles", style=DIM)
        self.p_chart.border_subtitle = strip

    # ----------------------------------------------------------------- bar --

    def update_bar(self) -> None:
        if not hasattr(self, "bar"):
            return
        fid = self._focused_id()
        if fid == "chart":
            binds = [("cursor", "h l"), ("pan", "H L"), ("zoom", "- +"), ("timeframe", "[ ]"),
                     ("line", "c"), ("volume", "v"), ("live", "esc"), ("pair", "j k"),
                     ("full", "f"), ("keys", "?"), ("quit", "q")]
        elif fid == "watchlist":
            binds = [("timeframe", "[ ]"), ("add", "a"), ("remove", "d"), ("reorder", "J K"),
                     ("cursor", "h l"), ("line", "c"), ("chart", "enter"), ("keys", "?"), ("quit", "q")]
        else:
            binds = [("scroll", "j k"), ("timeframe", "[ ]"), ("cursor", "h l"), ("add", "a"),
                     ("keys", "?"), ("quit", "q")]
        right = Text()
        if self.demo:
            right.append("demo market  ", style=Style(color=C_AMBER))
        dot, colour = {"live": ("● live", C_GREEN), "connecting": ("◌ connecting", C_AMBER),
                       "offline": ("✗ offline", C_RED)}.get(self.feed_status, ("?", C_GREY))
        right.append(dot, style=Style(color=colour))
        right.append("  coindeck", style=DIM)
        if self._flash_until:
            self.bar._right = right
            return
        self.bar.show(binds, right)

    def flash(self, message: str, error: bool = False, seconds: float = 4.0) -> None:
        self.update_bar()
        self.bar.flash(message, error)
        self._flash_until = time.monotonic() + seconds

    def on_descendant_focus(self, event) -> None:
        f = self.focused
        if f is not None and f.id in PANELS:
            self._last_focus = f.id
        self.update_bar()

    # ------------------------------------------------------------- actions --

    def check_action(self, action: str, parameters) -> bool | None:
        if isinstance(self.screen, ModalScreen) and action != "quit_app":
            return False
        return True

    def _focused_id(self) -> str:
        f = self.focused
        return f.id if f is not None and f.id in PANELS else self._last_focus

    def action_focus_panel(self, name: str) -> None:
        if self._fullscreen and name != "chart":
            self.action_fullscreen()
        panel = self.query_one(f"#{name}")
        if not panel.display:
            self.flash(f"{name} is hidden at this terminal width")
            return
        panel.focus()

    def action_cycle(self, step: int) -> None:
        order = ["chart"] if self._fullscreen else [p for p in PANELS if self.query_one(f"#{p}").display]
        cur = self._focused_id()
        i = order.index(cur) if cur in order else 0
        self.query_one(f"#{order[(i + step) % len(order)]}").focus()

    def action_move(self, n: int) -> None:
        fid = self._focused_id()
        if fid in ("watchlist", "chart"):
            self.p_watch.move(n)
        elif fid == "market":
            self.p_market.scroll_lines(n)
        elif fid == "trades":
            self.p_trades.scroll_lines(n)

    def action_top(self) -> None:
        fid = self._focused_id()
        if fid == "chart":
            self.p_chart.oldest()
        elif fid == "watchlist":
            self.p_watch.top()
        elif fid == "trades":
            self.p_trades.scroll_lines(-10**6)

    def action_bottom(self) -> None:
        fid = self._focused_id()
        if fid == "chart":
            self.p_chart.live()
        elif fid == "watchlist":
            self.p_watch.bottom()
        elif fid == "trades":
            self.p_trades.scroll_lines(10**6)

    def action_reorder(self, step: int) -> None:
        pid = self.p_watch.selected_key
        wl = self.state.watchlist
        if self._focused_id() != "watchlist" or pid not in wl:
            return
        i = wl.index(pid)
        j = max(0, min(len(wl) - 1, i + step))
        if i == j:
            return
        wl[i], wl[j] = wl[j], wl[i]
        self.state.save(self.demo)
        self.refresh_watchlist()
        self.p_watch.select_key(pid)

    def action_cursor(self, n: int) -> None:
        self.p_chart.move_cursor(n)

    def action_pan(self, direction: int) -> None:
        self.p_chart.page(direction)

    def action_timeframe(self, step: int) -> None:
        i = TIMEFRAMES.index(self.tf)
        self.tf = TIMEFRAMES[(i + step) % len(TIMEFRAMES)]
        self.state.timeframe = self.tf.name
        self.state.save(self.demo)
        if self.selected:
            s = self.series.setdefault((self.selected, self.tf.name), Series(self.selected, self.tf))
            self.p_chart.show(s, self.decimals_for(self.selected), self._chart_message(s))
            self.load_series(self.selected, self.tf)
        self.mark("chart")

    def action_zoom(self, step: int) -> None:
        self.p_chart.set_zoom(step)
        self.state.zoom = self.p_chart.zoom
        self.state.save(self.demo)

    def action_mode(self) -> None:
        self.p_chart.mode = "line" if self.p_chart.mode == "candles" else "candles"
        self.state.mode = self.p_chart.mode
        self.state.save(self.demo)
        self.mark("chart")

    def action_volume(self) -> None:
        self.p_chart.volume = not self.p_chart.volume
        self.state.volume = self.p_chart.volume
        self.state.save(self.demo)
        self.mark("chart")

    def action_fullscreen(self) -> None:
        self._fullscreen = not self._fullscreen
        self.query_one("#left").display = not self._fullscreen
        if self._fullscreen:
            self.p_chart.focus()
        self.mark("chart")

    def action_enter(self) -> None:
        if self._focused_id() == "watchlist" and self.selected:
            self.p_chart.focus()

    def action_escape(self) -> None:
        if self.p_chart.cursor is not None or self.p_chart.back:
            self.p_chart.live()
        elif self._fullscreen:
            self.action_fullscreen()
        elif self._focused_id() != "watchlist":
            self.p_watch.focus()

    def action_add(self) -> None:
        products = list(self.products.values())
        if not products:
            self.flash("the market list has not loaded yet", error=True)
            return

        def done(pid: str | None) -> None:
            if not pid:
                return
            if pid not in self.state.watchlist:
                self.state.watchlist.append(pid)
                self.state.save(self.demo)
                self.flash(f"added {pid}")
                self._subscribe()
                self.run_worker(self._fetch_latest(pid, SPARK_TF, quiet=True), group="spark")
            self.refresh_watchlist()
            self.p_watch.select_key(pid)
            self.p_watch.focus()

        self.push_screen(AddScreen(products, self.tickers, set(self.state.watchlist)), done)

    def action_remove(self) -> None:
        if self._focused_id() != "watchlist":
            self.flash("remove works on the watchlist (1)")
            return
        pid = self.p_watch.selected_key
        if not pid:
            return
        self.state.watchlist.remove(pid)
        self.state.save(self.demo)
        self.refresh_watchlist()
        self._select(self.p_watch.selected_key)
        self._subscribe()
        self.flash(f"removed {pid}  (a adds it back)")

    def action_copy(self) -> None:
        c = self.p_chart.focus_candle() if self.p_chart.cursor is not None else None
        t = self.tickers.get(self.selected or "")
        price = c.c if c else (t.price if t else 0)
        if not price:
            return
        text = fmt_price(price, self.decimals_for(self.selected or "")).replace(",", "")
        try:
            subprocess.run(["wl-copy", "--", text], check=True, timeout=2, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            self.copy_to_clipboard(text)
        self.flash(f"copied {text}")

    def action_open(self) -> None:
        if not self.selected:
            return
        url = f"https://www.coinbase.com/advanced-trade/spot/{self.selected}"
        try:
            subprocess.Popen(["xdg-open", url], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            self.flash(f"opened {url}")
        except OSError as exc:
            self.flash(f"could not open a browser: {exc}", error=True)

    def action_reload(self) -> None:
        if not self.selected:
            return
        s = self.series.get((self.selected, self.tf.name))
        if s is not None:
            s.exhausted = False
            s.error = ""
        self.load_series(self.selected, self.tf, force=True)
        self.run_worker(self._refresh_stats(), group="stats")
        self.flash(f"reloading {self.selected} {self.tf.name}")

    def action_help(self) -> None:
        self.push_screen(MenuScreen("Keybindings", help_rows(), footer=[("close", "esc")]))

    def action_quit_app(self) -> None:
        if isinstance(self.screen, ModalScreen):
            self.screen.dismiss(None)
            return
        self.state.save(self.demo)
        self.exit()

    # --------------------------------------------------------- chart events --

    def on_chart_need_history(self, event: Chart.NeedHistory) -> None:
        if self.selected:
            self.load_history(self.selected, self.tf)

    def on_chart_cursor_moved(self, event: Chart.CursorMoved) -> None:
        self.refresh_chart_title()

    async def on_unmount(self) -> None:
        self.state.save(self.demo)
        try:
            await self.client.close()
        except Exception:
            pass
