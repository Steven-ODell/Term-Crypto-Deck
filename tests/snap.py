"""Headless screenshots and behaviour checks.

    uv run python tests/snap.py demo    # offline demo market, deterministic enough to assert on
    uv run python tests/snap.py live    # real Coinbase data (read-only public API)

State and screenshots go to .scratch/ so your real watchlist is never touched.
"""

import asyncio
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
SCRATCH = PROJECT / ".scratch"
SHOTS = SCRATCH / "shots"


def setup_env(name: str) -> None:
    base = SCRATCH / name
    os.environ["XDG_CONFIG_HOME"] = str(base / "config")
    os.environ["XDG_CACHE_HOME"] = str(base / "cache")
    for f in (base / "config" / "coindeck").glob("state*.json"):
        f.unlink()
    SHOTS.mkdir(parents=True, exist_ok=True)


async def shot(app, pilot, name: str) -> None:
    await pilot.pause(0.4)
    app.save_screenshot(filename=f"{name}.svg", path=str(SHOTS))
    print("saved", SHOTS / f"{name}.svg")


async def wait_for(pilot, cond, seconds: float = 15.0) -> bool:
    for _ in range(int(seconds / 0.1)):
        if cond():
            return True
        await pilot.pause(0.1)
    return cond()


async def run(demo: bool, size=(170, 46)) -> None:
    prefix = "demo" if demo else "live"
    setup_env(prefix)
    from coindeck.app import CoinDeck

    app = CoinDeck(demo=demo)
    async with app.run_test(size=size) as pilot:
        chart = app.p_chart
        ok = await wait_for(pilot, lambda: chart.series is not None and len(chart.series.candles) > 50)
        assert ok, f"no candles: {chart.series and chart.series.error}"
        await wait_for(pilot, lambda: len(app.trades) > 3, 10)
        await wait_for(pilot, lambda: all(app.tickers.get(p) and app.tickers[p].price
                                          for p in app.state.watchlist), 10)
        await shot(app, pilot, f"{prefix}-01-start")
        print("feed:", app.feed.status, "trades:", len(app.trades),
              "candles:", len(chart.series.candles), "tf:", app.tf.name)

        # move down the watchlist: chart follows
        await pilot.press("j")
        assert app.selected == app.state.watchlist[1], app.selected
        await wait_for(pilot, lambda: len(chart.series.candles) > 50)
        await shot(app, pilot, f"{prefix}-02-eth")

        # cursor and pan
        await pilot.press("0")
        for _ in range(12):
            await pilot.press("h")
        assert chart.cursor is not None
        await shot(app, pilot, f"{prefix}-03-cursor")
        await pilot.press("H")
        assert chart.back > 0
        await pilot.press("escape")
        assert chart.cursor is None and chart.back == 0

        # timeframes, including a merged one
        await pilot.press("right_square_bracket")        # 4h, merged from 1h
        assert app.tf.name == "4h", app.tf.name
        await wait_for(pilot, lambda: not chart.series.loading and len(chart.series.candles) > 50)
        c = chart.series.candles
        assert all(b.t - a.t == 14400 for a, b in zip(c, c[1:])), "4h buckets not contiguous"
        await shot(app, pilot, f"{prefix}-04-4h")
        await pilot.press("left_square_bracket", "left_square_bracket", "left_square_bracket")
        assert app.tf.name == "5m", app.tf.name
        await wait_for(pilot, lambda: len(chart.series.candles) > 50)

        # zoom and line
        await pilot.press("plus")
        await shot(app, pilot, f"{prefix}-05-5m-wide")
        await pilot.press("minus", "minus", "c")
        assert chart.mode == "line"
        await shot(app, pilot, f"{prefix}-06-line-dense")
        await pilot.press("c", "equals_sign", "v")
        assert chart.mode == "candles" and not chart.volume
        await pilot.press("v")

        # history: go to the oldest candle, more gets loaded
        before = len(chart.series.candles)
        await pilot.press("g")
        await wait_for(pilot, lambda: len(chart.series.candles) > before, 10)
        print("history:", before, "->", len(chart.series.candles))
        assert len(chart.series.candles) > before
        await pilot.press("G")

        # add a pair through the search popup
        await pilot.press("1", "a")
        await pilot.pause(0.3)
        assert type(app.screen).__name__ == "AddScreen"
        for ch in "pepe":
            await pilot.press(ch)
        await shot(app, pilot, f"{prefix}-07-add")
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert "PEPE-USD" in app.state.watchlist, app.state.watchlist
        assert app.selected == "PEPE-USD", app.selected
        await wait_for(pilot, lambda: len(chart.series.candles) > 50)
        await pilot.press("K")
        assert app.state.watchlist[-2] == "PEPE-USD"
        await shot(app, pilot, f"{prefix}-08-pepe")
        await pilot.press("d")
        assert "PEPE-USD" not in app.state.watchlist

        await pilot.press("f")
        await shot(app, pilot, f"{prefix}-09-fullscreen")
        await pilot.press("f", "question_mark")
        await shot(app, pilot, f"{prefix}-10-help")
        await pilot.press("escape")

    async with CoinDeck(demo=demo).run_test(size=(96, 32)) as pilot:
        await wait_for(pilot, lambda: pilot.app.p_chart.series is not None
                       and len(pilot.app.p_chart.series.candles) > 20)
        await shot(pilot.app, pilot, f"{prefix}-11-narrow")
    print(prefix, "ok")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "demo"
    asyncio.run(run(demo=which != "live"))
