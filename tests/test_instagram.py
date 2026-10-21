"""post_instagram: slide building, rendering, Graph flow choice, and the skip paths."""

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


@pytest.mark.parametrize("n,slides", [(1, 1), (3, 3), (15, 10)])
def test_build_slides(n, slides):
    out = ig.build_slides(_preds(n), DATE, (4, 1))
    assert len(out) == slides
    for p, html in zip(_preds(n), out):
        assert p["home_team"] in html and p["away_team"] in html
        assert f"{round(p['confidence'] * 100)}%" in html
        assert 'class="marker"' in html and "4–1" in html and "DAILY PICKS · WED, OCT 21, 2026" in html
    caption = ig.build_caption(_preds(n), DATE)
    assert caption.count(" over ") == slides
    assert len(caption) <= 2200 and caption.count("#") <= 30


@pytest.mark.skipif(not any(shutil.which(c) for c in ("google-chrome", "chromium", "chromium-browser")),
                    reason="no Chrome")
@pytest.mark.parametrize("n", [1, 3, 15])
def test_render(n, tmp_path):
    paths = ig.render(ig.build_slides(_preds(n), DATE, None), tmp_path)
    assert len(paths) == min(n, 10)
    for p in paths:
        with Image.open(p) as im:
            assert (im.format, im.size) == ("JPEG", (1080, 1350))


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


@pytest.mark.parametrize("fail_on,claim_kept", [("/media_publish", True), ("/media", False)])
def test_failed_post_claim(monkeypatch, fake_supabase, tmp_path, fail_on, claim_kept):
    """A failure before media_publish frees the date; a failed media_publish keeps the claim."""
    class Failing(_Session):
        def request(self, method, url, timeout, data=None, params=None):
            if url.endswith(fail_on):
                raise requests.Timeout("boom")
            return super().request(method, url, timeout, data, params)

    class Storage:
        def from_(self, _):
            return self

        def upload(self, *a):
            pass

        def get_public_url(self, key):
            return f"https://x/{key}"

    db = fake_supabase({"predictions": [dict(p, game_date=DATE) for p in _preds(2)]})
    db.storage = Storage()
    monkeypatch.setenv("IG_ACCESS_TOKEN", "t")
    monkeypatch.setenv("IG_USER_ID", "42")
    monkeypatch.setattr(ig, "_get_supabase", lambda: db)
    def fake_render(htmls, out):
        paths = [tmp_path / f"{i}.jpg" for i in range(len(htmls))]
        for p in paths:
            p.write_bytes(b"jpg")
        return paths

    monkeypatch.setattr(ig, "render", fake_render)
    monkeypatch.setattr(requests, "Session", Failing)
    with pytest.raises(Exception):
        ig.run(DATE)
    assert bool(db.table("instagram_posts").select("*").execute().data) == claim_kept


def test_missing_ig_env_does_nothing(monkeypatch):
    monkeypatch.delenv("IG_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("IG_USER_ID", raising=False)
    monkeypatch.setattr(ig, "_get_supabase", _no_calls)
    monkeypatch.setattr(requests, "Session", _no_calls)
    ig.run(DATE)


def test_already_posted_skips(monkeypatch, fake_supabase):
    db = fake_supabase({"instagram_posts": [{"post_date": DATE, "media_id": "1"}],
                        "predictions": [dict(p, game_date=DATE) for p in _preds(2)]})
    monkeypatch.setenv("IG_ACCESS_TOKEN", "t")
    monkeypatch.setenv("IG_USER_ID", "42")
    monkeypatch.setattr(ig, "_get_supabase", lambda: db)
    monkeypatch.setattr(ig, "render", _no_calls)
    monkeypatch.setattr(requests, "Session", _no_calls)
    ig.run(DATE)
    assert db.writes == []
