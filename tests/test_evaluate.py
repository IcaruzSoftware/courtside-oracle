"""Evaluate: the running record is all-time (includes the seeded 2026 Finals rows)."""

from datetime import datetime

import pytest

import pipeline.evaluate as ev


@pytest.fixture(autouse=True)
def _freeze_today_et(monkeypatch):
    # Seeds use 2026-11 game dates; pin "today" after them so they count as started.
    monkeypatch.setattr(ev, "_today_et", lambda: "2026-11-10")


def test_running_record_is_all_time(monkeypatch, fake_supabase):
    seed = {
        "predictions": [
            # pending current-season game (will be resolved this run)
            {"id": "a", "game_id": "0022600001", "game_date": "2026-11-01",
             "predicted_team": "BOS", "home_team": "BOS", "away_team": "DET",
             "actual_winner": None, "correct": None},
            # already-resolved current-season game
            {"id": "b", "game_id": "0022600002", "game_date": "2026-11-02",
             "predicted_team": "LAL", "actual_winner": "LAL", "correct": True},
            # seeded 2026 Finals rows — counted in the all-time record
            {"id": "c", "game_id": "0042500401", "game_date": "2026-06-03",
             "predicted_team": "NYK", "actual_winner": "NYK", "correct": True},
            {"id": "d", "game_id": "0042500403", "game_date": "2026-06-08",
             "predicted_team": "NYK", "actual_winner": "SAS", "correct": False},
        ],
        "running_record": [],
    }
    db = fake_supabase(seed)
    monkeypatch.setattr(ev, "_fetch_results_cdn", lambda ids: {"0022600001": "BOS"})

    ev.evaluate(dry_run=False, db=db)

    rec = [w[2] for w in db.writes if w[0] == "running_record" and w[1] == "upsert"][-1]
    # Counted: a (BOS==BOS, correct) + b (correct) + Finals c (correct) + d (wrong) = 3/1.
    assert rec["total_correct"] == 3
    assert rec["total_incorrect"] == 1
    assert rec["accuracy"] == 0.75


def test_dry_run_writes_nothing(monkeypatch, fake_supabase):
    seed = {"predictions": [
        {"id": "a", "game_id": "0022600001", "game_date": "2026-11-01",
         "predicted_team": "BOS", "home_team": "BOS", "away_team": "DET",
         "actual_winner": None, "correct": None},
    ], "running_record": []}
    db = fake_supabase(seed)
    monkeypatch.setattr(ev, "_fetch_results_cdn", lambda ids: {"0022600001": "BOS"})

    ev.evaluate(dry_run=True, db=db)
    assert db.writes == []


def test_running_record_recomputed_when_no_pending(fake_supabase):
    # Everything already graded (no pending), but running_record is stale (seeded 4-1).
    seed = {
        "predictions": [
            {"id": "b", "game_id": "0022600002", "game_date": "2026-11-02",
             "predicted_team": "LAL", "actual_winner": "LAL", "correct": True},
            {"id": "e", "game_id": "0022600003", "game_date": "2026-11-03",
             "predicted_team": "NYK", "actual_winner": "BOS", "correct": False},
            {"id": "c", "game_id": "0042500401", "game_date": "2026-06-03",
             "predicted_team": "NYK", "actual_winner": "NYK", "correct": True},
        ],
        "running_record": [{"id": 1, "total_correct": 4, "total_incorrect": 1, "accuracy": 0.8}],
    }
    db = fake_supabase(seed)
    ev.evaluate(dry_run=False, db=db)

    rec = [w[2] for w in db.writes if w[0] == "running_record" and w[1] == "upsert"][-1]
    # All-time: b (correct) + e (wrong) + Finals row c (correct) = 2/1.
    assert rec["total_correct"] == 2
    assert rec["total_incorrect"] == 1
    assert rec["accuracy"] == round(2 / 3, 4)
    assert rec["last_updated"]
    datetime.fromisoformat(rec["last_updated"])


def test_record_recomputed_when_fetch_raises(monkeypatch, fake_supabase):
    seed = {"predictions": [
        {"id": "a", "game_id": "0022600001", "game_date": "2026-11-01",
         "predicted_team": "BOS", "home_team": "BOS", "away_team": "DET",
         "actual_winner": None, "correct": None},
        {"id": "b", "game_id": "0022600002", "game_date": "2026-11-02",
         "predicted_team": "LAL", "actual_winner": "LAL", "correct": True},
    ], "running_record": []}
    db = fake_supabase(seed)

    def boom(ids):
        raise RuntimeError("All NBA CDN channels failed")
    monkeypatch.setattr(ev, "_fetch_results_cdn", boom)

    with pytest.raises(RuntimeError):
        ev.evaluate(dry_run=False, db=db)

    rec = [w[2] for w in db.writes if w[0] == "running_record" and w[1] == "upsert"][-1]
    assert rec["total_correct"] == 1
    assert rec["total_incorrect"] == 0


def test_unstarted_games_are_not_fetched(monkeypatch, fake_supabase):
    pending = {"predicted_team": "BOS", "home_team": "BOS", "away_team": "DET",
               "actual_winner": None, "correct": None}
    seed = {"predictions": [
        # tipped off (Supabase TIMESTAMPTZ format)
        {"id": "a", "game_id": "0042500405", "game_date": "2026-06-13",
         "game_time_utc": "2026-06-14T00:30:00+00:00", **pending},
        # future tip-off (CDN 'Z' format)
        {"id": "f", "game_id": "0022600099", "game_date": "2099-01-01",
         "game_time_utc": "2099-01-01T23:30:00Z", **pending},
        # no tip-off time, game_date is "today" ET -> not started
        {"id": "t", "game_id": "0022600098", "game_date": "2026-11-10",
         "game_time_utc": None, **pending},
    ], "running_record": []}
    db = fake_supabase(seed)
    fetched = []
    monkeypatch.setattr(ev, "_fetch_results_cdn", lambda ids: fetched.extend(ids) or {})

    ev.evaluate(dry_run=True, db=db)
    assert fetched == ["0042500405"]
