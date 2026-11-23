import json, os, subprocess, sys, time, urllib.request, urllib.parse
UA = {"User-Agent": "Mozilla/5.0 (compatible; nfl-bets-assistant/1.0; personal, read-only)"}
LOG = []
def log(s):
    print(s, flush=True); LOG.append(s); open("probe/out/index.txt", "w").write("\n".join(LOG))
def get(u, t=40, tries=2):
    err = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t) as r:
                return r.read()
        except Exception as e:
            err = e; time.sleep(3)
    raise err
def push(msg):
    subprocess.run("git add -f probe/out && git commit -q -m '%s' && git push -q" % msg, shell=True)
os.makedirs("probe/out", exist_ok=True)
subprocess.run('git config user.name "nfl-bets-bot"; git config user.email "41898282+github-actions[bot]@users.noreply.github.com"', shell=True)
part = sys.argv[1]
WEEKS = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else list(range(1, 19))
if part == "nfl":
    for w in range(1, 19):
        try:
            open(f"probe/out/nfl-{w}.html", "wb").write(get(f"https://www.nfl.com/news/nfl-picks-week-{w}-2025-nfl-season")); log(f"nfl {w} ok")
        except Exception as e:
            log(f"nfl {w} err {e}")
        time.sleep(1)
    push("probe output nfl")
else:
    kind = part
    for w in WEEKS:
        t0 = time.time()
        try:
            q = urllib.parse.urlencode({"url": f"cbssports.com/nfl/picks/experts/{kind}/{w}/", "from": "20250905", "to": "20260815",
                                        "output": "json", "fl": "timestamp", "filter": "statuscode:200", "limit": "40"})
            tss = [r[0] for r in json.loads(get("https://web.archive.org/cdx/search/cdx?" + q, t=60) or b"[]")[1:]]
        except Exception as e:
            log(f"cbs {kind} {w} cdx err {e}"); continue
        ok = False
        for ts in tss[:6]:
            time.sleep(6)
            try:
                b = get(f"https://web.archive.org/web/{ts}id_/https://www.cbssports.com/nfl/picks/experts/{kind}/{w}/", t=60)
                if b"TableBase-bodyTr" in b and (b"NFL_2025" in b or b"NFL_2026010" in b):
                    open(f"probe/out/cbs-{kind}-{w}.html", "wb").write(b); ok = True; log(f"cbs {kind} {w} {ts} ok {int(time.time()-t0)}s"); break
                log(f"cbs {kind} {w} {ts} nomatch {len(b)}")
                if not os.path.exists(f"probe/out/nomatch-{kind}-{w}.html"):
                    open(f"probe/out/nomatch-{kind}-{w}.html", "wb").write(b[:400000])
            except Exception as e:
                log(f"cbs {kind} {w} {ts} err {e}")
        if not ok:
            log(f"cbs {kind} {w} MISSING ({len(tss)} snaps)")
        time.sleep(5)
        if w % 4 == 0:
            push(f"probe output {kind} {w}")
    push(f"probe output {kind}")
