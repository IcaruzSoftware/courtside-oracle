"""post_instagram: slide building, rendering, Graph flow choice, and the skip paths."""

import html
import shutil

import pytest
import requests
from PIL import Image

from scripts import post_instagram as ig

DATE = "2026-10-21"
TRICODES = list(ig.TEAMS)


def _preds(n):
    return [{"game_id": f"00225000{i:02d}", "game_time_utc": f"2026-10-21T23:{i:02d}:00+00:00",
             "home_team": TRICODES[2 * i % 30], "away_team": TRICODES[(2 * i + 1) % 30],
             "predicted_team": TRICODES[2 * i % 30], "confidence": 0.51 + i / 100}
            for i in range(n)]


def test_popularity_order():
    late = {"game_id": "1", "game_time_utc": "2026-10-22T02:00:00+00:00", "home_team": "LAL", "away_team": "GSW"}
    early = {"game_id": "2", "game_time_utc": "2026-10-21T23:00:00+00:00", "home_team": "CHA", "away_team": "WAS"}
    tie = dict(late, game_id="0", game_time_utc="2026-10-22T03:00:00+00:00", home_team="GSW", away_team="LAL")
    assert [g["game_id"] for g in ig._order([early, tie, late])] == ["1", "0", "2"]


@pytest.mark.parametrize("n", [1, 3, 15])
def test_prediction_slides(n):
    games = ig._order(_preds(n))
    out = [html.unescape(h) for h in ig.prediction_slides(games, DATE, (4, 1, "80.0%"))]
    assert len(out) == n
    for i, (p, doc) in enumerate(zip(games, out), 1):
        assert p["home_team"] in doc and p["away_team"] in doc and f"{round(p['confidence'] * 100)}%" in doc
        assert "TODAY'S PREDICTION · WED, OCT 21, 2026" in doc and f"Game {i} of {n}" in doc
        assert 'class="marker"' in doc and "4–1" in doc
    assert ig.MAX_ITEMS == 10
    _check_caption(ig.prediction_caption(games, DATE), n)


def _check_caption(caption, n):
    assert caption.count(" over ") == n and "gerritvisser.de" in caption
    assert len(caption) <= 2200 and caption.count("#") <= 8
    assert not any(w in caption.lower() for w in ("bet", "odds"))


def _resolved(date, n, correct=True):
    return [dict(p, game_date=date, correct=correct, actual_winner=p["home_team"]) for p in _preds(n)]


def test_record_slides(monkeypatch, fake_supabase):
    rows = _resolved("2026-10-20", 3)
    rows[1]["correct"] = False
    db = fake_supabase({"predictions": rows, "running_record": [
        {"id": 1, "total_correct": 6, "total_incorrect": 2, "accuracy": None}]})
    monkeypatch.setattr(ig, "fetch_boxscore", lambda gid: {
        "gameStatus": 3, "homeTeam": {"score": 110}, "awayTeam": {"score": 100}})
    slides, caption = ig._build(db, "record", DATE, None)
    slides = [html.unescape(s) for s in slides]
    assert len(slides) == 4
    assert all(s in slides[0] for s in (">6<", ">2<", "CORRECT", "INCORRECT", "75.0% accuracy", "Last night: 2–1"))
    assert "RUNNING RECORD · WED, OCT 21, 2026" in slides[0]
    verdicts = [("CORRECT" in s, "WRONG" in s) for s in slides[1:]]
    assert sorted(verdicts) == [(False, True), (True, False), (True, False)]
    assert all("LAST NIGHT'S RESULT · TUE, OCT 20, 2026" in s and "110" in s for s in slides[1:])
    assert caption.startswith("Last night: 2–1 ✅ · All-time: 6–2 (75.0%)")
    assert caption.count("✅") == 3 and caption.count("❌") == 1 and " won 110–100" in caption
    _check_caption(caption, 3)


def test_record_missing_score_raises(monkeypatch, fake_supabase):
    db = fake_supabase({"predictions": _resolved("2026-10-20", 2), "running_record": [
        {"id": 1, "total_correct": 2, "total_incorrect": 0, "accuracy": 1}]})
    monkeypatch.setattr(ig, "fetch_boxscore", lambda gid: None)
    with pytest.raises(RuntimeError, match="box score"):
        ig._build(db, "record", DATE, None)


@pytest.mark.skipif(not any(shutil.which(c) for c in ("google-chrome", "chromium", "chromium-browser")),
                    reason="no Chrome")
@pytest.mark.parametrize("n", [1, 3, 15])
def test_render(n, tmp_path):
    paths = ig.render(ig.prediction_slides(_preds(n), DATE, None), tmp_path, "PNG")
    assert len(paths) == n
    for p in paths:
        with Image.open(p) as im:
            assert (im.format, im.size) == ("PNG", (1080, 1350))


class _Session:
    def __init__(self):
        self.calls = []
        self.headers = {}

    def request(self, method, url, timeout, data=None, params=None):
        self.calls.append((method, url, data or {}))
        r = requests.Response()
        r.status_code = 200
        body = {"status_code": "FINISHED"} if method == "GET" else {"id": f"id{len(self.calls)}"}
        r._content = requests.compat.json.dumps(body).encode()
        return r


def _no_calls(*a, **k):
    raise AssertionError("must not be called")


@pytest.mark.parametrize("n,carousel", [(1, False), (3, True)])
def test_publish_single_vs_carousel(n, carousel):
    s = _Session()
    assert ig.publish(s, "42", [f"https://x/{i}.jpg" for i in range(n)], "cap").startswith("id")
    media = [d for m, u, d in s.calls if u.endswith("/42/media")]
    assert any(d.get("media_type") == "CAROUSEL" for d in media) == carousel
    assert len(media) == (n + 1 if carousel else 1)
    assert s.calls[-1][1].endswith("/42/media_publish")


class _Storage:
    def __init__(self):
        self.keys = []

    def from_(self, _):
        return self

    def upload(self, key, *a):
        self.keys.append(key)

    def get_public_url(self, key):
        return f"https://x/{key}"


def _live(monkeypatch, tmp_path, db, session=_Session):
    """IG env set, db patched in, render faked (records slide counts)."""
    db.storage = _Storage()
    db.rendered = []
    monkeypatch.setenv("IG_ACCESS_TOKEN", "t")
    monkeypatch.setenv("IG_USER_ID", "42")
    monkeypatch.setattr(ig, "_get_supabase", lambda: db)
    monkeypatch.setattr(ig, "fetch_boxscore", lambda gid: {
        "gameStatus": 3, "homeTeam": {"score": 110}, "awayTeam": {"score": 100}})
    monkeypatch.setattr(requests, "Session", session)

    def fake_render(htmls, out, fmt):
        out.mkdir(parents=True, exist_ok=True)
        db.rendered.append(len(htmls))
        paths = [out / f"{i}.jpg" for i in range(len(htmls))]
        for p in paths:
            p.write_bytes(b"jpg")
        return paths

    monkeypatch.setattr(ig, "render", fake_render)


def test_post_both_kinds_capped(monkeypatch, fake_supabase, tmp_path):
    db = fake_supabase({"predictions": [dict(p, game_date=DATE) for p in _preds(15)] + _resolved("2026-10-20", 15),
                        "running_record": [{"id": 1, "total_correct": 6, "total_incorrect": 2, "accuracy": 0.75}]})
    _live(monkeypatch, tmp_path, db)
    ig.run(DATE, out=str(tmp_path))
    assert db.rendered == [10, 10]   # record (1 + 9 games) first, then 10 predictions
    assert {(r["kind"], r["media_id"] is not None) for r in db.table("instagram_posts").rows} == \
        {("record", True), ("predictions", True)}
    assert db.storage.keys[0] == f"{DATE}/record/0.jpg" and db.storage.keys[-1] == f"{DATE}/predictions/9.jpg"


@pytest.mark.parametrize("fail_on,claim_kept", [("/media_publish", True), ("/media", False)])
def test_failed_post_claim(monkeypatch, fake_supabase, tmp_path, fail_on, claim_kept):
    """A failure before media_publish frees the (date, kind); a failed media_publish keeps the claim."""
    class Failing(_Session):
        def request(self, method, url, timeout, data=None, params=None):
            if url.endswith(fail_on):
                raise requests.Timeout("boom")
            return super().request(method, url, timeout, data, params)

    db = fake_supabase({"predictions": [dict(p, game_date=DATE) for p in _preds(2)]})
    _live(monkeypatch, tmp_path, db, Failing)
    with pytest.raises(Exception):
        ig.run(DATE, out=str(tmp_path))
    assert bool(db.table("instagram_posts").select("*").execute().data) == claim_kept


def test_missing_ig_env_does_nothing(monkeypatch):
    monkeypatch.delenv("IG_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("IG_USER_ID", raising=False)
    monkeypatch.setattr(ig, "_get_supabase", _no_calls)
    monkeypatch.setattr(requests, "Session", _no_calls)
    ig.run(DATE)


@pytest.mark.parametrize("seed", [
    {"instagram_posts": [{"post_date": DATE, "kind": k, "media_id": "1"} for k in ("record", "predictions")],
     "predictions": [dict(p, game_date=DATE) for p in _preds(2)] + _resolved("2026-10-20", 2)},
    {"predictions": []},                                   # no games on D or D-1
    {"predictions": _resolved("2026-10-20", 2) + [dict(_resolved("2026-10-20", 3)[2], correct=None)]},
], ids=["already-posted", "no-games", "unresolved"])
def test_skips_write_nothing(monkeypatch, fake_supabase, tmp_path, seed):
    db = fake_supabase(seed)
    _live(monkeypatch, tmp_path, db, _no_calls)
    monkeypatch.setattr(ig, "render", _no_calls)
    ig.run(DATE, out=str(tmp_path))
    assert db.writes == []
