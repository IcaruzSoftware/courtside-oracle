"""
NBA CDN client — schedule + live box scores from cdn.nba.com.

No proxies, no stats.nba.com. This is the read path the daily GitHub Actions
pipeline uses: it needs only the public NBA CDN, which is reachable from a plain
runner as long as the request carries a current browser-like header set (see
CDN_HEADERS). nba_api's own live header set is outdated and now gets a 403 from the
cdn.nba.com Akamai edge, so we send our own verified header constant instead.

Endpoints
---------
  schedule   https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json
  box score  https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{gameId}.json

CDN box scores exist from the 2019-20 season onward; older game IDs return 403.

Game-ID prefixes (first 3 chars of the 10-digit id):
  001 preseason   002 regular season   003 all-star
  004 playoffs    005 play-in          006 NBA Cup final
"""

import json
import logging
import os

import requests

logger = logging.getLogger(__name__)

# Offline/testing seam: if set, the schedule is read from this local JSON file
# instead of the live CDN (same shape as scheduleLeagueV2.json).
SCHEDULE_ENV = "COURTSIDE_SCHEDULE_JSON"

SCHEDULE_URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"
BOXSCORE_URL = "https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json"

_TIMEOUT = 30

# Verified header set for cdn.nba.com's Akamai edge (returns 200). nba_api's live
# header set is outdated (Chrome/87 UA, Accept: text/html, Cache-Control: max-age=0)
# and now gets a 403 here; this browser-like set works. Host is set by requests.
CDN_HEADERS = {
    "Accept":           "application/json, text/plain, */*",
    "Accept-Encoding":  "gzip, deflate, br",
    "Accept-Language":  "en-US,en;q=0.9",
    "Cache-Control":    "no-cache",
    "Connection":       "keep-alive",
    "Origin":           "https://www.nba.com",
    "Pragma":           "no-cache",
    "Referer":          "https://www.nba.com/",
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Fetch-Dest":   "empty",
    "Sec-Fetch-Mode":   "cors",
    "Sec-Fetch-Site":   "same-site",
    "User-Agent":       "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
}

# Game-type prefixes ---------------------------------------------------------
PRESEASON_PREFIX = "001"
ALLSTAR_PREFIX   = "003"
# Games that carry a real, ELO-relevant box score and can be predicted:
# regular season, playoffs, play-in, NBA Cup final. Preseason and all-star excluded.
STATEFUL_PREFIXES = {"002", "004", "005", "006"}

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    """A cached Session carrying the verified cdn.nba.com browser header set."""
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update(CDN_HEADERS)
        _session = s
    return _session


# ---------------------------------------------------------------------------
# Game-type helpers
# ---------------------------------------------------------------------------

def game_prefix(game_id: str) -> str:
    """Return the 3-digit game-type prefix (first 3 chars of the 10-digit ID),
    e.g. 0042500405 -> '004' (playoffs), 0022300001 -> '002' (regular season)."""
    gid = str(game_id).zfill(10)
    return gid[:3]


def is_preseason(game_id: str) -> bool:
    return game_prefix(game_id) == PRESEASON_PREFIX


def is_all_star(game_id: str) -> bool:
    return game_prefix(game_id) == ALLSTAR_PREFIX


def is_stateful(game_id: str) -> bool:
    """True for regular season / playoffs / play-in / Cup final — games that update ELO."""
    return game_prefix(game_id) in STATEFUL_PREFIXES


# ---------------------------------------------------------------------------
# Team tricode <-> team id
# ---------------------------------------------------------------------------

_tricode_to_id: dict[str, int] | None = None
_id_to_tricode: dict[int, str] | None = None


def _load_team_maps() -> None:
    global _tricode_to_id, _id_to_tricode
    if _tricode_to_id is not None:
        return
    from nba_api.stats.static import teams as _teams

    _tricode_to_id = {}
    _id_to_tricode = {}
    for t in _teams.get_teams():
        _tricode_to_id[t["abbreviation"].upper()] = int(t["id"])
        _id_to_tricode[int(t["id"])] = t["abbreviation"].upper()


def tricode_to_id(tricode: str) -> int:
    _load_team_maps()
    return _tricode_to_id[str(tricode).upper()]


def id_to_tricode(team_id) -> str:
    _load_team_maps()
    return _id_to_tricode[int(team_id)]


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

def fetch_schedule() -> dict:
    """Fetch the full league schedule JSON. Raises on HTTP error.

    Honours the COURTSIDE_SCHEDULE_JSON env var (offline/testing) — when set, the
    schedule is read from that local file instead of the live CDN.
    """
    override = os.environ.get(SCHEDULE_ENV)
    if override:
        logger.info("Reading schedule from %s (%s)", override, SCHEDULE_ENV)
        with open(override, encoding="utf-8") as f:
            return json.load(f)
    resp = _get_session().get(SCHEDULE_URL, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _parse_schedule_date(raw: str) -> str:
    """Parse a scheduleLeagueV2 gameDate ('MM/DD/YYYY HH:MM:SS') to ISO 'YYYY-MM-DD'."""
    mmddyyyy = raw.split(" ")[0]
    m, d, y = mmddyyyy.split("/")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def games_for_date(et_date: str, schedule: dict | None = None) -> list[dict]:
    """
    Return the games scheduled on a given ET calendar date.

    Args:
        et_date:   ISO date string 'YYYY-MM-DD' (Eastern-time game date).
        schedule:  Pre-fetched schedule dict (fetched if None).

    Returns a list of dicts, one per game:
        game_id, game_time_utc, game_status (1=scheduled, 2=live, 3=final),
        home_team_id, home_tricode, away_team_id, away_tricode,
        home_score, away_score
    """
    if schedule is None:
        schedule = fetch_schedule()

    out: list[dict] = []
    for day in schedule.get("leagueSchedule", {}).get("gameDates", []):
        if _parse_schedule_date(day.get("gameDate", "")) != et_date:
            continue
        for g in day.get("games", []):
            home = g.get("homeTeam", {})
            away = g.get("awayTeam", {})
            out.append({
                "game_id":       str(g["gameId"]).zfill(10),
                "game_time_utc": g.get("gameDateTimeUTC"),
                "game_status":   g.get("gameStatus"),
                "home_team_id":  int(home.get("teamId", 0)),
                "home_tricode":  home.get("teamTricode"),
                "away_team_id":  int(away.get("teamId", 0)),
                "away_tricode":  away.get("teamTricode"),
                "home_score":    home.get("score"),
                "away_score":    away.get("score"),
            })
    return out


# ---------------------------------------------------------------------------
# Box score
# ---------------------------------------------------------------------------

def fetch_boxscore(game_id: str) -> dict | None:
    """
    Fetch one game's live box score. Returns the ``game`` sub-dict, or None when the
    box score does not exist yet (HTTP 404 — a scheduled/not-yet-played game).

    A 403 is Akamai "Access Denied": the daily pipeline only ever fetches games from
    2019-20 onward (which all have box scores), so a 403 means the CDN is blocking
    this client (e.g. GitHub runners). That must fail the run loudly rather than be
    swallowed as "not available", so it is raised.
    """
    gid = str(game_id).zfill(10)
    url = BOXSCORE_URL.format(game_id=gid)
    resp = _get_session().get(url, timeout=_TIMEOUT)
    if resp.status_code == 404:
        logger.info("boxscore %s not available yet (HTTP 404)", gid)
        return None
    if resp.status_code != 200:
        raise RuntimeError(
            f"CDN box score {gid} returned HTTP {resp.status_code} — cdn.nba.com is "
            f"blocking this client (403 = Access Denied)."
        )
    try:
        return resp.json().get("game")
    except ValueError:
        raise RuntimeError(f"CDN box score {gid}: invalid JSON response")
