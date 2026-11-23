"""Constants: teams, stadiums, thresholds, file paths."""
import os
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_DATA = os.path.join(ROOT, "docs", "data")
STATE = os.path.join(ROOT, "state")
CACHE = os.path.join(STATE, "cache")
CT = ZoneInfo("America/Chicago")

ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"
KALSHI_EVENTS = KALSHI_BASE + "/events?series_ticker=KXNFLGAME&status=open&with_nested_markets=true&limit=200"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"

# ---- Pricing model (Version B, the one unified algorithm) ----
SIGMA = 13.5            # points -> probability scale
EPA_ADJ_CAP = 3.0       # +/- pts
EPA_ADJ_WEIGHT = 0.0    # tested 0-0.75 on 2021-2026 (1,519 games): any weight made fairs worse -> 0 (EPA shown, not priced)
HOME_FIELD = 1.5        # pts, used only inside the EPA-implied margin
# Spread-to-probability scale. Fitted on 2021-2025 (1,359 games, log loss), checked on 2026 W1-11:
# k=1.15 is calibrated in every bucket; the old x0.85 / x0.80 shrink made favourites too cheap.
SHRINK = 1.15
SHRINK_FAV = 1.15
LINE_MOVE_PRICED = 2.0  # pts: if the line moved this much since the injury news, the book already priced it
WEATHER_WIND = 15.0     # mph sustained, open-air
WEATHER_TEMP = 35.0     # F
QB_OUT_PTS = -3.5
WRCB_OUT_PTS = -1.0
VALUE_EDGE = 15.0       # cents after fees
WAIT_EDGE = 8.0
FEE_BUFFER_COMBO = 2.0
PREF_SINGLE = 65
PREF_COMBO = 20
GOOD_COMBO = 15
LOOK_DONT_BUY = 2
SHOE_IN = 70            # a shoe-in leg needs fair >= 70c
LOPSIDED_SPREAD = 7.0
COMBO_SIZES = (4, 6, 8, 10)
PTS_TO_CENTS = 2.5      # 1 pt ~ 2-3c of win prob near 50%

# Baseline backtest totals from Rick's original backtest files (Weeks 1-11, 151 games)
BASELINE = {"right": 97, "games": 151, "label": "Weeks 1–11 backtest", "through": "2026-11-21T00:00:00Z"}

# ESPN abbreviation is the house standard.
NFLVERSE_TO_ESPN = {"WAS": "WSH", "LA": "LAR", "JAC": "JAX", "OAK": "LV", "SD": "LAC", "STL": "LAR"}
KALSHI_TO_ESPN = {"JAC": "JAX", "WAS": "WSH", "LA": "LAR"}

TEAM_NAMES = {
    "ARI": "Arizona", "ATL": "Atlanta", "BAL": "Baltimore", "BUF": "Buffalo", "CAR": "Carolina",
    "CHI": "Chicago", "CIN": "Cincinnati", "CLE": "Cleveland", "DAL": "Dallas", "DEN": "Denver",
    "DET": "Detroit", "GB": "Green Bay", "HOU": "Houston", "IND": "Indianapolis", "JAX": "Jacksonville",
    "KC": "Kansas City", "LV": "Las Vegas", "LAC": "LA Chargers", "LAR": "LA Rams", "MIA": "Miami",
    "MIN": "Minnesota", "NE": "New England", "NO": "New Orleans", "NYG": "NY Giants", "NYJ": "NY Jets",
    "PHI": "Philadelphia", "PIT": "Pittsburgh", "SF": "San Francisco", "SEA": "Seattle",
    "TB": "Tampa Bay", "TEN": "Tennessee", "WSH": "Washington",
}

# Home stadium lat/lon by ESPN abbreviation.
STADIUMS = {
    "ARI": (33.5276, -112.2626), "ATL": (33.7554, -84.4008), "BAL": (39.2780, -76.6227),
    "BUF": (42.7738, -78.7870), "CAR": (35.2258, -80.8528), "CHI": (41.8623, -87.6167),
    "CIN": (39.0954, -84.5160), "CLE": (41.5061, -81.6995), "DAL": (32.7473, -97.0945),
    "DEN": (39.7439, -105.0201), "DET": (42.3400, -83.0456), "GB": (44.5013, -88.0622),
    "HOU": (29.6847, -95.4107), "IND": (39.7601, -86.1639), "JAX": (30.3239, -81.6373),
    "KC": (39.0489, -94.4839), "LV": (36.0909, -115.1833), "LAC": (33.9535, -118.3392),
    "LAR": (33.9535, -118.3392), "MIA": (25.9580, -80.2389), "MIN": (44.9737, -93.2575),
    "NE": (42.0909, -71.2643), "NO": (29.9511, -90.0812), "NYG": (40.8128, -74.0742),
    "NYJ": (40.8128, -74.0742), "PHI": (39.9008, -75.1675), "PIT": (40.4468, -80.0158),
    "SF": (37.4030, -121.9700), "SEA": (47.5952, -122.3316), "TB": (27.9759, -82.5033),
    "TEN": (36.1665, -86.7713), "WSH": (38.9078, -76.8645),
}
# Neutral / international venues by a word in the city or venue name.
VENUE_OVERRIDES = {
    "Mexico City": (19.3029, -99.1505), "London": (51.5560, -0.2796), "Tottenham": (51.6043, -0.0664),
    "Munich": (48.2188, 11.6247), "Berlin": (52.5147, 13.2395), "Frankfurt": (50.0686, 8.6455),
    "Madrid": (40.4531, -3.6883), "Melbourne": (-37.8200, 144.9834), "Dublin": (53.3607, -6.2512),
    "Rio de Janeiro": (-22.9122, -43.2302), "São Paulo": (-23.5453, -46.4742), "Sao Paulo": (-23.5453, -46.4742),
    "Paris": (48.9245, 2.3602),
}

# Depth-chart slot -> position group used by the injury formula.
POS_GROUP = {
    "QB": "QB", "RB": "RB", "HB": "RB", "FB": "RB", "WR": "WR", "LWR": "WR", "RWR": "WR", "SWR": "WR",
    "TE": "TE", "LT": "OL", "LG": "OL", "C": "OL", "RG": "OL", "RT": "OL", "G": "OL", "T": "OL", "OL": "OL",
    "LDE": "DL", "RDE": "DL", "DE": "DL", "LDT": "DL", "RDT": "DL", "DT": "DL", "NT": "DL", "DL": "DL",
    "EDGE": "DL", "LEO": "DL",
    "WLB": "LB", "MLB": "LB", "SLB": "LB", "LILB": "LB", "RILB": "LB", "LOLB": "LB", "ROLB": "LB",
    "OLB": "LB", "ILB": "LB", "LB": "LB", "WILL": "LB", "MIKE": "LB", "SAM": "LB",
    "LCB": "CB", "RCB": "CB", "NB": "CB", "CB": "CB", "DB": "CB",
    "SS": "S", "FS": "S", "S": "S",
    "PK": "ST", "K": "ST", "P": "ST", "LS": "ST", "H": "ST", "PR": "ST", "KR": "ST",
}

# Injury formula (Section 9) - shrunk base points by position.
BASE_POS = {"WR": -2.0, "CB": -1.0, "DL": -1.25, "LB": -1.25, "ST": -1.0,
            "OL": 0.0, "S": 0.0, "RB": 0.0, "TE": 0.0}
RELIANCE_MEDIAN = {"WR": 0.23, "TE": 0.23, "RB": 0.49, "QB": 1.0,
                   "CB": 0.09, "S": 0.09, "DL": 0.09, "LB": 0.09, "ST": None, "OL": None}


def espn_abbr(a):
    a = (a or "").upper()
    return NFLVERSE_TO_ESPN.get(a, a)

OVERRIDES = os.path.join(STATE, "overrides.json")
try:
    import json as _json
    with open(OVERRIDES) as _f:
        BASE_POS.update((_json.load(_f) or {}).get("basePos", {}))
except Exception:
    pass
