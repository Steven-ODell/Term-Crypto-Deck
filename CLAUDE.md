# coindeck

Side project (Claude-built, Sao uses it). Crypto market watcher plus the Cipher
page, a Cipher B paper trader that was the separate cipherdeck repo until
2026-10-18. Python 3.12, Textual, httpx, run with uv. README.md has the keys,
the trading rules, the Coinbase facts and the backtest numbers.

- The chart side: `app.py`, `chart.py`, `feed.py`, `market.py`, `widgets.py`,
  `screens.py`, `config.py`.
- The Cipher page lives in `src/coindeck/cipher/`. `bot.py` runs the loop on
  app-level timers so it keeps trading while the chart page is up; `screen.py`
  only draws. `strategy.py` is shared with `scripts/backtest.py`; keep it that
  way so backtest numbers describe the bot.
- Never place real orders without Sao asking for live mode in so many words.
  Live mode does not exist. It would use a Coinbase Advanced Trade API key with
  trade permission only, never withdraw.
- Tests write only to `.scratch/`. Never point one at `~/.config/coindeck` or
  `~/.local/share/cipherdeck`: those are his real watchlist, holdings and paper
  account.

Installed as an editable uv tool from this repo, providing both `coindeck` and
`cipherdeck`; listed in `~/Omarchy-merge/uv-tools.list`.
