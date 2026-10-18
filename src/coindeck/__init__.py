"""coindeck: a lazygit-style crypto market watcher. Coinbase public data, no API key."""

from __future__ import annotations

import argparse

__version__ = "0.1.0"


def main() -> None:
    parser = argparse.ArgumentParser(prog="coindeck", description=__doc__)
    parser.add_argument("--demo", action="store_true",
                        help="an offline, made-up market: for trying keys without a network")
    parser.add_argument("--cipher", action="store_true",
                        help="open on the Cipher page (the paper trader); b goes to the charts")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()

    from .app import CoinDeck

    CoinDeck(demo=args.demo, cipher=args.cipher).run()


def cipherdeck() -> None:
    """The old cipherdeck command and its flags: coindeck, opened on the Cipher page."""
    from .cipher.bot import TF

    ap = argparse.ArgumentParser(prog="cipherdeck", description="Cipher B paper trader for Coinbase")
    ap.add_argument("--tf", default="15m", choices=TF, help="candle size the signals use (default 15m)")
    ap.add_argument("--balance", type=float, default=300.0,
                    help="starting paper money for a new or reset account (default 300)")
    ap.add_argument("--spot-fee", type=float, default=0.012,
                    help="spot taker fee per fill, 0.012 = 1.2%% (check your Coinbase tier)")
    ap.add_argument("--reset", action="store_true", help="wipe the paper account first")
    ap.add_argument("--demo", action="store_true", help="made-up market, fast scans, no network")
    a = ap.parse_args()

    from .app import CoinDeck
    from .cipher.bot import Bot
    from .cipher.paper import Config

    bot = Bot(tf=a.tf, cfg=Config(balance=a.balance, spot_fee=a.spot_fee), demo=a.demo, reset=a.reset)
    CoinDeck(demo=a.demo, bot=bot, cipher=True).run()
