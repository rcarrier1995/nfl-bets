"""Weekly backup (review 2026-11-25): once a week the loop saves a copy of all saved data
(price history, learning, results: state/ + docs/data + config.json) as a GitHub Release file.
Git history already keeps every 10-minute version; this is a second, easy-to-download copy.
  python -m engine.backup due        prints the backup name if one is due this week, else nothing
  python -m engine.backup done NAME  records it
"""
import os
import sys

from . import config as C
from .fetch import load_json, save_json, now_utc

FILE = os.path.join(C.STATE, "backup.json")


def week_tag(now=None):
    y, w, _ = (now or now_utc()).astimezone(C.CT).isocalendar()
    return f"backup-{y}-w{w:02d}"


if __name__ == "__main__":
    a = sys.argv[1:]
    st = load_json(FILE, {}) or {}
    if a[:1] == ["due"]:
        t = week_tag()
        if st.get("last") != t:
            print(t)
    elif a[:1] == ["done"] and len(a) > 1:
        st["last"] = a[1]
        st["at"] = now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
        save_json(FILE, st)
