"""The chart panel: candlesticks at half-cell height, or a braille line, over
a volume strip, with a price axis on the right and times along the bottom."""

from __future__ import annotations

import math
from bisect import bisect_left
from datetime import datetime

from rich.style import Style
from rich.text import Text
from textual import events
from textual.message import Message
from textual.strip import Strip
from textual.widget import Widget

from .market import Candle, Series, fmt_compact, fmt_pct, fmt_price
from .widgets import C_ACCENT, C_BAR_BG, C_BAR_FG, C_BORDER, C_GREEN, C_GREY, C_RED, DIM, _strip

# (top half, bottom half) -> glyph; 2 body, 1 wick, 0 nothing
THIN = {
    (2, 2): "┃", (1, 1): "│", (2, 1): "╿", (1, 2): "╽",
    (2, 0): "╹", (0, 2): "╻", (1, 0): "╵", (0, 1): "╷", (0, 0): " ",
}
WIDE_CENTRE = {
    (2, 2): "█", (1, 1): "│", (2, 1): "▀", (1, 2): "▄",
    (2, 0): "▀", (0, 2): "▄", (1, 0): "╵", (0, 1): "╷", (0, 0): " ",
}
WIDE_SIDE = {(2, 2): "█", (2, 1): "▀", (2, 0): "▀", (1, 2): "▄", (0, 2): "▄"}
EIGHTHS = " ▁▂▃▄▅▆▇█"
BRAILLE = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))

# slot = columns per candle, body = columns of body inside it
ZOOMS = [(1, 1), (2, 1), (4, 3)]

S_UP = Style(color=C_GREEN)
S_DOWN = Style(color=C_RED)
S_FLAT = Style(color=C_BORDER)
S_UP_DIM = Style(color=C_GREEN, dim=True)
S_DOWN_DIM = Style(color=C_RED, dim=True)
S_AXIS = Style(color=C_BORDER)
S_LABEL = Style(color=C_GREY)
S_CROSS = Style(color="#6c6c6c")
S_BAR = Style(color=C_BAR_FG, bgcolor=C_BAR_BG)


def nice_step(span: float, target: int) -> float:
    if span <= 0 or target <= 0:
        return 1.0
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if m * mag >= raw:
            return m * mag
    return 10 * mag


def step_decimals(step: float) -> int:
    d = 0
    while d < 10 and abs(step * 10 ** d - round(step * 10 ** d)) > 1e-6 * step * 10 ** d:
        d += 1
    return d


def time_label(ts: int, seconds: int, full: bool = False) -> str:
    dt = datetime.fromtimestamp(ts)
    if full:
        if seconds >= 86400:
            return dt.strftime("%a %b %d %Y")
        return dt.strftime("%a %b %d %H:%M")
    if seconds >= 86400:
        return dt.strftime("%b %d") if dt.month != 1 or dt.day > 7 else dt.strftime("%Y")
    return dt.strftime("%H:%M")


class Grid:
    def __init__(self, width: int, height: int) -> None:
        self.w, self.h = width, height
        self.ch = [[" "] * width for _ in range(height)]
        self.st: list[list[Style | None]] = [[None] * width for _ in range(height)]

    def put(self, x: int, y: int, ch: str, style: Style | None = None) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.ch[y][x] = ch
            self.st[y][x] = style

    def text(self, x: int, y: int, s: str, style: Style | None = None) -> None:
        for i, c in enumerate(s):
            self.put(x + i, y, c, style)

    def empty(self, x: int, y: int) -> bool:
        return 0 <= x < self.w and 0 <= y < self.h and self.ch[y][x] == " "

    def row(self, y: int) -> Text:
        t = Text(no_wrap=True, end="")
        chars, styles = self.ch[y], self.st[y]
        run, style = [], styles[0] if styles else None
        for c, s in zip(chars, styles):
            if s != style:
                t.append("".join(run), style=style)
                run, style = [], s
            run.append(c)
        t.append("".join(run), style=style)
        return t


class Chart(Widget, can_focus=True):
    """Draws a Series. Owns the viewport: how far back it is panned, where
    the cursor sits and how wide candles are."""

    class NeedHistory(Message):
        """The view is close to the oldest loaded candle."""

    class CursorMoved(Message):
        pass

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.series: Series | None = None
        self.decimals = 2
        self.back = 0              # candles hidden past the right edge; 0 follows live
        self.cursor: int | None = None
        self.zoom = 1
        self.mode = "candles"
        self.volume = True
        self.message = "loading…"
        self._lines: list[Text] | None = None
        self._built_for = (0, 0)
        self._prev = (None, 0)       # first candle time, count: to keep the view steady

    # ---------------------------------------------------------------- data --

    def show(self, series: Series | None, decimals: int | None = None, message: str = "") -> None:
        """Switch to another series: back to live, cursor off."""
        self.series = series
        self.back = 0
        self.cursor = None
        self.message = message
        if decimals is not None:
            self.decimals = decimals
        self._prev = self._shape()
        self.redraw()

    def changed(self) -> None:
        """The same series got new candles, at either end."""
        s = self.series
        old_first, old_len = self._prev
        if s is not None and s.candles and old_first is not None and old_len:
            ts = [c.t for c in s.candles]
            prepended = bisect_left(ts, old_first)
            appended = len(ts) - prepended - old_len
            if self.cursor is not None:
                self.cursor = min(self.cursor + prepended, len(ts) - 1)
            if self.back > 0 and appended > 0:
                self.back += appended
        self._prev = self._shape()
        self.redraw()

    def _shape(self) -> tuple[int | None, int]:
        s = self.series
        if s is None or not s.candles:
            return (None, 0)
        return (s.candles[0].t, len(s.candles))

    def redraw(self) -> None:
        self._lines = None
        self.refresh()

    @property
    def candles(self) -> list[Candle]:
        return self.series.candles if self.series else []

    # ------------------------------------------------------------ geometry --

    @property
    def slot(self) -> int:
        return ZOOMS[self.zoom][0]

    def _axis_width(self) -> int:
        cs = self.candles
        if not cs:
            return 10
        top = max(c.h for c in cs[-2000:])
        return len(fmt_price(top, self.decimals)) + 2

    def visible_count(self) -> int:
        plot = max(1, self.size.width - self._axis_width())
        return max(1, plot // self.slot)

    def window(self) -> tuple[int, int]:
        n = len(self.candles)
        count = self.visible_count()
        self.back = max(0, min(self.back, max(0, n - count)))
        end = n - self.back
        return max(0, end - count), end

    def _check_history(self) -> None:
        start, _ = self.window()
        s = self.series
        if s and not s.loading and not s.exhausted and start < self.visible_count():
            self.post_message(self.NeedHistory())

    # ------------------------------------------------------------ movement --

    def move_cursor(self, delta: int) -> None:
        n = len(self.candles)
        if not n:
            return
        start, end = self.window()
        cur = end - 1 if self.cursor is None else self.cursor
        cur = max(0, min(n - 1, cur + delta))
        if cur < start:
            self.back += start - cur
        elif cur >= end:
            self.back = max(0, self.back - (cur - end + 1))
        self.cursor = cur
        self._check_history()
        self.post_message(self.CursorMoved())
        self.redraw()

    def pan(self, candles: int) -> None:
        self.back = max(0, self.back + candles)
        start, end = self.window()
        if self.cursor is not None:
            self.cursor = max(start, min(end - 1, self.cursor))
        self._check_history()
        self.post_message(self.CursorMoved())
        self.redraw()

    def page(self, direction: int) -> None:
        self.pan(direction * max(1, self.visible_count() // 2))

    def live(self) -> None:
        self.back = 0
        self.cursor = None
        self.post_message(self.CursorMoved())
        self.redraw()

    def oldest(self) -> None:
        self.back = len(self.candles)
        self.window()
        self.cursor = 0 if self.candles else None
        self._check_history()
        self.post_message(self.CursorMoved())
        self.redraw()

    def set_zoom(self, step: int) -> None:
        keep_right = self.back
        self.zoom = max(0, min(len(ZOOMS) - 1, self.zoom + step))
        self.back = keep_right
        if self.cursor is not None:
            # keep the cursor candle on screen
            start, end = self.window()
            if not start <= self.cursor < end:
                self.back = max(0, len(self.candles) - self.cursor - self.visible_count() // 2)
        self._check_history()
        self.redraw()

    def focus_candle(self) -> Candle | None:
        cs = self.candles
        if not cs:
            return None
        if self.cursor is not None and 0 <= self.cursor < len(cs):
            return cs[self.cursor]
        _, end = self.window()
        return cs[end - 1] if end > 0 else cs[-1]

    # -------------------------------------------------------------- events --

    def on_resize(self, event: events.Resize) -> None:
        self.redraw()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self.pan(3)
        event.stop()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self.pan(-3)
        event.stop()

    def on_click(self, event: events.Click) -> None:
        off = event.get_content_offset(self)
        if off is None or not self.candles:
            return
        start, end = self.window()
        idx = start + off.x // self.slot
        if start <= idx < end:
            self.cursor = idx
            self.post_message(self.CursorMoved())
            self.redraw()

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()

    # ---------------------------------------------------------------- draw --

    def render_line(self, y: int) -> Strip:
        w, h = self.size.width, self.size.height
        if self._lines is None or self._built_for != (w, h):
            self._built_for = (w, h)
            try:
                self._lines = self._build(w, h)
            except Exception as exc:     # a drawing bug should not take the app down
                self._lines = [Text(f" chart error: {exc}", style=S_DOWN)]
        base = self.rich_style
        if y < len(self._lines):
            return _strip(self._lines[y], self.app.console, w, base)
        return Strip.blank(w, base)

    def _build(self, w: int, h: int) -> list[Text]:
        cs = self.candles
        if not cs or w < 20 or h < 6:
            lines = [Text() for _ in range(max(h, 1))]
            msg = self.message or "no data"
            lines[max(0, h // 2 - 1)] = Text(msg.center(w), style=DIM)
            return lines

        axis_w = self._axis_width()
        plot_w = max(1, w - axis_w)
        slot, body = ZOOMS[self.zoom]
        start, end = self.window()
        vis = cs[start:end]
        n = len(vis)
        vol_rows = max(2, round(h * 0.18)) if self.volume and h >= 14 else 0
        price_rows = h - 2 - vol_rows          # header and time axis
        grid = Grid(w, h)
        top = 1                                 # first price row
        # right-align the candles when there are fewer than fit
        x0 = plot_w - n * slot if n * slot < plot_w else 0

        # price range
        if self.mode == "line":
            lo, hi = min(c.c for c in vis), max(c.c for c in vis)
        else:
            lo, hi = min(c.l for c in vis), max(c.h for c in vis)
        if hi - lo <= 0:
            pad = abs(hi) * 0.01 or 1.0
        else:
            pad = (hi - lo) * 0.06
        lo, hi = lo - pad, hi + pad
        span = hi - lo

        def row_of(price: float) -> int:
            return max(0, min(price_rows - 1, int((hi - price) / span * price_rows)))

        def half_of(price: float) -> int:
            return max(0, min(price_rows * 2 - 1, int((hi - price) / span * price_rows * 2)))

        # axis column and ticks
        for r in range(price_rows + vol_rows):
            grid.put(plot_w, top + r, "│", S_AXIS)
        step = nice_step(span, max(2, price_rows // 4))
        tdec = min(step_decimals(step), max(self.decimals, step_decimals(step)))
        tick = math.ceil(lo / step) * step
        used_rows: set[int] = set()
        while tick <= hi:
            r = row_of(tick)
            if r not in used_rows and (r - 1) not in used_rows:
                used_rows.add(r)
                grid.put(plot_w, top + r, "┤", S_AXIS)
                grid.text(plot_w + 1, top + r, fmt_price(tick, tdec)[: axis_w - 1], S_LABEL)
            tick += step

        # candles or line
        if self.mode == "line":
            self._draw_line(grid, vis, x0, top, plot_w, price_rows, hi, span)
        else:
            for i, c in enumerate(vis):
                x = x0 + i * slot
                style = S_FLAT if c.v == 0 and c.h == c.l else (S_UP if c.up else S_DOWN)
                hy, ly = half_of(c.h), half_of(c.l)
                by0, by1 = half_of(max(c.o, c.c)), half_of(min(c.o, c.c))
                for r in range(hy // 2, ly // 2 + 1):
                    halves = []
                    for hf in (2 * r, 2 * r + 1):
                        halves.append(2 if by0 <= hf <= by1 else 1 if hy <= hf <= ly else 0)
                    key = (halves[0], halves[1])
                    if body == 1:
                        grid.put(x, top + r, THIN[key], style)
                    else:
                        mid = x + body // 2
                        grid.put(mid, top + r, WIDE_CENTRE[key], style)
                        side = WIDE_SIDE.get(key)
                        if side:
                            for dx in range(body):
                                if x + dx != mid:
                                    grid.put(x + dx, top + r, side, style)

        # volume
        if vol_rows:
            vtop = top + price_rows
            vmax = max((c.v for c in vis), default=0) or 1
            for i, c in enumerate(vis):
                eighths = int(c.v / vmax * vol_rows * 8 + 0.5)
                style = S_UP_DIM if c.up else S_DOWN_DIM
                for k in range(vol_rows):
                    fill = max(0, min(8, eighths - k * 8))
                    if fill:
                        for dx in range(body):
                            grid.put(x0 + i * slot + dx, vtop + vol_rows - 1 - k, EIGHTHS[fill], style)
            grid.text(plot_w + 1, vtop, ("vol " + fmt_compact(vmax))[: axis_w - 1], S_LABEL)

        # last price line
        last = cs[-1]
        if self.back == 0 or lo <= last.c <= hi:
            r = row_of(last.c)
            if lo <= last.c <= hi:
                lstyle = S_UP_DIM if last.up else S_DOWN_DIM
                for x in range(plot_w):
                    if grid.empty(x, top + r):
                        grid.put(x, top + r, "╌", lstyle)
                label = fmt_price(last.c, self.decimals).ljust(axis_w - 1)[: axis_w - 1]
                grid.put(plot_w, top + r, "├", S_AXIS)
                grid.text(plot_w + 1, top + r, label,
                          Style(color="#1c1c1c", bgcolor=C_GREEN if last.up else C_RED, bold=True))

        # time axis
        ty = h - 1
        label_len = 7 if self.series.tf.seconds < 86400 else 6
        every = max(1, math.ceil((label_len + 2) / slot))
        last_x = -99
        for i, c in enumerate(vis):
            absolute = start + i
            if absolute % every:
                continue
            x = x0 + i * slot + body // 2
            label = time_label(c.t, self.series.tf.seconds)
            if self.series.tf.seconds < 86400:
                prev = cs[absolute - every] if absolute - every >= 0 else None
                if prev is None or datetime.fromtimestamp(prev.t).date() != datetime.fromtimestamp(c.t).date():
                    label = datetime.fromtimestamp(c.t).strftime("%b %d")
            lx = x - len(label) // 2
            if lx <= last_x + 1 or lx < 0 or lx + len(label) > plot_w:
                continue
            grid.text(lx, ty, label, S_LABEL)
            last_x = lx + len(label)

        # crosshair
        focus = None
        if self.cursor is not None and start <= self.cursor < end:
            i = self.cursor - start
            x = x0 + i * slot + body // 2
            focus = cs[self.cursor]
            for r in range(price_rows + vol_rows):
                if grid.empty(x, top + r):
                    grid.put(x, top + r, "┊", S_CROSS)
            r = row_of(focus.c)
            for xx in range(plot_w):
                if grid.empty(xx, top + r) or grid.ch[top + r][xx] == "╌":
                    grid.put(xx, top + r, "┈", S_CROSS)
            grid.text(plot_w + 1, top + r, fmt_price(focus.c, self.decimals).ljust(axis_w - 1)[: axis_w - 1],
                      S_BAR)
            label = " " + time_label(focus.t, self.series.tf.seconds, full=True) + " "
            lx = max(0, min(plot_w - len(label), x - len(label) // 2))
            grid.text(lx, ty, " " * len(label), S_BAR)
            grid.text(lx, ty, label, S_BAR)

        lines = [grid.row(y) for y in range(h)]
        lines[0] = self._header(focus or cs[end - 1], cs, start if focus is None else self.cursor,
                                focus is not None, w)
        return lines

    def _header(self, c: Candle, cs: list[Candle], idx: int, cursor: bool, w: int) -> Text:
        vs = S_UP if c.up else S_DOWN
        chg = (c.c / c.o - 1) * 100 if c.o else 0.0
        if not cursor:
            right = Text("live", style=Style(color=C_GREEN)) if self.back == 0 else \
                Text(f"{self.back} back", style=DIM)
        else:
            right = Text("cursor", style=DIM)

        def build(compact: bool) -> Text:
            t = Text(no_wrap=True, end="")
            when = datetime.fromtimestamp(c.t).strftime("%H:%M" if self.series.tf.seconds < 86400
                                                          else "%b %d") if compact else \
                time_label(c.t, self.series.tf.seconds, full=True)
            t.append(" " + when, style=Style(color=C_ACCENT))
            fields = (("C", c.c),) if compact else (("O", c.o), ("H", c.h), ("L", c.l), ("C", c.c))
            for k, v in fields:
                t.append(f"  {k} ", style=DIM)
                t.append(fmt_price(v, self.decimals), style=vs)
            t.append("  " + fmt_pct(chg), style=vs)
            t.append("  V ", style=DIM)
            t.append(fmt_compact(c.v))
            return t

        t = build(False)
        if t.cell_len + right.cell_len + 2 > w:
            t = build(True)
        pad = w - t.cell_len - right.cell_len - 1
        if pad >= 1:
            t.append(" " * pad)
            t.append_text(right)
        return t

    def _draw_line(self, grid: Grid, vis: list[Candle], x0: int, top: int, plot_w: int,
                   rows: int, hi: float, span: float) -> None:
        slot = self.slot
        dots_h = rows * 4
        cells: dict[tuple[int, int], int] = {}

        def point(i: int, c: Candle) -> tuple[int, int]:
            x = x0 * 2 + int((i + 0.5) * slot * 2)
            y = int((hi - c.c) / span * (dots_h - 1) + 0.5)
            return x, max(0, min(dots_h - 1, y))

        def dot(x: int, y: int) -> None:
            cx, cy = x // 2, y // 4
            if 0 <= cx < plot_w:
                cells[(cx, cy)] = cells.get((cx, cy), 0) | BRAILLE[y % 4][x % 2]

        pts = [point(i, c) for i, c in enumerate(vis)]
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            dx, dy = abs(xb - xa), -abs(yb - ya)
            sx, sy = (1 if xb > xa else -1), (1 if yb > ya else -1)
            err = dx + dy
            x, y = xa, ya
            while True:
                dot(x, y)
                if x == xb and y == yb:
                    break
                e2 = 2 * err
                if e2 >= dy:
                    err += dy
                    x += sx
                if e2 <= dx:
                    err += dx
                    y += sy
        if len(pts) == 1:
            dot(*pts[0])
        style = S_UP if vis[-1].c >= vis[0].c else S_DOWN
        for (cx, cy), bits in cells.items():
            grid.put(cx, top + cy, chr(0x2800 + bits), style)
