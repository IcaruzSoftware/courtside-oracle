"""
Post to Instagram: two post types per ET date D, one 1080x1350 slide per game.

    record       posted first: all-time running record slide + one result slide per
                 game of D-1 (final score from the CDN, our pick, CORRECT/WRONG)
    predictions  one slide per predicted game of D

Usage:
    python src/scripts/post_instagram.py                          # D = today (ET)
    python src/scripts/post_instagram.py --date 2026-10-21
    python src/scripts/post_instagram.py --render-only --date 2026-10-21   # PNGs only

Reads Supabase (and CDN box scores for the record post), renders the slides as static
HTML -> headless Chrome screenshot, uploads JPEGs to the public Supabase Storage bucket
`instagram`, and publishes them via the Instagram Graph API.
1 slide -> single-image post; 2+ -> carousel (capped at 10, see MAX_ITEMS).
Games are ordered by popularity (see POPULARITY), not by tip-off.

The record post is skipped (no claim row) unless every D-1 prediction is resolved,
so a later re-run can still post it; a postponed game blocks that day's record post.

Idempotent: a claim row in `instagram_posts` (one per date and kind) is inserted
before publishing, so a re-run or a concurrent run never double-posts.

Required environment variables:
    SUPABASE_URL, SUPABASE_KEY      (--render-only: the read-only anon key is enough)
    IG_ACCESS_TOKEN, IG_USER_ID     (not needed for --render-only; if missing, the
                                     script logs and exits 0 without doing anything)
    NBA_PROXIES                     (optional, CDN box scores; see nba_cdn.py)
"""

import argparse
import html
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date as Date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("post_instagram")

from pipeline.daily_state import _today_et
from pipeline.evaluate import _get_supabase
from pipeline.nba_cdn import fetch_boxscore

GRAPH = "https://graph.facebook.com/v23.0"
ET = ZoneInfo("America/New_York")
BUCKET = "instagram"
# Instagram carousels hold at most 10 items. When posting, predictions keep the first
# 10 games in popularity order, the record post the record slide + the first 9 games;
# the caption lists only the posted games. --render-only renders everything.
MAX_ITEMS = 10
BACKTEST_ACCURACY = "67.5%"   # hardcoded, same as web/app/(main)/page.tsx
SITE = "courtside-oracle.gerritvisser.de"
HASHTAGS = "#NBA #NBAPicks #NBAPredictions #Basketball #MachineLearning #SportsAnalytics"
PRED_COLS = "game_id,game_time_utc,home_team,away_team,predicted_team,confidence"
CHROME_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

TEAMS = {  # tricode: (nickname, primary color)
    "ATL": ("Hawks", "#E03A3E"),        "BOS": ("Celtics", "#007A33"),
    "BKN": ("Nets", "#000000"),         "CHA": ("Hornets", "#1D1160"),
    "CHI": ("Bulls", "#CE1141"),        "CLE": ("Cavaliers", "#860038"),
    "DAL": ("Mavericks", "#00538C"),    "DEN": ("Nuggets", "#0E2240"),
    "DET": ("Pistons", "#C8102E"),      "GSW": ("Warriors", "#1D428A"),
    "HOU": ("Rockets", "#CE1141"),      "IND": ("Pacers", "#002D62"),
    "LAC": ("Clippers", "#C8102E"),     "LAL": ("Lakers", "#552583"),
    "MEM": ("Grizzlies", "#5D76A9"),    "MIA": ("Heat", "#98002E"),
    "MIL": ("Bucks", "#00471B"),        "MIN": ("Timberwolves", "#0C2340"),
    "NOP": ("Pelicans", "#0C2340"),     "NYK": ("Knicks", "#006BB6"),
    "OKC": ("Thunder", "#007AC1"),      "ORL": ("Magic", "#0077C0"),
    "PHI": ("76ers", "#006BB6"),        "PHX": ("Suns", "#1D1160"),
    "POR": ("Trail Blazers", "#E03A3E"), "SAC": ("Kings", "#5A2D81"),
    "SAS": ("Spurs", "#C4CED4"),        "TOR": ("Raptors", "#CE1141"),
    "UTA": ("Jazz", "#002B5C"),         "WAS": ("Wizards", "#002B5C"),
}

# ponytail: fixed social-following ranking (index = rank, lower = more popular);
# upgrade path = national-TV flag from the CDN schedule.
POPULARITY = ["LAL", "GSW", "BOS", "NYK", "CHI", "MIA", "PHI", "LAC", "DAL", "MIL",
              "PHX", "DEN", "OKC", "BKN", "TOR", "CLE", "HOU", "SAS", "ATL", "MEM",
              "MIN", "NOP", "POR", "SAC", "IND", "DET", "ORL", "CHA", "UTA", "WAS"]

# ---------------------------------------------------------------------------
# Slides (pure: data -> HTML strings)
# ---------------------------------------------------------------------------

# Inter (latin subset, variable 100-900) vendored next to this script: a Google
# Fonts <link> sometimes lost the race against Chrome's --virtual-time-budget and
# the slide fell back to DejaVu Sans. OFL licence: fonts/OFL.txt.
FONT_FACE = ("@font-face{font-family:Inter;font-weight:100 900;font-display:block;"
             f"src:url('{(Path(__file__).parent / 'fonts' / 'Inter-latin.woff2').as_uri()}') format('woff2')}}")

CSS = """
*{box-sizing:border-box;margin:0}
html,body{width:1080px;height:1350px;overflow:hidden}
body{background:#080808;background-image:radial-gradient(circle at 85% 0%,rgba(34,197,94,.14),transparent 45%),radial-gradient(circle at 0% 100%,rgba(234,88,12,.10),transparent 40%);
  color:#fff;font-family:Inter,"DejaVu Sans",sans-serif;display:flex;flex-direction:column;padding:72px 72px 64px;line-height:normal}
.brand{display:flex;align-items:center;gap:18px;font-size:30px;font-weight:800;letter-spacing:.04em}
.g{color:#22c55e}
.kicker{margin-top:40px;font-size:26px;font-weight:800;letter-spacing:.18em;color:#ea580c;white-space:nowrap}
h1{margin-top:14px;font-size:92px;font-weight:900;line-height:1;letter-spacing:-.02em;white-space:nowrap}
.sub{margin-top:18px;font-size:28px;color:#9ca3af}
.main{flex:1;display:flex;flex-direction:column;justify-content:center}
.card{background:#111;border:1px solid #2a2a2a}
.row{display:flex;align-items:center;justify-content:space-between}
.dot{display:inline-block;flex:none;border-radius:50%;border:1px solid #3a3a3a}
.lbl{margin-top:12px;font-size:26px;font-weight:800;letter-spacing:.18em;color:#6b7280}
footer{margin-top:auto;display:flex;align-items:flex-end;justify-content:space-between;padding-top:26px;border-top:1px solid #2a2a2a}
.stats{display:flex;gap:48px}
.stats b{display:block;font-size:40px;font-weight:900}
.stats span{font-size:20px;letter-spacing:.06em;color:#6b7280}
.url{margin-left:auto;text-align:right;font-weight:600;font-size:22px;color:#9ca3af}
"""

BALL = ('<svg width="40" height="40" viewBox="0 0 40 40"><circle cx="20" cy="20" r="18" fill="#ea580c"/>'
        '<g fill="none" stroke="#1c1917" stroke-width="2"><circle cx="20" cy="20" r="18"/>'
        '<path d="M2 20h36M20 2v36M8 7c6 6 6 20 0 26M32 7c-6 6-6 20 0 26"/></g></svg>')
# Inline SVG, not font glyphs: glyph coverage for ✓/✗ on the CI runner is uncertain.
VERDICT = {True: ("CORRECT", "#22c55e", "M4 12.5l5 5L20 6.5"),
           False: ("WRONG", "#ef4444", "M6 6l12 12M18 6L6 18")}
URL_HTML = '<div class="url">courtside-oracle<br>.gerritvisser.de</div>'

e = html.escape


def _rank(tricode: str) -> int:
    return POPULARITY.index(tricode) if tricode in POPULARITY else len(POPULARITY)


def _order(preds: list[dict]) -> list[dict]:
    """Most popular game first; tip-off, then game id break ties."""
    return sorted(preds, key=lambda p: (_rank(p["home_team"]) + _rank(p["away_team"]),
                                        p.get("game_time_utc") or "", p["game_id"]))


def _day(date: str, fmt: str = "%a, %b %-d, %Y") -> str:
    return f"{Date.fromisoformat(date):{fmt}}"


def _loser(p: dict) -> str:
    return p["home_team"] if p["predicted_team"] == p["away_team"] else p["away_team"]


def _pct(p: dict) -> int:
    return round(float(p["confidence"]) * 100)


def team_mark(tricode: str, size: float) -> str:
    """Team marker: a dot in the team's primary color. Swap for a logo <img> here."""
    color = TEAMS.get(tricode, ("", "#6b7280"))[1]
    return f'<span class="dot" style="width:{size:.0f}px;height:{size:.0f}px;background:{color}"></span>'


def _tip_et(p: dict) -> str:
    tip = p.get("game_time_utc")
    if not tip:
        return ""
    t = datetime.fromisoformat(tip).astimezone(ET)
    return f"{t:%I:%M %p}".lstrip("0") + " ET"


# The opener's PickCard scaled up to fill the slide: sizes x1.8, vertical spacing x2.5.
def _u(px):
    return f"{px * 1.8:.1f}px"


def _v(px):
    return f"{px * 2.5:.1f}px"


def _matchup(p: dict, bold: str, right: str, scores: dict | None = None) -> str:
    """Away @ home row with team dots; `bold` team in white, optional final scores."""
    def side(t):
        style = "color:#fff;font-weight:800" if t == bold else ""
        score = f" {scores[t]}" if scores else ""
        return f'{team_mark(t, 32 * 1.8)}<span style="{style}">{e(t)}{score}</span>'
    return f"""
  <div class="row">
    <div style="display:flex;align-items:center;gap:{_u(16)};font-size:{_u(26)};font-weight:600;color:#9ca3af;white-space:nowrap">
      {side(p["away_team"])} @ {side(p["home_team"])}</div>
    <div style="font-size:{_u(22)};font-weight:600;color:#6b7280">{e(right)}</div>
  </div>"""


def _bar(p: dict) -> str:
    """Split confidence bar with the 50% marker and the two percentages under it."""
    win, lose, pct = p["predicted_team"], _loser(p), _pct(p)
    return f"""
  <div style="position:relative;display:flex;justify-content:space-between;margin-top:{_v(18)};height:{_u(14)};gap:{_u(4)}">
    <div style="width:{pct}%;border-radius:{_u(7)};background:linear-gradient(to right,#16a34a,#22c55e)"></div>
    <div style="width:{100 - pct}%;border-radius:{_u(7)};background:#3a3a3a"></div>
    <div class="marker" style="position:absolute;left:50%;top:{_u(-6)};bottom:{_u(-6)};width:{_u(2)};margin-left:{_u(-1)};background:#fff;opacity:.7"></div>
  </div>
  <div style="position:relative;display:flex;justify-content:space-between;margin-top:{_v(10)};font-size:{_u(20)};font-weight:600;color:#6b7280">
    <span style="color:#22c55e">{e(win)} {pct}%</span>
    <span style="position:absolute;left:50%;transform:translateX(-50%);color:#4b5563">50%</span>
    <span>{e(lose)} {100 - pct}%</span>
  </div>"""


def _card(p: dict) -> str:
    """Prediction card: matchup + tip-off, big pick name + %, split bar."""
    win, pct = p["predicted_team"], _pct(p)
    name = TEAMS.get(win, (win,))[0]
    # ponytail: width estimate (~0.6 em/char); shrinks only 12+ char names (Timberwolves, Trail Blazers)
    name_px = min(44 * 1.8, 540 / (0.6 * len(name)))
    return f"""
<div class="card" style="border-radius:{_u(22)};padding:{_v(24)} {_u(34)}">{_matchup(p, win, _tip_et(p))}
  <div class="row" style="align-items:flex-end;margin-top:{_v(10)};gap:{_u(16)}">
    <div style="font-size:{name_px:.1f}px;font-weight:900;line-height:1.1;white-space:nowrap">{e(name)}</div>
    <div style="text-align:right;line-height:1"><div style="font-size:{_u(52)};font-weight:900;color:#22c55e">{pct}%</div>
      <div style="font-size:{_u(22)};font-weight:600;color:#6b7280">confidence</div></div>
  </div>{_bar(p)}
</div>"""


def _result_card(g: dict) -> str:
    """Result card: matchup + final score, our pick + bar, then a big verdict badge."""
    home, away = g["home_team"], g["away_team"]
    winner = home if g["home_score"] > g["away_score"] else away
    pick = f"Our pick: {TEAMS.get(g['predicted_team'], (g['predicted_team'],))[0]} · {_pct(g)}%"
    pick_px = min(54, 760 / (0.6 * len(pick)))
    label, color, path = VERDICT[bool(g["correct"])]
    return f"""
<div class="card" style="border-radius:{_u(22)};padding:{_v(24)} {_u(34)}">{_matchup(g, winner, "FINAL", {home: g["home_score"], away: g["away_score"]})}
  <div style="margin-top:{_v(14)};font-size:{pick_px:.1f}px;font-weight:800;white-space:nowrap">{e(pick)}</div>{_bar(g)}
</div>
<div class="verdict" style="margin-top:64px;align-self:center;display:flex;align-items:center;gap:28px;padding:26px 64px 26px 52px;border-radius:999px;border:4px solid {color};background:{color}1f;color:{color};font-size:88px;font-weight:900;letter-spacing:.04em;line-height:1">
  <svg width="96" height="96" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="{path}"/></svg>{label}</div>"""


def _page(kicker: str, title: str, main: str, footer: str, sub: str = "") -> str:
    sub = f'<div class="sub">{e(sub)}</div>' if sub else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<style>{FONT_FACE}{CSS}</style></head><body>
<div class="brand">{BALL}<span>COURTSIDE <span class="g">ORACLE</span></span></div>
<div class="kicker">{e(kicker.upper())}</div>
<h1>{e(title)}</h1>
{sub}
<div class="main">{main}</div>
<footer>{footer}</footer>
</body></html>"""


def prediction_slides(games: list[dict], date: str, record: tuple | None) -> list[str]:
    """One 1080x1350 HTML document per game of `games` (already ordered/capped)."""
    stats = f"<div><b>{BACKTEST_ACCURACY}</b><span>BACKTEST ACCURACY</span></div>"
    if record:
        stats += f"<div><b>{record[0]}–{record[1]}</b><span>RECORD</span></div>"
    footer = f'<div class="stats">{stats}</div>{URL_HTML}'
    return [_page(f"Today's prediction · {_day(date)}", f"Game {i} of {len(games)}", _card(p), footer,
                  "Machine-learning prediction, locked in before tip-off.")
            for i, p in enumerate(games, 1)]


def record_slides(games: list[dict], date: str, record: tuple, night: tuple) -> list[str]:
    """Running-record slide, then one result slide per game of D-1 (games carry scores)."""
    c, i, acc = record
    # ponytail: width estimate, digits ~0.68 em + dash ~0.5 em within ~840px (936 minus gaps)
    num_px = min(280, 840 / (0.68 * len(f"{c}{i}") + 0.5))
    num = f"font-size:{num_px:.0f}px;font-weight:900;line-height:1"
    main = f"""
<div style="display:flex;justify-content:center;align-items:flex-start;gap:48px;text-align:center">
  <div><div style="{num}">{c}</div><div class="lbl">CORRECT</div></div>
  <div style="{num};color:#4b5563">–</div>
  <div><div style="{num}">{i}</div><div class="lbl">INCORRECT</div></div>
</div>
<div style="margin-top:64px;text-align:center;font-size:64px;font-weight:900;color:#22c55e">{acc} accuracy</div>
<div style="margin-top:28px;text-align:center;font-size:42px;font-weight:700;color:#9ca3af">Last night: {night[0]}–{night[1]}</div>"""
    prev = (Date.fromisoformat(date) - timedelta(days=1)).isoformat()
    return [_page(f"Running record · {_day(date)}", "All-time record", main, URL_HTML)] + [
        _page(f"Last night's result · {_day(prev)}", f"Game {n} of {len(games)}", _result_card(g), URL_HTML)
        for n, g in enumerate(games, 1)]


def prediction_caption(games: list[dict], date: str) -> str:
    swipe = f" Swipe through all {len(games)} →" if len(games) > 1 else ""
    return "\n".join([f"Today's NBA predictions 🏀 {_day(date, '%a, %b %-d')}", ""]
                     + [f"{p['predicted_team']} over {_loser(p)} · {_pct(p)}%" for p in games]
                     + ["", f"Our machine-learning model picks every game, locked in before tip-off.{swipe}",
                        f"Full picks + live record: {SITE}", "", HASHTAGS])


def record_caption(games: list[dict], record: tuple, night: tuple) -> str:
    lines = [f"Last night: {night[0]}–{night[1]}{' ✅' if night[0] >= night[1] else ''}"
             f" · All-time: {record[0]}–{record[1]} ({record[2]})", ""]
    for g in games:
        hi, lo = sorted((g["home_score"], g["away_score"]), reverse=True)
        pick = f"{g['predicted_team']} over {_loser(g)}"
        if g["correct"]:
            lines.append(f"✅ {pick} · {hi}–{lo}")
        else:
            lines.append(f"❌ {pick} · {_loser(g)} won {hi}–{lo}")
    return "\n".join(lines + ["", "Every pick goes public before tip-off and gets graded the next morning.",
                              SITE, "", HASHTAGS])


# ---------------------------------------------------------------------------
# Render: HTML -> headless Chrome PNG -> PNG/JPEG
# ---------------------------------------------------------------------------

def render(htmls: list[str], out_dir: Path, fmt: str = "JPEG") -> list[Path]:
    """Screenshot each document; save as `fmt` ("JPEG" for posting, "PNG" for --render-only)."""
    from PIL import Image

    chrome = next((shutil.which(c) for c in ("google-chrome", "chromium", "chromium-browser")
                   if shutil.which(c)), None)
    if not chrome:
        raise RuntimeError("No Chrome/Chromium found (google-chrome, chromium, chromium-browser).")
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, doc in enumerate(htmls, 1):
            src, png = Path(tmp) / f"{i}.html", Path(tmp) / f"{i}.png"
            src.write_text(doc, encoding="utf-8")
            for attempt in range(3):   # headless Chrome occasionally hangs; a slide takes ~1 s
                try:
                    subprocess.run(
                        [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                         "--force-device-scale-factor=1", "--window-size=1080,1350",
                         "--virtual-time-budget=10000", f"--user-agent={CHROME_UA}",
                         # fresh profile per attempt: a killed Chrome can leave its profile locked
                         f"--user-data-dir={tmp}/profile{attempt}", f"--screenshot={png}", src.as_uri()],
                        check=True, timeout=30, capture_output=True,
                    )
                    break
                except subprocess.TimeoutExpired:
                    if attempt == 2:
                        raise
                    logger.warning("Chrome timed out on slide %d, retrying.", i)
            dst = out_dir / f"{i}.{'png' if fmt == 'PNG' else 'jpg'}"
            with Image.open(png) as im:
                if im.size != (1080, 1350):
                    raise RuntimeError(f"Chrome rendered {im.size}, expected (1080, 1350).")
                im.convert("RGB").save(dst, fmt, quality=92)
            paths.append(dst)
    return paths


# ---------------------------------------------------------------------------
# Instagram Graph API
# ---------------------------------------------------------------------------

def _graph(session, method: str, path: str, **kwargs) -> dict:
    r = session.request(method, f"{GRAPH}/{path}", timeout=30, **kwargs)
    if not r.ok:
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = r.text[:300]
        raise RuntimeError(f"Graph API {method} {path.split('?')[0]} failed ({r.status_code}): {msg}")
    return r.json()


def publish(session, ig_user_id: str, image_urls: list[str], caption: str) -> str:
    """Publish one image, or a carousel for 2+, and return the IG media id."""
    if len(image_urls) == 1:
        container = _graph(session, "POST", f"{ig_user_id}/media",
                           data={"image_url": image_urls[0], "caption": caption})["id"]
    else:
        children = [_graph(session, "POST", f"{ig_user_id}/media",
                           data={"image_url": url, "is_carousel_item": "true"})["id"]
                    for url in image_urls]
        container = _graph(session, "POST", f"{ig_user_id}/media",
                           data={"media_type": "CAROUSEL", "children": ",".join(children),
                                 "caption": caption})["id"]
    for _ in range(20):   # ~60 s
        status = _graph(session, "GET", container, params={"fields": "status_code"}).get("status_code")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Media container {container} status {status}.")
        time.sleep(3)
    else:
        raise RuntimeError(f"Media container {container} not ready after 60 s.")
    try:
        return _graph(session, "POST", f"{ig_user_id}/media_publish", data={"creation_id": container})["id"]
    except Exception as exc:
        raise PublishUncertain(f"media_publish failed, the post may still have gone out: {exc}") from exc


class PublishUncertain(RuntimeError):
    """media_publish failed (e.g. timed out) — Instagram may have published anyway."""


def _upload(db, prefix: str, paths: list[Path]) -> list[str]:
    bucket = db.storage.from_(BUCKET)
    urls = []
    for p in paths:
        key = f"{prefix}/{p.name}"
        bucket.upload(key, p.read_bytes(), {"content-type": "image/jpeg", "upsert": "true"})
        urls.append(bucket.get_public_url(key))
    return urls


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _record(db) -> tuple | None:
    """All-time (correct, incorrect, "75.0%") from running_record — what the site shows."""
    rows = db.table("running_record").select("total_correct,total_incorrect,accuracy").eq("id", 1).execute().data
    if not rows:
        return None
    c, i, acc = rows[0]["total_correct"], rows[0]["total_incorrect"], rows[0].get("accuracy")
    acc = float(acc) if acc is not None else (c / (c + i) if c + i else 0.0)
    return c, i, f"{acc * 100:.1f}%"


def _build(db, kind: str, date: str, cap: int | None) -> tuple[list[str], str] | None:
    """(slides, caption) for one post type, or None when there is nothing to post."""
    if kind == "predictions":
        games = _order(db.table("predictions").select(PRED_COLS).eq("game_date", date).execute().data or [])
        if not games:
            logger.info("No predictions for %s — no predictions post.", date)
            return None
        games = games[:cap]
        return prediction_slides(games, date, _record(db)), prediction_caption(games, date)

    prev = (Date.fromisoformat(date) - timedelta(days=1)).isoformat()
    games = _order(db.table("predictions").select(PRED_COLS + ",actual_winner,correct")
                   .eq("game_date", prev).execute().data or [])
    if not games or any(g.get("correct") is None for g in games):
        logger.info("%s has no predictions or unresolved ones — no record post yet.", prev)
        return None
    record = _record(db)
    if not record:
        raise RuntimeError("running_record row id=1 missing.")
    night = (sum(bool(g["correct"]) for g in games), sum(not g["correct"] for g in games))
    games = games[:cap]
    for g in games:   # never a guessed score: final box score or fail
        box = fetch_boxscore(g["game_id"])
        if not box or box.get("gameStatus") != 3:
            raise RuntimeError(f"No final box score for {g['game_id']} — not rendering a guessed score.")
        g["home_score"], g["away_score"] = box["homeTeam"]["score"], box["awayTeam"]["score"]
    return record_slides(games, date, record, night), record_caption(games, record, night)


def _post(db, kind: str, date: str, render_only: bool, out: str, token: str, ig_user_id: str) -> None:
    def claim(q):
        return q.eq("post_date", date).eq("kind", kind)

    if not render_only and claim(db.table("instagram_posts").select("post_date")).execute().data:
        logger.info("Already posted %s for %s — skipping.", kind, date)
        return
    cap = None if render_only else MAX_ITEMS - (kind == "record")   # record slide takes one item
    built = _build(db, kind, date, cap)
    if not built:
        return
    slides, caption = built
    out_dir = Path(out) / f"{kind}-{date}"
    paths = render(slides, out_dir, "PNG" if render_only else "JPEG")
    (out_dir / "caption.txt").write_text(caption, encoding="utf-8")
    if render_only:
        print(f"{out_dir}: {len(paths)} slide(s)\n{caption}\n")
        return

    # Claim (date, kind) first: the PK makes a concurrent run's insert fail -> no double post.
    db.table("instagram_posts").insert({"post_date": date, "kind": kind}).execute()
    try:
        import requests
        session = requests.Session()
        session.headers["Authorization"] = f"Bearer {token}"
        media_id = publish(session, ig_user_id, _upload(db, f"{date}/{kind}", paths), caption)
    except PublishUncertain:
        # Keep the claim: a retry could double-post. Check the account, then delete
        # the instagram_posts row by hand if it really didn't post.
        raise
    except Exception:
        claim(db.table("instagram_posts").delete()).execute()
        raise
    # A crash before this line leaves the claim row: later runs skip (never double-post).
    claim(db.table("instagram_posts").update({"media_id": media_id})).execute()
    logger.info("Posted %s: %d slide(s) for %s, media %s", kind, len(paths), date, media_id)


def run(date: str | None = None, render_only: bool = False, out: str = "instagram-out") -> None:
    date = date or _today_et()
    token, ig_user_id = os.environ.get("IG_ACCESS_TOKEN"), os.environ.get("IG_USER_ID")
    if not render_only and not (token and ig_user_id):
        logger.info("Instagram secrets not set — skipping.")
        return

    db = _get_supabase()
    failed = []
    for kind in ("record", "predictions"):   # independent: one failing never blocks the other
        try:
            _post(db, kind, date, render_only, out, token, ig_user_id)
        except Exception:
            logger.exception("%s post for %s failed.", kind, date)
            failed.append(kind)
    if failed:
        raise RuntimeError(f"Instagram post(s) failed for {date}: {', '.join(failed)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date",        help="ET date YYYY-MM-DD (default: today)")
    parser.add_argument("--render-only", action="store_true",
                        help="Write PNGs + caption.txt only; no upload/post/table writes")
    parser.add_argument("--out",         default="instagram-out", help="Output dir for the slides")
    args = parser.parse_args()
    run(args.date, args.render_only, args.out)


if __name__ == "__main__":
    main()
