"""fetch_boxscore: Akamai 403 is an error; 404 or S3-origin 403 (x-amz-request-id)
means not-yet-available."""

import pytest

from pipeline import nba_cdn


class _Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload


class _Session:
    def __init__(self, status, payload=None, headers=None):
        self._resp = _Resp(status, payload, headers)

    def get(self, url, timeout=None, proxies=None):
        return self._resp


def test_403_raises(monkeypatch):
    monkeypatch.setattr(nba_cdn, "_get_session", lambda: _Session(403))
    with pytest.raises(RuntimeError):
        nba_cdn.fetch_boxscore("0042500405")


def test_404_returns_none(monkeypatch):
    monkeypatch.setattr(nba_cdn, "_get_session", lambda: _Session(404))
    assert nba_cdn.fetch_boxscore("0042500405") is None


def test_s3_403_returns_none(monkeypatch):
    # Missing object: the request got past Akamai and the S3 origin answers 403.
    s3 = _Session(403, headers={"x-amz-request-id": "ABC", "content-type": "application/xml"})
    monkeypatch.setattr(nba_cdn, "_get_session", lambda: s3)
    assert nba_cdn.fetch_boxscore("0022600001") is None


def test_200_returns_game(monkeypatch):
    monkeypatch.setattr(nba_cdn, "_get_session", lambda: _Session(200, {"game": {"gameId": "x"}}))
    assert nba_cdn.fetch_boxscore("0042500405") == {"gameId": "x"}
