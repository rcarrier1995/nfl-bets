"""Pull archived CBS expert straight-up pick pages (2023-24 seasons incl. playoffs) from the Internet Archive.
Run in GitHub Actions (the dev sandbox can't reach archive.org). Saves raw pages gzipped + an index."""
import gzip, json, os, sys, time, urllib.request, urllib.parse

OUT = os.path.join(os.path.dirname(__file__), "pages")
UA = {"User-Agent": "Mozilla/5.0 (compatible; personal research, read-only)"}
FROM, TO = sys.argv[1] if len(sys.argv) > 1 else "20230801", sys.argv[2] if len(sys.argv) > 2 else "20250215"
CAP = 700


def get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa
            print("retry", i, url, e, flush=True)
            time.sleep(5 * (i + 1))
    return None


def cdx(prefix):
    q = urllib.parse.urlencode({"url": prefix, "matchType": "prefix", "from": FROM, "to": TO, "output": "json",
                                "fl": "timestamp,original,statuscode,digest", "filter": "statuscode:200",
                                "collapse": "digest", "limit": "20000"})
    b = get("https://web.archive.org/cdx/search/cdx?" + q)
    rows = json.loads(b or b"[]")
    return rows[1:] if rows else []


os.makedirs(OUT, exist_ok=True)
rows = []
for p in ("www.cbssports.com/nfl/picks/experts/straight-up/", "cbssports.com/nfl/picks/experts/straight-up/",
          "www.cbssports.com/nfl/picks/experts/"):
    r = cdx(p)
    print(p, len(r), flush=True)
    rows += r
    if r:
        break
seen, keep = set(), []
for ts, orig, sc, dg in sorted(rows):
    if "straight-up" not in orig and not orig.rstrip("/").endswith("/experts"):
        continue
    if "against-the-spread" in orig or "?" in orig and "straight-up" not in orig:
        continue
    if dg in seen:
        continue
    seen.add(dg)
    keep.append((ts, orig))
print("unique snapshots", len(keep), flush=True)
# spread the cap evenly if too many
if len(keep) > CAP:
    step = len(keep) / CAP
    keep = [keep[int(i * step)] for i in range(CAP)]
index = []
for n, (ts, orig) in enumerate(keep):
    fn = f"{ts}.html.gz"
    path = os.path.join(OUT, fn)
    if not os.path.exists(path):
        b = get(f"https://web.archive.org/web/{ts}id_/{orig}")
        if not b:
            continue
        with gzip.open(path, "wb") as f:
            f.write(b)
        time.sleep(1.5)
    index.append({"ts": ts, "url": orig, "file": fn})
    if n % 25 == 0:
        print(n, ts, orig, flush=True)
json.dump(index, open(os.path.join(OUT, "index.json"), "w"), indent=0)
print("saved", len(index))
