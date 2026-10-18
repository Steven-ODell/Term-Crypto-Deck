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
cipher      b                the Cipher page, a paper trader (see below)
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

## Cipher page

`b` opens a second page: a paper trader that watches six Coinbase coins (QNT,
NEAR, RENDER, AERO, TAO, VIRTUAL) with the Cipher B signals from VuManChu's
open-source Market Cipher B remake. Every candle close it rescans all six,
picks the strongest signal, and trades it with pretend money at real Coinbase
bid/ask prices and fees. It never places a real order. This was its own app,
cipherdeck, until 2026-10-18.

```
╭─[1] Scanner ───────────────────────────────────────╮╭─[2] Position ─────────────╮
│ coin         price     wt1     wt2    flow  cross  ││ LONG RENDER  spot         │
│ QNT         238.25   -30.7   -38.0    -0.3  up 10  ││ size    480.2 RENDER      │
│ NEAR ⇅      5.8422   +48.9   +53.1    +6.1  dn 1   ││ entry   2.0029   17:33    │
╰──────────────────────────────── 15m · closed 17:30 ╯│ equity  $300.00  +0.00%   │
╭─[3] Log ───────────────────────────────────────────╮╭─[4] Trades ───────────────╮
│ 17:33:37 OPEN LONG 480.2 RENDER @ 2.0029 on spot   ││ 17:33 NEAR  long  -$26.66 │
```

The bot starts the first time you open the page and keeps trading after `b`
or `esc` takes you back to the charts; the bottom right of the chart page then
shows `cipher long RENDER +$3.20` or `cipher flat`. If the saved account holds
a position, the bot starts with coindeck so the stop is watched even if you
never open the page.

```sh
cipherdeck                      # coindeck opened on the Cipher page: 15m candles, $300, 1.2% spot fee
cipherdeck --tf 1h              # slower: about 2 trades a day instead of 7
cipherdeck --balance 500 --reset
cipherdeck --spot-fee 0.006     # if your Coinbase tier is 0.6% taker
cipherdeck --demo               # made-up market, a scan every second, no network
coindeck --cipher               # the same as plain cipherdeck
```

Plain `coindeck` and `b` use the defaults (15m, $300, 1.2%).

```
b esc    back to the charts (the bot keeps running)
space    pause new entries (stops and exits keep running)
x        close the open position now at market
s        rescan now (only a candle that closed in the last 2 minutes can trade)
R R      wipe the paper account back to the starting balance
1-4      focus a panel; the log scrolls with the mouse wheel when focused
q        quit (the account is saved after every fill)
```

The paper account lives in `~/.local/share/cipherdeck/paper.json` (the old
app's folder, kept so the account carried over) and every event is appended to
`events.log` next to it. `--demo` uses its own files and starts fresh every time.

### The rules

`src/coindeck/cipher/strategy.py` is the whole strategy, and the backtest calls
the same functions.

- **Long**: the waves cross up below zero while money flow is green.
- **Short**: the waves cross down above zero while money flow is red. NEAR only.
- **Exit**: the opposite wave cross, or the stop.
- **Stops**: 3% under entry for spot longs, 1.5% over entry for the NEAR short.
- **Pick**: if several coins signal on the same candle, the highest score wins.
  The score is how far from zero the waves crossed plus the money flow strength.
- One position at a time. Spot longs use all the cash.

The scanner also shows the classic Cipher B green and red dots, but nothing
trades on them.

### What Coinbase allows (checked 2026-10-11)

- All six coins trade on Coinbase spot, so any of them can be bought.
- Of the six, only NEAR has a US perp, `NER-20DEC30-CDE` ("NEAR PERP"), so
  NEAR is the only coin that can be shorted. Scanner rows marked `⇅` can short,
  and others show `SHORT (no perp)` greyed out.
- One NEAR PERP contract is 500 NEAR, about $2,950 at $5.90. At the advertised
  10x max leverage, that's about $296 of margin. A $300 account can open
  exactly one contract, and only while it has not lost money. Once it has,
  short signals are skipped and the log says why.
- One contract on $300 is about 10x leverage: a 1% move in NEAR is about $30.
  The bot never opens more than one contract (`max_contracts` in `paper.py`).
- A real short needs a Coinbase Financial Markets derivatives account, which
  is a separate sign-up from spot.

### Estimates, not read from Coinbase

These are in `Config` in `paper.py`:

- Spot taker fee 1.2%, the lowest volume tier. Some sources say 0.6%. Your
  real tier is on your Coinbase fee page.
- Perp taker fee 0.05%. Coinbase advertises "from 0.02%".
- Liquidation when the short's margin falls under 5% of notional.
- Funding payments on the perp are not modelled.

### Backtest

```sh
uv run python scripts/backtest.py                       # 30 days of 15m
uv run python scripts/backtest.py --tf 1h --days 90 --spot-fee 0.006
```

Results on 2026-10-11, $300 start:

| candles | fee | trades | end |
|---|---|---|---|
| 15m, 30 days | 1.2% | 215 | $2 |
| 15m, 30 days | 0.6% | 219 | $23 |
| 15m, 30 days | 0.05% (fees nearly gone) | 222 | $138 |
| 1h, 90 days | 1.2% | 143 | $10 |
| 6h, 365 days | 1.2% | 69 | $44 |

Holding any of the six over the same 30 days made between +18% and +275%.
These rules lose money even with fees taken out, and fees make it much worse.
At 7 trades a day, the 15m default pays about 17% of the account in fees each
day. Treat the paper run as a way to watch the signals work, not as proof
they make money.

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
| `~/.local/share/cipherdeck/paper.json` | the Cipher page's paper account |
| `~/.local/share/cipherdeck/events.log` | everything the Cipher page has logged |

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
| `src/coindeck/cipher/waves.py` | Cipher B math ported from VuManChu's Pine v4 (default inputs) |
| `src/coindeck/cipher/strategy.py` | long/short/exit/pick rules, shared with `scripts/backtest.py` |
| `src/coindeck/cipher/paper.py` | the paper account: fills at bid/ask, fees, NEAR perp contracts and margin |
| `src/coindeck/cipher/coinbase.py` | the page's own market client (spot quotes, NEAR perp book) and its demo market |
| `src/coindeck/cipher/bot.py` | the loop: scan on candle close + 8 s, price poll every 5 s, the log |
| `src/coindeck/cipher/screen.py` | the Cipher page |

## Tests

```sh
uv run python tests/snap.py demo    # offline: drives every key, asserts, saves screenshots
uv run python tests/snap.py live    # the same against real Coinbase data
uv run python tests/test_paper.py          # paper account arithmetic against hand-worked numbers
uv run python tests/cipher_snap.py demo    # Cipher page: long, short, cross exit, stop, manual close, pause, reset, b and back
uv run python tests/cipher_snap.py live    # Cipher page against real Coinbase prices, one scan
```

Screenshots land in `.scratch/shots/` as SVG. State goes to `.scratch/` too,
so your own watchlist is never touched.

## Credits

The Cipher B math is VuManChu's Cipher B + Divergences (MPL-2.0), which built
on LazyBear's WaveTrend and others. See `src/coindeck/cipher/waves.py`.
