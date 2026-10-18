"""The Cipher page: scanner, position, log and closed trades. b or esc goes back
to the charts; the bot keeps trading underneath."""

from __future__ import annotations

import math
import time
from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import RichLog, Static

from .bot import CYAN, DIM, GREEN, PINK, PURPLE, Bot, dur, hm, money, px
from .paper import COINS, PERPS


def num(x: float, w: int = 6) -> str:
    return f"{'-':>{w}}" if math.isnan(x) else f"{x:>+{w}.1f}"


class Panel(Static, can_focus=True):
    pass


class CipherScreen(Screen):
    BINDINGS = [
        Binding("escape,b", "back", show=False),
        Binding("space", "pause", show=False),
        Binding("x", "close_now", show=False),
        Binding("R", "reset", show=False),
        Binding("s", "scan_now", show=False),
        Binding("1", "focus_panel('c-scanner')", show=False),
        Binding("2", "focus_panel('c-position')", show=False),
        Binding("3", "focus_panel('c-log')", show=False),
        Binding("4", "focus_panel('c-trades')", show=False),
    ]

    def __init__(self, bot: Bot) -> None:
        super().__init__()
        self.bot = bot

    def compose(self) -> ComposeResult:
        with Vertical(id="c-main"):
            with Horizontal(id="c-top"):
                yield Panel(id="c-scanner", classes="panel c-panel")
                yield Panel(id="c-position", classes="panel c-panel")
            with Horizontal(id="c-bottom"):
                yield RichLog(id="c-log", classes="panel c-panel", wrap=True, markup=False, max_lines=2000)
                yield Panel(id="c-trades", classes="panel c-panel")
        yield Static(id="c-bar")

    def on_mount(self) -> None:
        self.query_one("#c-scanner").border_title = "[1] Scanner"
        self.query_one("#c-position").border_title = "[2] Position"
        self.query_one("#c-log").border_title = "[3] Log"
        self.query_one("#c-trades").border_title = "[4] Trades"
        log = self.query_one("#c-log", RichLog)
        for line in self.bot.lines:
            log.write(line)
        self.bot.sink = log.write
        log.focus()
        self.redraw()
        self.set_interval(1.0, self.redraw)

    def on_screen_resume(self) -> None:
        self.redraw()

    # ----------------------------------------------------------- actions --

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_pause(self) -> None:
        self.bot.toggle_pause()

    def action_close_now(self) -> None:
        self.bot.close_now()

    def action_scan_now(self) -> None:
        self.bot.scan_now()

    def action_reset(self) -> None:
        self.bot.reset()

    def action_focus_panel(self, wid: str) -> None:
        self.query_one(f"#{wid}").focus()

    # ------------------------------------------------------------ output --

    def redraw(self) -> None:
        if not self.is_current:
            return
        self.draw_scanner()
        self.draw_position()
        self.draw_trades()
        self.draw_bar()

    def draw_scanner(self) -> None:
        b = self.bot
        t = Text()
        t.append(f"{'coin':9}{'price':>11}{'wt1':>8}{'wt2':>8}{'flow':>8}  {'cross':7}{'signal'}\n", style=DIM)
        for c in COINS:
            r = b.reads.get(c)
            q = b.spot.get(c)
            held = b.acct.position and b.acct.position.coin == c
            name = c + (" ⇅" if c in PERPS else "")
            t.append(f"{name:9}", style=f"bold {CYAN}" if held else "bold")
            t.append(f"{px(q.mid) if q else (px(r.close) if r else '-'):>11}")
            if not r:
                t.append("   waiting for candles\n", style=DIM)
                continue
            t.append(num(r.wt1, 8), style=GREEN if r.wt1 >= r.wt2 else PINK)
            t.append(num(r.wt2, 8), style=DIM)
            t.append(num(r.mf, 8), style=GREEN if r.mf > 0 else PINK)
            t.append(f"  {r.last_cross or '-':7}", style=DIM)
            if r.signal == "long":
                t.append(f"LONG {r.score:.0f}", style=f"bold {GREEN}")
            elif r.signal == "short":
                ok = c in PERPS
                t.append(f"SHORT {r.score:.0f}" + ("" if ok else " (no perp)"),
                         style=f"bold {PINK}" if ok else DIM)
            elif r.dot:
                t.append(f"{r.dot} dot", style=GREEN if r.dot == "green" else PINK)
            t.append("\n")
        t.append("\nflow = money flow (green above 0)   cross = last wave cross, candles ago   ⇅ = can short",
                 style=DIM)
        w = self.query_one("#c-scanner", Panel)
        w.update(t)
        if b.reads:
            last = max(r.t for r in b.reads.values()) + b.tf
            w.border_subtitle = f"{b.tf_name} · closed {hm(last)}"

    def draw_position(self) -> None:
        b = self.bot
        a, p = b.acct, b.acct.position
        t = Text()
        q = b.pos_quote()
        if p:
            col = GREEN if p.side == "long" else PINK
            t.append(f"{p.side.upper()} {p.coin}", style=f"bold {col}")
            t.append(f"  {p.venue}" + (f" ×{p.contracts}" if p.venue == "perp" else "") + "\n", style=DIM)
            t.append(f"size    {p.qty:,.4g} {p.coin}\n")
            t.append(f"entry   {px(p.entry)}   {hm(p.opened)}\n")
            if q:
                now = q.bid if p.side == "long" else q.ask
                u = a.unrealized(q)
                t.append(f"now     {px(now)}   ")
                t.append(f"{(now / p.entry - 1) * 100:+.2f}%\n", style=GREEN if (now > p.entry) == (p.side == "long") else PINK)
                t.append("P&L     ")
                t.append(f"{money(u, True)}", style=f"bold {GREEN if u > 0 else PINK}")
                t.append("  if closed now\n", style=DIM)
            t.append(f"stop    {px(p.stop)}\n")
            if p.venue == "perp":
                t.append(f"margin  {money(p.margin)}  notional {money(p.qty * p.entry)}\n", style=DIM)
            t.append(f"held    {dur(time.time() - p.opened)}\n")
        else:
            t.append("flat", style="bold")
            t.append("  waiting for a signal\n\n", style=DIM)
        eq = a.equity(q)
        t.append("\n")
        t.append(f"equity  {money(eq)}  ", style="bold")
        ret = (eq / a.start - 1) * 100
        t.append(f"{ret:+.2f}%\n", style=GREEN if ret >= 0 else PINK)
        t.append(f"cash    {money(a.cash)}\n")
        wins = sum(1 for x in a.trades if x.pnl > 0)
        t.append(f"trades  {len(a.trades)}  ({wins} won)\n")
        t.append(f"fees    {money(a.fees)}\n", style=DIM)
        t.append(f"since   {datetime.fromtimestamp(a.started):%b %d %H:%M}\n", style=DIM)
        w = self.query_one("#c-position", Panel)
        w.update(t)
        w.border_subtitle = "PAUSED" if b.paused else ("paper" if not b.demo else "paper · demo")

    def draw_trades(self) -> None:
        trades = self.bot.acct.trades
        t = Text()
        for x in reversed(trades[-200:]):
            col = GREEN if x.pnl > 0 else PINK
            t.append(f"{hm(x.closed)} ", style=DIM)
            t.append(f"{x.coin:8}{x.side:6}")
            t.append(f"{money(x.pnl, True):>9}", style=col)
            t.append(f"  {x.reason}\n", style=DIM)
        if not trades:
            t.append("no closed trades yet", style=DIM)
        w = self.query_one("#c-trades", Panel)
        w.update(t)
        total = sum(x.pnl for x in trades)
        w.border_subtitle = f"{len(trades)} · {money(total, True)}"

    def draw_bar(self) -> None:
        b = self.bot
        t = Text()
        t.append(" PAPER ", style=f"bold black on {PURPLE}")
        t.append(f" {b.tf_name} ", style=PURPLE)
        left = max(0, b.next_scan - time.time())
        when = "--:--" if math.isinf(left) else f"{int(left // 60):02d}:{int(left % 60):02d}"
        t.append(f" next scan {when} ", style=DIM)
        if b.paused:
            t.append(" PAUSED ", style=f"bold black on {PINK}")
        t.append("  charts: b | pause: space | close: x | scan: s | reset: R R | panels: 1-4 | quit: q",
                 style=DIM)
        dot = GREEN if b.feed == "live" else PINK
        t.append("   ● ", style=dot)
        t.append(b.feed if not b.demo else "demo", style=DIM)
        self.query_one("#c-bar", Static).update(t)
