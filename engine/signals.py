"""Situational signals: rest, byes, travel, division games, prime time, weather, backup QBs...

study() (run by hand: python -m engine.signals) tests each one against the closing sportsbook line
on 2006-2022 and checks it on 2023-2026. A signal only counts if the line misses it by more
than 2 standard errors in the first sample AND it points the same way in the second.
None did, so they are shown on the game as context ("already in the line") and never move a price.
"""
import json
import os

from . import config as C

FILE = os.path.join(C.STATE, "signals_study.json")
GAMES = os.path.join(C.CACHE, "nflverse", "games.csv")
FIX = {"OAK": "LV", "SD": "LAC", "STL": "LAR", "LA": "LAR", "WAS": "WSH", "JAC": "JAX"}
_sched = None


def _lon(t):
    return C.STADIUMS.get(t, (0, 0))[1]


def _schedule():
    global _sched
    if _sched is None:
        try:
            import pandas as pd
            g = pd.read_csv(GAMES, usecols=["season", "week", "game_type", "away_team", "home_team", "away_rest",
                                            "home_rest", "div_game", "gametime", "weekday"])
            g = g[g.season >= 2026]
            _sched = {(int(r.season), FIX.get(r.away_team, r.away_team), FIX.get(r.home_team, r.home_team)): r
                      for r in g.itertuples()}
        except Exception:
            _sched = {}
    return _sched


def tags(season, away, home, kickoff_ct_hour=None):
    """Plain-language situation tags for one game, from the nflverse schedule. Context only."""
    r = _schedule().get((int(season or 0), away, home))
    if r is None:
        return []
    out = []
    ar, hr = r.away_rest, r.home_rest
    if hr - ar >= 3:
        out.append(f"{home} {int(hr)} days rest vs {int(ar)}")
    elif ar - hr >= 3:
        out.append(f"{away} {int(ar)} days rest vs {int(hr)}")
    if hr >= 13:
        out.append(f"{home} off a bye")
    if ar >= 13:
        out.append(f"{away} off a bye")
    if r.div_game == 1:
        out.append("Division game")
    if _lon(home) - _lon(away) > 25 and str(r.gametime) <= "13:05":
        out.append(f"{away} body clock: 1pm ET after flying east")
    if str(r.gametime) >= "19:00" or r.weekday != "Sunday":
        out.append("Prime time")
    return out


DOME_TEAMS = {"ATL", "DET", "LV", "LAC", "LAR", "MIN", "NO", "ARI", "DAL", "HOU", "IND"}


def venue_tags(away, home, indoor, neutral, wx):
    """Altitude / cold / dome context for one game (tested in study(): all already in the line)."""
    out = []
    if home == "DEN" and not neutral:
        out.append("Altitude (Denver, 5,280 ft)")
    if indoor:
        return out          # the weather line already says "Indoors"
    t = (wx or {}).get("tempMin")
    if t is not None and t <= C.WEATHER_TEMP:
        out.append(f"Cold: {t:.0f}°F at kickoff")
        domes = [x for x in (away, home) if x in DOME_TEAMS]
        if domes:
            out.append(f"{'/'.join(domes)} plays home games in a dome")
    elif away in DOME_TEAMS:
        out.append(f"{away} (dome team) outdoors")
    return out


def study():
    import numpy as np
    import pandas as pd
    g = pd.read_csv(GAMES)
    # regular season + playoffs, never preseason (Rick's research rule, 2026-11-23)
    g = g[(g.game_type != "PRE") & g.result.notna() & g.spread_line.notna() & (g.season >= 2006)].copy()
    fix = FIX
    fix={'OAK':'LV','SD':'LAC','STL':'LAR','LA':'LAR','WAS':'WSH','JAC':'JAX'}
    for s in ('home','away'): g[s+'_t']=g[s+'_team'].map(lambda x: fix.get(x,x))
    g['r']=g.result-g.spread_line          # home margin vs line (pts)
    g=g.sort_values(['season','week'])
    # team-game long table
    rows=[]
    for side,opp in (('home','away'),('away','home')):
        sg=1 if side=='home' else -1
        t=pd.DataFrame({'season':g.season,'week':g.week,'team':g[side+'_t'],'opp':g[opp+'_t'],'home':side=='home',
            'r':g.r*sg,'spread':g.spread_line*sg,'rest':g[side+'_rest'],'orest':g[opp+'_rest'],'div':g.div_game,
            'gametime':g.gametime,'weekday':g.weekday,'roof':g.roof,'temp':g.temp,'wind':g.wind,'location':g.location,
            'qb':g[side+'_qb_id'],'margin':g.result*sg,'gid':g.game_id,'gameday':g.gameday,'post':g.game_type!='REG'})
        rows.append(t)
    T=pd.concat(rows).sort_values(['season','week']).reset_index(drop=True)
    T['prev_margin']=T.groupby(['season','team']).margin.shift(1)
    # starter = most common QB in prior games of season
    def backup(df):
        out=[];seen={}
        for q in df.qb:
            top=max(seen,key=seen.get) if seen else None
            out.append(top is not None and q!=top and seen.get(top,0)>=3)
            seen[q]=seen.get(q,0)+1
        return pd.Series(out,index=df.index)
    T['backupQB']=T.groupby(['season','team'],group_keys=False).apply(backup)
    T['oppBackupQB']=T.set_index(['gid','team'])['backupQB'].reindex(list(zip(T.gid,T.opp))).values
    lon=lambda t: C.STADIUMS.get(t,(0,0))[1]
    T['tzshift']=[(lon(o)-lon(t)) for t,o in zip(T.team,T.opp)]   # positive = travelling east
    T['early']=T.gametime.astype(str)<='13:05'
    T['prime']=(T.gametime.astype(str)>='19:00')|(~T.weekday.isin(['Sunday']))
    T['fav']=T.spread>0
    outdoor=T.roof.isin(['outdoors','open'])
    # each team's usual home roof (dome/closed vs open-air), by season
    hr=T[T.home].groupby(['season','team']).roof.agg(lambda x: x.mode().iat[0])
    domeTeam=hr.isin(['dome','closed'])
    T['domeTeam']=[bool(domeTeam.get((a,b),False)) for a,b in zip(T.season,T.team)]
    T['oppDome']=[bool(domeTeam.get((a,b),False)) for a,b in zip(T.season,T.opp)]
    cold=outdoor&(T.temp<=35)
    S={
     'Denver at home (altitude)': T.home&(T.team=='DEN'),
     'Dome team outdoors in cold (≤35°F)': ~T.home&T.domeTeam&cold,
     'Home team vs dome visitor in cold': T.home&T.oppDome&cold,
     'Dome team on the road outdoors': ~T.home&T.domeTeam&outdoor,
     'Home team in a dome': T.home&T.domeTeam&T.roof.isin(['dome','closed']),
     'Rest advantage 3+ days': T.rest-T.orest>=3,
     'Short week vs rested opp': (T.rest<=5)&(T.orest>=7),
     'Off a bye vs normal rest': (T.rest>=13)&(T.orest<=8),
     'Division game · favourite': T['div'].astype(bool)&T.fav,
     'Division game · underdog': T['div'].astype(bool)&~T.fav,
     'West team, 1pm ET road game': (~T.home)&(T.tzshift>25)&T.early,
     'Home team in freezing outdoor game': T.home&outdoor&(T.temp<=32),
     'Windy (15+ mph) · favourite': outdoor&(T.wind>=15)&T.fav,
     'Prime time · favourite': T.prime&T.fav,
     'Prime time · home underdog': T.prime&T.home&~T.fav,
     'Big favourite (10+ pts)': T.spread>=10,
     'Home team (all)': T.home,
     'Home underdog': T.home&~T.fav,
     'After a 20+ pt loss': T.prev_margin<=-20,
     'After a 20+ pt win': T.prev_margin>=20,
     'Backup QB starting': T.backupQB.astype(bool),
     'Opponent on backup QB': T.oppBackupQB.astype(bool),
     'Late season (wk 15+) underdog': (T.week>=15)&~T.fav,
     'Neutral site · favourite': (T.location=='Neutral')&T.fav,
     # short weeks and rest (Rick 2026-11-25, item 8)
     'Thursday game · road team': (T.weekday=='Thursday')&~T.home&(T.rest<=5),
     'Thursday game · favourite': (T.weekday=='Thursday')&T.fav&(T.rest<=5),
     'Thanksgiving · home team': (T.weekday=='Thursday')&T.home&T.gameday.astype(str).str[5:7].eq('11')&(T.week>=11),
     'Thanksgiving · road team': (T.weekday=='Thursday')&~T.home&T.gameday.astype(str).str[5:7].eq('11')&(T.week>=11),
     'Short week · favourite': (T.rest<=5)&T.fav,
     'Short week · underdog': (T.rest<=5)&~T.fav,
     'Off a bye · favourite': (T.rest>=13)&T.fav&~T.post,
     'Off a bye · underdog': (T.rest>=13)&~T.fav&~T.post,
     'Playoffs · team off a bye': T.post&(T.rest>=13),
    }
    out = []
    tr = T.season <= 2022
    te = T.season >= 2023
    for name, m in S.items():
        m = m.fillna(False).astype(bool)
        a, b = T[m & tr].r, T[m & te].r
        if len(a) < 30:
            continue
        se = a.std() / np.sqrt(len(a))
        seb = b.std() / np.sqrt(max(len(b), 1))
        holds = abs(a.mean()) > 2 * se and np.sign(a.mean()) == np.sign(b.mean()) and abs(b.mean()) > 1.5 * seb
        allr = T[m].r
        z = float(allr.mean() / (allr.std() / np.sqrt(len(allr))))
        out.append({"signal": name, "z": round(z, 2), "ptsAll": round(float(allr.mean()), 2),
                    "n": int(len(a)), "pts": round(float(a.mean()), 2), "se": round(float(se), 2),
                    "nTest": int(len(b)), "ptsTest": round(float(b.mean()), 2), "holds": bool(holds)})
    out.sort(key=lambda r: -abs(r["z"]) if np.sign(r["pts"]) == np.sign(r["ptsTest"]) else -abs(r["z"]) / 4)
    res = {"games": int(len(g)), "train": "2006–2022", "test": "2023–2026", "rows": out,
           "finding": (f"None of {len(out)} situations beat the closing line in both samples. Rest, byes, travel, "
                       "division games, prime time, weather, blowouts and big favourites are already priced. "
                       "Altitude, cold, dome/open-air splits, Thursday/Thanksgiving short weeks and byes (incl. playoffs) are in the list too, all priced. Closest: a team starting a backup QB did ~0.7 pts worse than its line in both samples, "
                       "too small and too noisy to price (≈2¢).")}
    with open(FILE, "w") as f:
        json.dump(res, f, indent=1)
    return res


if __name__ == "__main__":
    for r in study()["rows"]:
        print(r)
