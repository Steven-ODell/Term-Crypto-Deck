"""Line-API widgets drawn the way lazygit, gitdeck and launchdeck draw lists."""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.style import Style
from rich.text import Text
from textual import events
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static

# gitdeck's palette, 256-colour codes converted to hex
C_ACCENT = "#87afff"   # 111 headings, paths
C_FOCUS = "#5fd75f"    # 77  lit border
C_BORDER = "#585858"   # 240 other borders
C_BAR_BG = "#afafd7"   # 146 selection bar
C_BAR_FG = "#262626"   # 235 text on the bar
C_KEY = "#5fd7d7"      # 80  key names
C_AMBER = "#d7af5f"    # 179
C_RED = "#d75f5f"      # 167
C_GREEN = "#5faf5f"    # 71
C_TEAL = "#87afaf"     # 109
C_VIOLET = "#af87d7"   # 140
C_ORANGE = "#d7875f"   # 173
C_GREY = "#8a8a8a"     # 245
C_DIMBAR = "#3a3a3a"   # 237 selection when the panel is not focused

DIM = Style(dim=True)


@dataclass
class Row:
    left: Text
    right: Text = field(default_factory=Text)
    key: str | None = None          # None makes a heading that the cursor skips

    @property
    def selectable(self) -> bool:
        return self.key is not None


def _strip(text: Text, console, width: int, base: Style, start: int = 0) -> Strip:
    """Render a Text to a Strip. Rich drops a Text's own base style when the
    Text has no spans, so fold it into a span first."""
    if text.style:
        text = text.copy()
        text.stylize_before(text.style)
        text.style = ""
    segs = list(text.render(console))
    return Strip(segs, text.cell_len).crop_extend(start, start + width, base)


def _fit(left: Text, right: Text, width: int) -> Text:
    """left, padded or cut, then right flush against the edge."""
    rw = right.cell_len
    room = width - rw - (1 if rw else 0)
    if room < 4:
        right, rw, room = Text(), 0, width
    line = left.copy()
    if line.cell_len > room:
        line.truncate(max(room - 1, 0))
        line.append("…", style=DIM)
    line.pad_right(room - line.cell_len)
    if rw:
        line.append(" ")
        line.append_text(right)
    return line


class PanelList(ScrollView, can_focus=True):
    """A cursor list with a solid selection bar and non-selectable headings."""

    class Highlighted(Message):
        def __init__(self, panel: "PanelList", key: str | None) -> None:
            super().__init__()
            self.panel = panel
            self.key = key

    class Activated(Message):
        def __init__(self, panel: "PanelList", key: str | None) -> None:
            super().__init__()
            self.panel = panel
            self.key = key

    def __init__(self, empty: str = "nothing here", **kw) -> None:
        super().__init__(**kw)
        self.rows: list[Row] = []
        self.cursor = -1
        self.empty = empty

    # ---------------------------------------------------------------- data --

    @property
    def selected_key(self) -> str | None:
        if 0 <= self.cursor < len(self.rows):
            return self.rows[self.cursor].key
        return None

    @property
    def selectable_count(self) -> int:
        return sum(1 for r in self.rows if r.selectable)

    @property
    def selectable_index(self) -> int:
        return sum(1 for r in self.rows[: self.cursor + 1] if r.selectable)

    def set_rows(self, rows: list[Row], keep: str | None = None) -> None:
        old_key = keep if keep is not None else self.selected_key
        old_cursor = self.cursor
        self.rows = rows
        self.cursor = -1
        if old_key is not None:
            for i, r in enumerate(rows):
                if r.key == old_key:
                    self.cursor = i
                    break
        if self.cursor < 0:
            sel = [i for i, r in enumerate(rows) if r.selectable]
            if sel:
                self.cursor = min(sel, key=lambda i: abs(i - max(old_cursor, 0)))
        self.virtual_size = Size(self.size.width, len(rows))
        self._keep_visible()
        self.refresh()
        if self.selected_key != old_key:
            self.post_message(self.Highlighted(self, self.selected_key))

    # ------------------------------------------------------------ movement --

    def select_key(self, key: str) -> bool:
        for i, r in enumerate(self.rows):
            if r.key == key:
                self._go(i)
                return True
        return False

    def move(self, delta: int) -> None:
        if not self.rows:
            return
        sel = [i for i, r in enumerate(self.rows) if r.selectable]
        if not sel:
            return
        if self.cursor not in sel:
            target = sel[0]
        else:
            pos = sel.index(self.cursor) + delta
            target = sel[max(0, min(len(sel) - 1, pos))]
        self._go(target)

    def top(self) -> None:
        self.move(-len(self.rows))
        self.scroll_to(y=0, animate=False)

    def bottom(self) -> None:
        self.move(len(self.rows))

    def page(self, direction: int) -> None:
        self.move(direction * max(1, self.size.height // 2))

    def _go(self, index: int) -> None:
        if index == self.cursor:
            self._keep_visible()
            return
        self.cursor = index
        self._keep_visible()
        self.refresh()
        self.post_message(self.Highlighted(self, self.selected_key))

    def _keep_visible(self) -> None:
        h = self.size.height
        if h <= 0 or self.cursor < 0:
            return
        y = int(self.scroll_y)
        # keep a heading directly above the cursor in view when scrolling up
        top_want = self.cursor
        if top_want > 0 and not self.rows[top_want - 1].selectable:
            top_want -= 1
        if top_want < y:
            self.scroll_to(y=top_want, animate=False, immediate=True)
        elif self.cursor >= y + h:
            self.scroll_to(y=self.cursor - h + 1, animate=False, immediate=True)

    def on_resize(self, event: events.Resize) -> None:
        self.virtual_size = Size(self.size.width, len(self.rows))
        self._keep_visible()

    def on_click(self, event: events.Click) -> None:
        off = event.get_content_offset(self)
        if off is None:
            return
        idx = off.y + int(self.scroll_y)
        if 0 <= idx < len(self.rows) and self.rows[idx].selectable:
            self._go(idx)
            if event.chain >= 2:
                self.post_message(self.Activated(self, self.selected_key))

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self.move(1)
        event.stop()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self.move(-1)
        event.stop()

    # ---------------------------------------------------------------- draw --

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        idx = int(self.scroll_y) + y
        base = self.rich_style
        if not self.rows:
            if y == 0:
                return _strip(Text(" " + self.empty, style=DIM), self.app.console, width, base)
            return Strip.blank(width, base)
        if idx >= len(self.rows):
            return Strip.blank(width, base)
        row = self.rows[idx]
        line = _fit(row.left, row.right, width)
        if idx == self.cursor:
            if self.has_focus:
                # A solid bar drops per-span colours: colour on colour is a mess.
                line = Text(line.plain)
                line.stylize(Style(color=C_BAR_FG, bgcolor=C_BAR_BG))
            else:
                line.stylize(Style(bgcolor=C_DIMBAR))
        return _strip(line, self.app.console, width, base)

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()


class LinesView(Widget, can_focus=True):
    """Pre-built lines, scrolled by `top`. Used for Market and Trades."""

    def __init__(self, empty: str = "", **kw) -> None:
        super().__init__(**kw)
        self.lines: list[Text] = []
        self.top = 0
        self.empty = empty

    def set_lines(self, lines: list[Text]) -> None:
        self.lines = lines
        self.top = max(0, min(self.top, len(lines) - 1))
        self.refresh()

    def scroll_lines(self, n: int) -> None:
        self.top = max(0, min(self.top + n, max(0, len(self.lines) - self.size.height)))
        self.refresh()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self.scroll_lines(3)
        event.stop()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self.scroll_lines(-3)
        event.stop()

    def render_line(self, y: int) -> Strip:
        width, base = self.size.width, self.rich_style
        if not self.lines:
            if y == 0 and self.empty:
                return _strip(Text(" " + self.empty, style=DIM), self.app.console, width, base)
            return Strip.blank(width, base)
        idx = self.top + y
        if idx >= len(self.lines):
            return Strip.blank(width, base)
        return _strip(self.lines[idx], self.app.console, width, base)

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()


class CommandBar(Static):
    """`label: key | label: key` on the left, the app name on the right."""

    def show(self, binds: list[tuple[str, str]], right: Text | str = "coindeck") -> None:
        self._binds = binds
        self._right = right
        self._message = None
        self._draw()

    def flash(self, message: str, error: bool = False) -> None:
        self._message = (message, error)
        self._draw()

    def clear_flash(self) -> None:
        self._message = None
        self._draw()

    def on_resize(self) -> None:
        self._draw()

    def _draw(self) -> None:
        width = max(self.size.width, 20)
        right = getattr(self, "_right", "coindeck")
        right_t = right if isinstance(right, Text) else Text(right, style=DIM)
        msg = getattr(self, "_message", None)
        if msg:
            text, err = msg
            left = Text(" " + text, style=Style(color=C_RED) if err else DIM)
        else:
            left = Text(" ")
            binds = getattr(self, "_binds", [])
            shown = 0
            for label, key in binds:
                piece = Text()
                if shown:
                    piece.append(" | ", style=DIM)
                piece.append(f"{label}: ", style=DIM)
                piece.append(key, style=Style(color=C_KEY))
                if left.cell_len + piece.cell_len + right_t.cell_len + 2 > width and shown:
                    break
                left.append_text(piece)
                shown += 1
        self.update(_fit(left, right_t, width - 1))
