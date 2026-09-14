"""coindeck: a lazygit-style crypto market watcher. Coinbase public data, no API key."""

from __future__ import annotations

import argparse

__version__ = "0.1.0"


def main() -> None:
    parser = argparse.ArgumentParser(prog="coindeck", description=__doc__)
    parser.add_argument("--demo", action="store_true",
                        help="an offline, made-up market: for trying keys without a network")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()

    from .app import CoinDeck

    CoinDeck(demo=args.demo).run()
