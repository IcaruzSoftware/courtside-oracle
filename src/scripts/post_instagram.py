"""
Post today's picks to Instagram: one 1080x1350 slide per game.

Usage:
    python src/scripts/post_instagram.py                          # today (ET)
    python src/scripts/post_instagram.py --date 2026-10-21
    python src/scripts/post_instagram.py --dry-run --date 2026-10-21   # render only

Reads the day's predictions from Supabase, renders one slide per game as static
HTML -> headless Chrome screenshot -> JPEG, uploads the JPEGs to the public
Supabase Storage bucket `instagram`, and publishes them via the Instagram Graph API.
1 game -> single-image post; 2+ games -> carousel (capped at 10, see MAX_ITEMS).

Idempotent: a claim row in `instagram_posts` (one per date) is inserted before
publishing, so a re-run or a concurrent run never double-posts.

Required environment variables:
    SUPABASE_URL, SUPABASE_KEY      (--dry-run: the read-only anon key is enough)
    IG_ACCESS_TOKEN, IG_USER_ID     (not needed for --dry-run; if missing, the
                                     script logs and exits 0 without doing anything)
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
from datetime import date as Date, datetime
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

GRAPH = "https://graph.facebook.com/v23.0"
ET = ZoneInfo("America/New_York")
BUCKET = "instagram"
# Instagram carousels hold at most 10 items: with more than 10 games, only the
# first 10 by tip-off time are posted (slides and caption alike).
MAX_ITEMS = 10
BACKTEST_ACCURACY = "67.5%"   # hardcoded, same as web/app/(main)/page.tsx
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

# ---------------------------------------------------------------------------
# Slides (pure: data -> HTML strings)
# ---------------------------------------------------------------------------

CSS = """
*{box-sizing:border-box;margin:0}
html,body{width:1080px;height:1350px;overflow:hidden}
body{background:#080808;background-image:radial-gradient(circle at 85% 0%,rgba(34,197,94,.14),transparent 45%),radial-gradient(circle at 0% 100%,rgba(234,88,12,.10),transparent 40%);
  color:#fff;font-family:Inter,"DejaVu Sans",sans-serif;display:flex;flex-direction:column;padding:72px 72px 64px;line-height:normal}
.brand{display:flex;align-items:center;gap:18px;font-size:30px;font-weight:800;letter-spacing:.04em}
.page{margin-left:auto;font-size:24px;font-weight:600;letter-spacing:.06em;color:#6b7280}
.g{color:#22c55e}
.kicker{margin-top:40px;font-size:26px;font-weight:800;letter-spacing:.18em;color:#ea580c;white-space:nowrap}
h1{margin-top:14px;font-size:92px;font-weight:900;line-height:1;letter-spacing:-.02em;white-space:nowrap}
.sub{margin-top:18px;font-size:28px;color:#9ca3af}
.main{flex:1;display:flex;flex-direction:column;justify-content:center}
.card{background:#111;border:1px solid #2a2a2a}
.row{display:flex;align-items:center;justify-content:space-between}
.dot{display:inline-block;flex:none;border-radius:50%;border:1px solid #3a3a3a}
footer{margin-top:auto;display:flex;align-items:flex-end;justify-content:space-between;padding-top:26px;border-top:1px solid #2a2a2a}
.stats{display:flex;gap:48px}
.stats b{display:block;font-size:40px;font-weight:900}
.stats span{font-size:20px;letter-spacing:.06em;color:#6b7280}
.url{text-align:right;font-weight:600;font-size:22px;color:#9ca3af}
"""

BALL = ('<svg width="40" height="40" viewBox="0 0 40 40"><circle cx="20" cy="20" r="18" fill="#ea580c"/>'
        '<g fill="none" stroke="#1c1917" stroke-width="2"><circle cx="20" cy="20" r="18"/>'
        '<path d="M2 20h36M20 2v36M8 7c6 6 6 20 0 26M32 7c-6 6-6 20 0 26"/></g></svg>')

e = html.escape


def _select(preds: list[dict]) -> list[dict]:
    """Sort by tip-off and cap at MAX_ITEMS — the games that get posted."""
    return sorted(preds, key=lambda p: (p.get("game_time_utc") or "", p["game_id"]))[:MAX_ITEMS]


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


def _card(p: dict) -> str:
    """The opener's PickCard at its final state, scaled up to fill the slide: sizes
    x1.8, vertical spacing x2.5, "confidence" under the % so long names fit."""
    def u(px):
        return f"{px * 1.8:.1f}px"

    def v(px):
        return f"{px * 2.5:.1f}px"
    win, home, away = p["predicted_team"], p["home_team"], p["away_team"]
    lose = home if win == away else away
    pct = round(float(p["confidence"]) * 100)
    name = TEAMS.get(win, (win,))[0]
    # ponytail: width estimate (~0.6 em/char); shrinks only 12+ char names (Timberwolves, Trail Blazers)
    name_px = min(44 * 1.8, 540 / (0.6 * len(name)))

    def tri(t):
        style = "color:#fff;font-weight:800" if t == win else ""
        return f'<span style="{style}">{e(t)}</span>'

    return f"""
<div class="card" style="border-radius:{u(22)};padding:{v(24)} {u(34)}">
  <div class="row">
    <div style="display:flex;align-items:center;gap:{u(16)};font-size:{u(26)};font-weight:600;color:#9ca3af">
      {team_mark(away, 32 * 1.8)}{tri(away)} @ {team_mark(home, 32 * 1.8)}{tri(home)}</div>
    <div style="font-size:{u(22)};font-weight:600;color:#6b7280">{e(_tip_et(p))}</div>
  </div>
  <div class="row" style="align-items:flex-end;margin-top:{v(10)};gap:{u(16)}">
    <div style="font-size:{name_px:.1f}px;font-weight:900;line-height:1.1;white-space:nowrap">{e(name)}</div>
    <div style="text-align:right;line-height:1"><div style="font-size:{u(52)};font-weight:900;color:#22c55e">{pct}%</div>
      <div style="font-size:{u(22)};font-weight:600;color:#6b7280">confidence</div></div>
  </div>
  <div style="position:relative;display:flex;justify-content:space-between;margin-top:{v(18)};height:{u(14)};gap:{u(4)}">
    <div style="width:{pct}%;border-radius:{u(7)};background:linear-gradient(to right,#16a34a,#22c55e)"></div>
    <div style="width:{100 - pct}%;border-radius:{u(7)};background:#3a3a3a"></div>
    <div class="marker" style="position:absolute;left:50%;top:{u(-6)};bottom:{u(-6)};width:{u(2)};margin-left:{u(-1)};background:#fff;opacity:.7"></div>
  </div>
  <div style="position:relative;display:flex;justify-content:space-between;margin-top:{v(10)};font-size:{u(20)};font-weight:600;color:#6b7280">
    <span style="color:#22c55e">{e(win)} {pct}%</span>
    <span style="position:absolute;left:50%;transform:translateX(-50%);color:#4b5563">50%</span>
    <span>{e(lose)} {100 - pct}%</span>
  </div>
</div>"""


def build_slides(preds: list[dict], date: str, record: tuple[int, int] | None) -> list[str]:
    """One complete 1080x1350 HTML document per posted game."""
    picks = _select(preds)
    kicker = f"DAILY PICKS · {Date.fromisoformat(date):%a, %b %-d, %Y}".upper()
    stats = f"<div><b>{BACKTEST_ACCURACY}</b><span>BACKTEST ACCURACY</span></div>"
    if record:
        stats += f"<div><b>{record[0]}–{record[1]}</b><span>RECORD</span></div>"
    slides = []
    for i, p in enumerate(picks, 1):
        page = f'<span class="page">{i} / {len(picks)}</span>' if len(picks) > 1 else ""
        slides.append(f"""<!doctype html>
<html><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400..900&display=block">
<style>{CSS}</style></head><body>
<div class="brand">{BALL}<span>COURTSIDE <span class="g">ORACLE</span></span>{page}</div>
<div class="kicker">{e(kicker)}</div>
<h1>Tonight&#x27;s picks</h1>
<div class="sub">Machine-learning predictions, locked in before tip-off.</div>
<div class="main">{_card(p)}</div>
<footer><div class="stats">{stats}</div><div class="url">courtside-oracle<br>.gerritvisser.de</div></footer>
</body></html>""")
    return slides


def build_caption(preds: list[dict], date: str) -> str:
    lines = [f"Tonight's picks · {Date.fromisoformat(date):%a, %b %-d} 🏀", ""]
    for p in _select(preds):
        win = p["predicted_team"]
        lose = p["home_team"] if win == p["away_team"] else p["away_team"]
        lines.append(f"{win} over {lose} · {round(float(p['confidence']) * 100)}%")
    lines += ["", "Machine-learning picks (per-player ELO + XGBoost), locked in before tip-off. "
              "Not betting advice.", "courtside-oracle.gerritvisser.de", "",
              "#NBA #NBAPicks #NBAPredictions #MachineLearning"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Render: HTML -> headless Chrome PNG -> JPEG
# ---------------------------------------------------------------------------

def render(htmls: list[str], out_dir: Path) -> list[Path]:
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
            subprocess.run(
                [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                 "--force-device-scale-factor=1", "--window-size=1080,1350",
                 "--virtual-time-budget=10000", f"--user-agent={CHROME_UA}",
                 f"--user-data-dir={tmp}/profile", f"--screenshot={png}", src.as_uri()],
                check=True, timeout=60, capture_output=True,
            )
            jpg = out_dir / f"{i}.jpg"
            with Image.open(png) as im:
                if im.size != (1080, 1350):
                    raise RuntimeError(f"Chrome rendered {im.size}, expected (1080, 1350).")
                im.convert("RGB").save(jpg, "JPEG", quality=92)
            paths.append(jpg)
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


def _upload(db, date: str, paths: list[Path]) -> list[str]:
    bucket = db.storage.from_(BUCKET)
    urls = []
    for p in paths:
        key = f"{date}/{p.name}"
        bucket.upload(key, p.read_bytes(), {"content-type": "image/jpeg", "upsert": "true"})
        urls.append(bucket.get_public_url(key))
    return urls


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(date: str | None = None, dry_run: bool = False, out: str = "instagram-out") -> None:
    date = date or _today_et()
    token, ig_user_id = os.environ.get("IG_ACCESS_TOKEN"), os.environ.get("IG_USER_ID")
    if not dry_run and not (token and ig_user_id):
        logger.info("Instagram secrets not set — skipping.")
        return

    db = _get_supabase()
    if not dry_run and db.table("instagram_posts").select("post_date").eq("post_date", date).execute().data:
        logger.info("Already posted for %s — skipping.", date)
        return

    preds = (db.table("predictions")
             .select("game_id,game_time_utc,home_team,away_team,predicted_team,confidence")
             .eq("game_date", date).execute().data) or []
    if not preds:
        logger.info("No predictions for %s — nothing to post.", date)
        return

    rec = db.table("running_record").select("total_correct,total_incorrect").eq("id", 1).execute().data
    record = (rec[0]["total_correct"], rec[0]["total_incorrect"]) if rec else None

    paths = render(build_slides(preds, date, record), Path(out) / date)
    caption = build_caption(preds, date)
    if dry_run:
        for p in paths:
            print(p)
        print(caption)
        return

    # Claim the date first: the PK makes a concurrent run's insert fail -> no double post.
    db.table("instagram_posts").insert({"post_date": date}).execute()
    try:
        import requests
        session = requests.Session()
        session.headers["Authorization"] = f"Bearer {token}"
        media_id = publish(session, ig_user_id, _upload(db, date, paths), caption)
    except PublishUncertain:
        # Keep the claim: a retry could double-post. Check the account, then delete
        # the instagram_posts row by hand if it really didn't post.
        raise
    except Exception:
        db.table("instagram_posts").delete().eq("post_date", date).execute()
        raise
    # A crash before this line leaves the claim row: later runs skip (never double-post).
    db.table("instagram_posts").update({"media_id": media_id}).eq("post_date", date).execute()
    logger.info("Posted %d slide(s) for %s: media %s", len(paths), date, media_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date",    help="ET date YYYY-MM-DD (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="Render only; no upload/post")
    parser.add_argument("--out",     default="instagram-out", help="Output dir for the JPEGs")
    args = parser.parse_args()
    run(args.date, args.dry_run, args.out)


if __name__ == "__main__":
    main()
