# NFL Bets — Rick's prediction-market assistant

**Suggestions and alerts only.** It never signs in to a betting account, never places a bet, never buys anything. You place every bet yourself in the Robinhood app.

**Open it:** https://rcarrier1995.github.io/nfl-bets/ — works on phone and computer. On iPhone: Safari → Share → *Add to Home Screen*.

## How it runs (free, in the cloud)
- **GitHub Pages** hosts the app (`docs/`).
- **GitHub Actions** runs `engine/` every 10 minutes (`.github/workflows/tick.yml`). In Central time it decides what's due:
  | Job | When (CT) |
  |---|---|
  | nfl-pregame-weekly | Thu 12:00 — full refresh, nflverse stats, Thursday baseline |
  | Morning Top 3 push | Thu & Sun 8:00 |
  | nfl-sunday-inactives | Sun 10:30 |
  | nfl-live-sunday | every 10 min while any game is live |
  | nfl-window-early / late / snf | Sun 15:35 / 18:50 / 23:00 (and the moment a window's last game is final) |
  | nfl-learning-monday | Mon 23:45 (after MNF) |
  | board refresh | hourly otherwise |
- Results are committed back to `docs/data/` (what the app reads) and `state/` (model memory).
- **Manual jobs:** Actions → *manual* → Run workflow (e.g. `inactives` for the Sunday inactives check).

## Phone alerts
Free **ntfy** app → subscribe to the topic in `config.json`. Change it by editing that file on GitHub.

## Free data
ESPN (unofficial), Kalshi public API (price proxy — confirm in Robinhood), nflverse, Open-Meteo. No paid keys.

## Code
- `engine/model.py` Version B pricing · `engine/combos.py` exhaustive combo search · `engine/injuries.py` live injury formula + NextQFactor · `engine/live.py` live alerts · `engine/learning.py` grading, lessons, calibration · `engine/backtest.py` rebuilt backtest · `engine/run.py` scheduler.
- Tests: `python -m pytest -q tests/test_core.py`.
