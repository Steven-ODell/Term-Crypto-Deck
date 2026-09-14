"""Centred popups in the style of lazygit's menus and confirmations."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from .market import Product, Ticker, fmt_compact, fmt_pct, fmt_price
from .widgets import C_ACCENT, C_GREEN, C_KEY, C_RED, DIM, PanelList, Row


def _hint(pairs: list[tuple[str, str]]) -> Text:
    t = Text()
    for i, (label, key) in enumerate(pairs):
        if i:
            t.append(" | ", style=DIM)
        t.append(f"{label}: ", style=DIM)
        t.append(key, style=Style(color=C_KEY))
    return t


class ConfirmScreen(ModalScreen[bool]):
    """enter confirms, esc cancels."""

    BINDINGS = [
        Binding("enter,y", "yes", show=False),
        Binding("escape,n,q", "no", show=False),
    ]

    def __init__(self, title: str, body: Text, confirm_label: str = "confirm") -> None:
        super().__init__()
        self.popup_title = title
        self.body = body
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(classes="popup") as box:
            box.border_title = self.popup_title
            box.border_subtitle = _hint([(self.confirm_label, "enter"), ("cancel", "esc")])
            yield Static(self.body, classes="popup-body")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class MenuScreen(ModalScreen[str | None]):
    """A list to pick from, or with no keys, a list to read (the key help)."""

    BINDINGS = [
        Binding("escape,q", "cancel", show=False),
        Binding("enter", "pick", show=False),
        Binding("j,down", "move(1)", show=False),
        Binding("k,up", "move(-1)", show=False),
        Binding("g", "top", show=False),
        Binding("G", "bottom", show=False),
    ]

    def __init__(self, title: str, rows: list[Row], footer: list[tuple[str, str]] | None = None,
                 height: int | None = None) -> None:
        super().__init__()
        self.popup_title = title
        self.rows = rows
        self.footer = footer if footer is not None else [("select", "enter"), ("close", "esc")]
        self.list_height = height

    def compose(self) -> ComposeResult:
        with Vertical(classes="popup popup-menu") as box:
            box.border_title = self.popup_title
            box.border_subtitle = _hint(self.footer)
            lst = PanelList(classes="menu-list")
            if self.list_height:
                lst.styles.height = self.list_height
            yield lst

    def on_mount(self) -> None:
        lst = self.query_one(PanelList)
        lst.set_rows(self.rows)
        want = len(self.rows)
        lst.styles.height = min(want, max(3, self.app.size.height - 6))
        lst.focus()

    def action_move(self, n: int) -> None:
        self.query_one(PanelList).move(n)

    def action_top(self) -> None:
        self.query_one(PanelList).top()

    def action_bottom(self) -> None:
        self.query_one(PanelList).bottom()

    def action_pick(self) -> None:
        key = self.query_one(PanelList).selected_key
        self.dismiss(key)

    def on_panel_list_activated(self, event: PanelList.Activated) -> None:
        self.dismiss(event.key)

    def action_cancel(self) -> None:
        self.dismiss(None)


HELP = [
    ("", "Panels"),
    ("1 2 3 0", "focus Watchlist, Market, Trades, Chart"),
    ("tab shift+tab", "next / previous panel"),
    ("f", "chart fills the window; again to bring the panels back"),
    ("", "Watchlist"),
    ("j k  up down", "move; the chart follows the selection"),
    ("g G", "top, bottom"),
    ("J K", "move the pair down, up the list"),
    ("a", "add a pair: search every market on Coinbase"),
    ("d", "remove the selected pair"),
    ("enter", "focus the chart"),
    ("", "Chart"),
    ("[ ]  t", "previous / next timeframe: 1m 5m 15m 1h 4h 6h 1d 1w"),
    ("h l  left right", "move the cursor over candles (from any panel)"),
    ("H L  ctrl+u ctrl+d", "pan half a screen back, forward"),
    ("- +", "narrower / wider candles"),
    ("c", "candles or line"),
    ("v", "volume strip on / off"),
    ("esc", "drop the cursor and follow live again"),
    ("g G", "in the chart: oldest loaded, back to live"),
    ("", "Other"),
    ("y", "copy the price under the cursor, or the last price"),
    ("o", "open the pair on coinbase.com"),
    ("r", "reload candles and 24h stats"),
    ("?", "this list"),
    ("q  ctrl+c", "quit"),
]


def help_rows() -> list[Row]:
    rows = []
    for i, (key, desc) in enumerate(HELP):
        if not key:
            rows.append(Row(Text(desc, style=Style(color=C_ACCENT, bold=True))))
            continue
        left = Text()
        left.append(f"  {key:<20}", style=Style(color=C_KEY))
        left.append(desc)
        rows.append(Row(left, key=str(i)))
    return rows


class AddScreen(ModalScreen[str | None]):
    """Search every product. Most traded first; typing narrows it down."""

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("down,ctrl+n,ctrl+j", "move(1)", show=False),
        Binding("up,ctrl+p,ctrl+k", "move(-1)", show=False),
        Binding("pagedown", "move(10)", show=False),
        Binding("pageup", "move(-10)", show=False),
    ]

    def __init__(self, products: list[Product], tickers: dict[str, Ticker], have: set[str]) -> None:
        super().__init__()
        self.tickers = tickers
        self.have = have

        def usd_volume(p: Product) -> float:
            t = tickers.get(p.id)
            if not t:
                return 0.0
            v = t.volume_24h * t.price
            if p.quote == "BTC":
                btc = tickers.get("BTC-USD")
                v *= btc.price if btc else 0
            elif p.quote == "ETH":
                eth = tickers.get("ETH-USD")
                v *= eth.price if eth else 0
            elif p.quote not in ("USD", "USDC", "USDT"):
                v *= 0.8   # close enough to rank EUR, GBP, CAD
            return v

        self.products = sorted(products, key=usd_volume, reverse=True)
        self.volume = {p.id: usd_volume(p) for p in products}

    def compose(self) -> ComposeResult:
        with Vertical(classes="popup popup-add") as box:
            box.border_title = "Add a pair"
            box.border_subtitle = _hint([("add", "enter"), ("move", "up down"), ("close", "esc")])
            yield Input(placeholder="Type a symbol or name: sol, pepe, eth-btc", id="add-input")
            yield PanelList(classes="menu-list", id="add-list", empty="no matching markets")

    def on_mount(self) -> None:
        self.refilter("")
        self.query_one(Input).focus()

    def _row(self, p: Product) -> Row:
        t = self.tickers.get(p.id)
        left = Text(" ")
        left.append("● " if p.id in self.have else "  ", style=Style(color=C_GREEN))
        left.append(p.base, style=Style(bold=True))
        left.append(("-" + p.quote).ljust(6), style=DIM)
        if t and t.price:
            left.append(fmt_price(t.price).rjust(14))
        right = Text()
        if t and t.open_24h:
            right.append(fmt_pct(t.change_pct).rjust(8), style=Style(color=C_GREEN if t.change_pct >= 0 else C_RED))
        vol = self.volume.get(p.id, 0)
        right.append(("$" + fmt_compact(vol) if vol else "").rjust(9), style=DIM)
        return Row(left, right, key=p.id)

    def refilter(self, needle: str) -> None:
        words = needle.lower().replace("/", "-").split()
        if words:
            def ok(p: Product) -> bool:
                blob = f"{p.id} {p.base} {p.quote}".lower()
                return all(w in blob for w in words)

            exact = sorted((p for p in self.products if p.base.lower() == words[0] and ok(p)),
                           key=lambda p: ("USD", "USDC", "USDT").index(p.quote)
                           if p.quote in ("USD", "USDC", "USDT") else 9)
            rest = [p for p in self.products if ok(p) and p not in exact]
            shown = exact + rest
        else:
            shown = self.products
        lst = self.query_one(PanelList)
        rows = [self._row(p) for p in shown[:300]]
        lst.styles.height = max(1, min(len(rows), 24, self.app.size.height - 10))
        lst.set_rows(rows, keep=rows[0].key if rows else None)
        box = self.query_one(".popup-add")
        box.border_title = f"Add a pair ─ {len(shown)} markets"

    def on_input_changed(self, event: Input.Changed) -> None:
        self.refilter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(self.query_one(PanelList).selected_key)

    def on_panel_list_activated(self, event: PanelList.Activated) -> None:
        self.dismiss(event.key)

    def action_move(self, n: int) -> None:
        self.query_one(PanelList).move(n)

    def action_cancel(self) -> None:
        self.dismiss(None)
