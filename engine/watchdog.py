"""Watchdog (review 2026-11-25), run by .github/workflows/watchdog.yml every 15 minutes, separate from the loop.

Looks at the LIVE site the way Rick's phone does:
  - the page, app.js and style.css load, and board.json is real JSON with games  (site self-test)
  - board.json was updated in the last 45 minutes                                 (app still running)
One phone push when either breaks, one when it's fixed. Exit code 3 = the loop looks stopped,
so the workflow restarts it. State is kept in the Actions cache (path given as argv[1]).
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

from . import alarm as AL

STALE_MIN = 45
SITE_FAILS = 2


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "nfl-bets-watchdog/1.0", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status}")
        return r.read()


def site_url():
    owner, repo = (os.environ.get("GITHUB_REPOSITORY") or "rcarrier1995/nfl-bets").split("/")
    return f"https://{owner}.github.io/{repo}/"


def check(base):
    """Returns (problem or None, minutes since last update or None)."""
    t = int(time.time())
    try:
        html = _get(f"{base}?t={t}").decode("utf-8", "ignore")
        for asset in re.findall(r'(?:src|href)="((?:app\.js|style\.css)[^"]*)"', html) or ["app.js", "style.css"]:
            _get(base + asset)
        b = json.loads(_get(f"{base}data/board.json?t={t}"))
        if not b.get("games"):
            return "the app's data has no games", None
        gen = datetime.fromisoformat(b["generatedAt"].replace("Z", "+00:00"))
        return None, (datetime.now(timezone.utc) - gen).total_seconds() / 60
    except Exception as e:
        return f"the app page didn't load ({str(e)[:80]})", None


def main(state_path):
    AL.FILE = state_path
    st = AL._load()
    problem, age = check(site_url())
    if problem:
        st["siteFails"] = st.get("siteFails", 0) + 1
        print("site problem:", problem, "x", st["siteFails"])
        if st["siteFails"] >= SITE_FAILS:
            AL.raise_("site", "App site not loading", f"Self-test failed: {problem}. Claude can fix it.", st=st)
        else:
            AL.save_json(state_path, st)
        return 0
    st["siteFails"] = 0
    AL.clear("site", "App site is loading again", st=st)
    print(f"board age {age:.0f} min")
    if age > STALE_MIN:
        AL.raise_("stale", "App stopped updating",
                  f"Last update {age:.0f} min ago. Restarting it now. Until it's back, check prices in Robinhood before buying.", st=st)
        return 3
    AL.clear("stale", "App is updating again", st=st)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/watchdog/state.json"))
