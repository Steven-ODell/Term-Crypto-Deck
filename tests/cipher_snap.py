"""The Cipher page, headless, with screenshots. State goes to .scratch/, never
your real paper account or watchlist.

    uv run python tests/cipher_snap.py demo     # made-up market: waits for longs, a short, a stop
    uv run python tests/cipher_snap.py live     # real Coinbase prices, one scan, no waiting for trades
"""

import asyncio
import os
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
SCRATCH = PROJECT / ".scratch"
SHOTS = SCRATCH / "shots"
os.environ["XDG_DATA_HOME"] = str(SCRATCH / "cipher" / "data")
os.environ["XDG_CONFIG_HOME"] = str(SCRATCH / "cipher" / "config")
os.environ["XDG_CACHE_HOME"] = str(SCRATCH / "cipher" / "cache")
sys.path.insert(0, str(PROJECT / "src"))

from coindeck.app import CoinDeck          # noqa: E402
from coindeck.cipher.bot import Bot        # noqa: E402
from coindeck.cipher.paper import Config   # noqa: E402
from coindeck.cipher.screen import CipherScreen  # noqa: E402


class View:
    """The test reads the bot through the old app's attribute names."""
    def __init__(self, deck: CoinDeck) -> None:
        self.deck = deck

    def __getattr__(self, name):
        return getattr(self.deck.bot, name)

    @property
    def cfg(self):
        return self.deck.bot.cfg

    def save_screenshot(self, **kw):
        return self.deck.save_screenshot(**kw)


async def shot(app, pilot, name: str) -> None:
    await pilot.pause(1.2)      # the page redraws once a second
    SHOTS.mkdir(parents=True, exist_ok=True)
    app.save_screenshot(filename=f"cipher-{name}.svg", path=str(SHOTS))
    print("saved", SHOTS / f"cipher-{name}.svg")


async def wait_for(pilot, cond, seconds: float) -> bool:
    for _ in range(int(seconds / 0.2)):
        if cond():
            return True
        await pilot.pause(0.2)
    return cond()


async def demo() -> None:
    deck = CoinDeck(demo=True, bot=Bot(cfg=Config(balance=1000), demo=True), cipher=True)
    app = View(deck)
    async with deck.run_test(size=(150, 42)) as pilot:
        assert await wait_for(pilot, lambda: isinstance(deck.screen, CipherScreen), 5), "page did not open"
        assert await wait_for(pilot, lambda: len(app.reads) == 6, 10), "no reads"
        await shot(app, pilot, "demo-01-scan")
        assert await wait_for(pilot, lambda: app.acct.position is not None, 60), "never opened"
        await shot(app, pilot, "demo-02-open")
        seen: set[str] = set()

        def sides() -> set[str]:
            seen.update(t.side for t in app.acct.trades)
            if app.acct.position:
                seen.add(app.acct.position.side)
            return seen

        ok = await wait_for(pilot, lambda: {"long", "short"} <= sides() and len(app.acct.trades) >= 4, 300)
        reasons = {t.reason for t in app.acct.trades}
        print("trades", len(app.acct.trades), "sides", sides(), "exits", reasons,
              "equity", round(app.acct.equity(app.pos_quote()), 2))
        await shot(app, pilot, "demo-03-trades")
        assert ok, "did not see both a long and a short"
        # b goes back to the charts; the bot keeps trading and shows in the bar
        await pilot.press("b")
        assert not isinstance(deck.screen, CipherScreen)
        n = app.acted_t
        await pilot.pause(3)
        assert app.acted_t > n, "bot stopped while the charts were up"
        assert "cipher" in deck.bot.status().plain
        deck.save_screenshot(filename="cipher-demo-03b-charts.svg", path=str(SHOTS))
        await pilot.press("x")          # remove on the watchlist, not close the position
        assert isinstance(deck.screen, CipherScreen) is False
        await pilot.press("b")
        assert isinstance(deck.screen, CipherScreen)
        # pause blocks entries; manual close works
        await pilot.press("space")
        assert app.paused
        if app.acct.position is None:
            await wait_for(pilot, lambda: app.acct.position is not None, 1)
        if app.acct.position is not None:
            n = len(app.acct.trades)
            await pilot.press("x")
            assert await wait_for(pilot, lambda: len(app.acct.trades) == n + 1, 5)
            assert app.acct.trades[-1].reason == "manual"
        await pilot.pause(8)
        assert app.acct.position is None, "opened while paused"
        await shot(app, pilot, "demo-04-paused")
        # reset needs two presses
        await pilot.press("R")
        assert app.acct.trades
        await pilot.press("R")
        assert not app.acct.trades and app.acct.cash == 1000
        # stops: tighten them so the price poll trips one
        app.cfg.spot_stop = app.cfg.perp_stop = 0.0015
        await pilot.press("space")
        assert not app.paused
        ok = await wait_for(pilot, lambda: any(t.reason == "stop" for t in app.acct.trades), 120)
        print("after stop test:", [(t.coin, t.side, t.reason, round(t.pnl, 2)) for t in app.acct.trades])
        await shot(app, pilot, "demo-05-stop")
        assert ok, "no stop exit"


async def live() -> None:
    deck = CoinDeck(cipher=True)
    app = View(deck)
    async with deck.run_test(size=(150, 42)) as pilot:
        ok = await wait_for(pilot, lambda: len(app.reads) == 6 and len(app.spot) == 6 and app.perp, 60)
        await pilot.pause(1.5)
        await shot(app, pilot, "live-01")
        assert ok, f"feed={app.feed} reads={list(app.reads)} spot={list(app.spot)}"
        for c, r in app.reads.items():
            q = app.spot[c]
            print(f"{c:8} close {r.close:<10} bid {q.bid:<10} wt1 {r.wt1:+.1f} wt2 {r.wt2:+.1f} "
                  f"mf {r.mf:+.1f} {r.signal}")
        print("NEAR perp", app.perp["NEAR"], "next scan in", round(app.next_scan - __import__('time').time()))


asyncio.run(demo() if sys.argv[1:] == ["demo"] else live())
