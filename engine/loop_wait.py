"""Seconds until the next loop tick: 6 min while a game is on or starts within 45 min, else 10 min."""
import json
import os
from datetime import datetime, timedelta, timezone



def wait_seconds(now=None):
    now = now or datetime.now(timezone.utc)
    try:
        with open(os.path.join("docs", "data", "board.json")) as f:
            games = json.load(f).get("games", [])
    except Exception:
        return 600
    for g in games:
        if g.get("state") == "in":
            return 360
        try:
            k = datetime.fromisoformat((g.get("kickoff") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if g.get("state") == "pre" and now <= k <= now + timedelta(minutes=45):
            return 360
    return 600


if __name__ == "__main__":
    print(wait_seconds())
