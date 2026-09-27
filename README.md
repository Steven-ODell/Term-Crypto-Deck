# coindeck

A crypto market watcher for the terminal. Your watchlist down the side, a live
candlestick chart of whichever pair is selected, the 24h numbers and the trade
tape underneath. Coinbase public market data, no account or API key.

```
╭─ [1]─Watchlist ──────────────────────────╮╭─ [0]─Chart ─ BTC-USD candles ────────────────────────────────╮
│ BTC        77,582.64 ▂▃▃▄▅▆▆▇█▇  +0.63%  ││ Sun Sep 13 23:00  O 77,576.65  H 77,862.41  L 77,334.00  live │
│ ETH         2,515.01 ▁▂▂▃▅▅▆▇▇█  +0.12%  ││            ╷                                        │77,750  │
│ SOL           101.48 ▃▂▃▄▄▅▆▇▇█  +0.27%  ││   ╷ ╷ ┃ ╷  ┃ ╷                               ╻  ┃ ╷  │        │
│ DOGE         0.08435 █▇▆▅▄▅▅▄▃▃  -0.05%  ││ ╌╌┃╌╿╌┃╌╿╌╌╿╌┃╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┃╌╌╿╌┃╌├77,582.64│
╰──────────────────────────── 1 of 10 ─────╯│   ╵ ┃ ╵ ╵  ╵ ╵        ╷   ╷                ╽  ╵ ╵  ┤77,250  │
╭─ [2]─Market ─ BTC-USD ───────────────────╮│         ╵            ┃ ╻ ┃  ╷ ╻            ┃       │        │
│ last     77,582.64                       ││                      ╵ ┃ ╵  ┃ ┃ ╷          ╵       ┤77,000  │
│ 24h      ▲ 482.89  +0.63%                ││                        ╵    ╵ ╵ ┃                  │vol 341 │
│ range    ━━━━━━━━━━━━━━━━━●━━━━  82%     ││ ▃ ▂ ▂ ▁ ▂ ▁ ▂ ▁ ▃ ▂ ▁ ▂ ▁ ▃ ▂ ▅ ▃ ▂ ▆ ▃ ▂ ▁ ▂ ▃ ▇ ▅ │        │
╰──────────────────── 24h stats just now ──╯│ 17:00       22:00       Sep 12      08:00      13:00           │
╭─ [3]─Trades ─────────────────────────────╮│                                                               │
│ 23:52:56   77,582.64  0.00061234         ││                                                               │
╰───────────────────────────────── 4/min ──╯╰─────── 1m 5m 15m [1h] 4h 6h 1d 1w   300 candles ────────────╯
 timeframe: [ ] | add: a | remove: d | reorder: J K | cursor: h l | line: c | keys: ?          ● live  coindeck
```

Candles are drawn at half-cell height with box-drawing glyphs, so a 40 row
terminal gets 80 rows of price resolution. `c` swaps to a braille line chart.

## Run it

```sh
cd ~/Projects/Side/coindeck
uv run coindeck
```

To have it on your PATH as `coindeck`:

```sh
uv tool install -e ~/Projects/Side/coindeck
```

`coindeck --demo` runs a made-up market that needs no network: the same
interface, prices from a seeded random walk. Handy on a plane, and what the
tests use. It keeps its own watchlist so it never touches the real one.

## Keys

```
panels      1 2 3 0          Watchlist, Market, Trades, Chart
            tab shift-tab    next and previous panel
            f                chart fills the window, again to bring the panels back
watchlist   j k arrows       move; the chart follows the selection (also works with the chart focused)
            g G              top and bottom
            J K              move the selected pair down or up the list
            a                add a pair: search every market on Coinbase, most traded first
            d                remove the selected pair
            enter            focus the chart
chart       [ ]  t           previous / next timeframe: 1m 5m 15m 1h 4h 6h 1d 1w
            h l arrows       move the cursor over candles, from any panel
            H L ctrl-u ctrl-d  pan half a screen back / forward
            - +              narrower / wider candles (three widths)
            c                candles or line
            v                volume strip on or off
            g G              oldest loaded candle / back to live
            esc              drop the cursor and follow live again
            mouse            wheel pans, click puts the cursor on a candle
holdings    e                set how much of the selected token you hold (0 stops tracking it)
            p                portfolio: every token held, its dollar value, 24h move and share
other       y                copy the price under the cursor, or the last price (wl-copy)
            o                open the pair on coinbase.com
            r                reload candles and 24h stats
            ?                key list
            q ctrl-c         quit
```

The lit border says which panel has focus. With the cursor on a candle the
header line shows that candle's open, high, low, close, change and volume, and
the time axis shows its full date.

## Panels

**Watchlist.** Price, a 24 hour sparkline from hourly closes, and the change
since 24 hours ago. A price flashes green or red for a moment when it ticks.

**Chart.** Title says pair and style; the bottom border shows the timeframe
strip and how many candles are loaded. The header reads `live` while the right
edge is the current candle, or `N back` when panned. The dashed line and the
coloured label on the axis are the last traded price. Going back past the
oldest loaded candle fetches another page of history until Coinbase runs out.

**Market.** Last price, 24h change, high, low, where the price sits in today's
range, 24h volume (with the dollar value for USD pairs), best bid and ask with
the spread.

**Holdings.** Amounts you own, per token (TAO, not TAO-USD), priced off the
token's USD pair. The Market panel's `holding` line shows the selected token's
amount and dollar value, the Watchlist border shows the total, and `p` opens the
full table with a total row. Held tokens tick live even when they are not on
the watchlist.

**Trades.** The live tape for the selected pair, newest first. Green is a buyer
taking the ask, red a seller hitting the bid. Trades over $25k are bold with
their dollar size in amber. The border shows trades per minute.

## Where the data comes from

All from the [Coinbase Exchange public API](https://docs.cdp.coinbase.com/exchange/),
no key:

| What | Endpoint |
|---|---|
| Market list for the add popup | `GET /products`, cached a week in `~/.cache/coindeck/products.json` |
| 24h stats for every pair at once | `GET /products/stats`, every 60 s |
| Candles | `GET /products/{id}/candles`, 300 per request; the active chart refreshes every 20 s |
| Live prices and trades | websocket `wss://ws-feed.exchange.coinbase.com`: `ticker` for every watched pair, `matches` for the charted one |

Between REST refreshes the chart's last candle moves with every trade from the
websocket. REST requests go one at a time with a short gap, well under the
public rate limit. The websocket reconnects with backoff; the bottom right says
`● live`, `◌ connecting` or `✗ offline`.

Coinbase serves 1m, 5m, 15m, 1h, 6h and 1d candles. 4h is built from 1h and 1w
from 1d (weeks start Monday). Minutes with no trades are missing from Coinbase's
data; they come back as flat grey candles so the time axis stays even.

## Files

| Path | What |
|---|---|
| `~/.config/coindeck/state.json` | watchlist, holdings, selected pair, timeframe, zoom, line or candles, volume on or off |
| `~/.config/coindeck/state-demo.json` | the same for `--demo` |
| `~/.cache/coindeck/products.json` | Coinbase market list, safe to delete |

## Code

| File | What |
|---|---|
| `src/coindeck/app.py` | the app: layout, keys, workers that fetch, live updates, panel text |
| `src/coindeck/chart.py` | the chart widget: viewport (pan, cursor, zoom) and all drawing |
| `src/coindeck/feed.py` | REST client, websocket feed, and the demo market with the same interface |
| `src/coindeck/market.py` | candles, series merging, timeframes, tickers, number formatting |
| `src/coindeck/widgets.py` | list, text panel and command bar, in launchdeck's palette |
| `src/coindeck/screens.py` | add-pair search, key list, confirm popup |
| `src/coindeck/config.py` | state and cache files |

## Tests

```sh
uv run python tests/snap.py demo    # offline: drives every key, asserts, saves screenshots
uv run python tests/snap.py live    # the same against real Coinbase data
```

Screenshots land in `.scratch/shots/` as SVG. State goes to `.scratch/` too,
so your own watchlist is never touched.
