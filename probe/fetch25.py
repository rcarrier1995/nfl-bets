import json, os, time, urllib.request, urllib.parse
UA = {"User-Agent": "Mozilla/5.0 (compatible; nfl-bets-assistant/1.0; personal, read-only)"}
def get(u):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as e:
            err = e; time.sleep(5)
    raise err
os.makedirs("probe/out", exist_ok=True)
log = []
for kind in ("straight-up", "against-the-spread"):
    q = urllib.parse.urlencode({"url": f"cbssports.com/nfl/picks/experts/{kind}/*", "from": "20250905", "to": "20260815",
                                "output": "json", "fl": "timestamp,original", "filter": "statuscode:200"})
    rows = json.loads(get("https://web.archive.org/cdx/search/cdx?" + q))[1:]
    json.dump(rows, open(f"probe/out/cdx-{kind}.json", "w"))
    best = {}
    for ts, orig in rows:
        w = urllib.parse.urlparse(orig).path.rstrip("/").split("/")[-1]
        if w.isdigit() and 1 <= int(w) <= 18:
            best.setdefault(int(w), []).append(ts)
    for w in range(1, 19):
        tss = sorted(best.get(w, []))
        ok = False
        for ts in tss[:4]:
            try:
                b = get(f"https://web.archive.org/web/{ts}id_/https://www.cbssports.com/nfl/picks/experts/{kind}/{w}/")
                if b"TableBase-bodyTr" in b and b"NFL_2025" in b or b"NFL_2026010" in b:
                    open(f"probe/out/cbs-{kind}-{w}.html", "wb").write(b); ok = True; log.append(f"cbs {kind} {w} {ts} ok"); break
                log.append(f"cbs {kind} {w} {ts} nomatch")
            except Exception as e:
                log.append(f"cbs {kind} {w} {ts} err {e}")
            time.sleep(2)
        if not ok:
            log.append(f"cbs {kind} {w} MISSING ({len(tss)} snaps)")
for w in range(1, 19):
    for u in (f"https://www.nfl.com/news/nfl-picks-week-{w}-2025-nfl-season",):
        try:
            open(f"probe/out/nfl-{w}.html", "wb").write(get(u)); log.append(f"nfl {w} ok")
        except Exception as e:
            log.append(f"nfl {w} err {e}")
        time.sleep(2)
open("probe/out/index.txt", "w").write("\n".join(log))
