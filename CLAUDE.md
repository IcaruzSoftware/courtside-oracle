# CLAUDE.md

Entry point for an AI session working in this repo. Read this first; it links
to `docs/` for depth instead of duplicating it. Human-facing overview:
[README.md](README.md).

## What this is

Courtside Oracle predicts NBA game outcomes: a custom per-player ELO system
feeds an XGBoost classifier (Platt-calibrated). Predictions run daily via
GitHub Actions, are stored in Supabase, and are shown on a Next.js site
(https://courtside-oracle.gerritvisser.de) and a 420×260 iframe widget
embedded on https://gerritvisser.de (separate repo: `IcaruzSoftware/portfolio`).

## Data flow

```
bootstrap (stats.nba.com, one-time) → elo.py → committed ELO state
                                                       │
daily: cdn.nba.com → daily_state.py → state files → elo.py (incremental)
daily: cdn.nba.com → evaluate.py    → Supabase (resolve predictions, running_record)
daily: cdn.nba.com → predict.py     → features.py (live) → xgb_model.pkl → Supabase
                                                       │
                                    Supabase (RLS) → web/ (Next.js static export) → Vercel
```

Details: [docs/architecture.md](docs/architecture.md) (module-by-module +
why the live and training feature paths differ),
[docs/data.md](docs/data.md) (every file/table),
[docs/elo.md](docs/elo.md) (the ELO system),
[docs/model.md](docs/model.md) (features, training, metrics, caveats),
[docs/operations.md](docs/operations.md) (runbook).

## Repo map

```
src/pipeline/
  collect.py          full nba_api collector (proxy-pool aware) — superseded by bootstrap_data.py for the actual rebuild
  elo.py              player ELO: scoring, ranking, build_elo/update_elo/update_team_assignments, CDN adapter
  nba_cdn.py          cdn.nba.com client: schedule, box score, game-ID prefix helpers, team id<->tricode
  daily_state.py      daily catch-up: CDN box scores -> game logs/player stats/ELO (replaces removed update_season.py)
  features.py         build_feature_matrix() — training and live feature paths
  build_dataset.py    walks history -> feature_matrix.parquet (training input)
  train.py            Optuna + XGBoost + Platt calibration -> models/xgb_model.pkl
  predict.py          predict one matchup (CLI) or predict_todays_games() (daily pipeline)
  evaluate.py         resolve pending predictions vs CDN results, recompute running_record
  seed_finals.py      one-time historical seed — already run, do not re-run
  shap_export.py      global SHAP plot/summary utility — not wired into the daily pipeline
src/scripts/
  bootstrap_data.py   resumable stats.nba.com downloader for the historical rebuild
  daily_run.py        GitHub Actions entry point: --predict / --evaluate / both
src/supabase/
  schema.sql            fresh-setup schema (tables + RLS), run once in the SQL editor
  migrations/001_*.sql  brings a pre-existing DB up to schema.sql's shape (game_time_utc + RLS)
.github/workflows/
  daily_predict.yml   11:00 AM ET — predict today's games
  daily_evaluate.yml  8:00 AM ET — resolve results + advance committed state
  keepalive.yml       daily — ping Supabase, re-enable workflows GitHub auto-disabled
web/                  Next.js 15, static export, deployed to Vercel; app/(main)/ = site, app/card/ = iframe widget
tests/                pytest; conftest.py has a FakeSupabase + a tiny built-from-fixture live state
```

## Running locally

Python **3.12** (matches CI; use a local `.venv` — it's gitignored, not committed).

```bash
pip install -r requirements.txt
python -m pytest                                          # tests/, via pytest.ini
python src/scripts/daily_run.py                            # evaluate + predict, today (ET)
python src/scripts/daily_run.py --predict --dry-run --date 2026-06-13
python src/scripts/daily_run.py --evaluate --dry-run
python src/pipeline/daily_state.py --dry-run --date 2026-11-05
python src/pipeline/evaluate.py --dry-run
python src/pipeline/predict.py --game-id 0042500237
python src/pipeline/predict.py --home NYK --away OKC --date 2026-06-05
python src/pipeline/elo.py --force                          # full ELO rebuild from src/data/raw/
python src/pipeline/build_dataset.py --force                # rebuild feature_matrix.parquet
python src/pipeline/train.py --trials 100 --force            # retrain
python src/scripts/bootstrap_data.py --phase 2 --limit 3      # smoke-test the box-score downloader
```

`SUPABASE_URL` / `SUPABASE_KEY` (service-role key) are required for anything
that isn't `--dry-run`. `web/`: `cd web && npm install && npm run dev`.

## Committed live-state contract

`.gitignore` ignores `src/data/raw/*` and `src/data/processed/*` wholesale,
then re-includes exactly four files with `!` negations — **never commit
anything else under `src/data/`,** and never add a new generated file there
without also adding its negation:

- `src/data/raw/game_log_*.csv` — one row per team per game (appended daily by `daily_state.py`)
- `src/data/raw/player_season_stats_*.csv` — one row per player per season (updated daily)
- `src/data/processed/player_elo_current.parquet` — post-game ELO snapshot per player
- `src/data/processed/player_elo_recent.parquet` — last-11 pre-game ELO snapshots per player

`src/models/xgb_model.pkl` **is committed** (its own negation in
`.gitignore`) — the old "model not committed" caveat from an earlier README
is no longer true. `player_elo.parquet` (full history) and
`feature_matrix.parquet` are deliberately **not** committed — see
[docs/data.md](docs/data.md) for the full file-by-file table and why.

## NBA data access rules

Two unrelated sources, never mixed in one run:

- **stats.nba.com** (via `nba_api`) — bootstrap only. Confirmed working from
  the owner's home PC with `nba_api`'s default browser-like headers; a plain
  `curl` times out. Whether it's reachable from a cloud/CI IP is unverified
  here (commonly reported to be blocked, but not tested against this repo).
- **cdn.nba.com** (via `src/pipeline/nba_cdn.py`) — the entire daily
  pipeline. Needs the browser-style JSON header set in `nba_cdn.CDN_HEADERS`
  (modern UA, `Origin`/`Referer` `https://www.nba.com`, `Sec-Fetch-*`) — a
  plain request, and even `nba_api`'s own (outdated) live header set, gets an
  Akamai 403. Box scores exist from the 2019-20 season onward. `fetch_boxscore()`
  treats a 404 as normal (game not played yet → returns `None`) but raises on
  any other non-200 status (403 = Akamai blocking this client) — that failure
  is intentionally loud, never silently skipped. **Whether GitHub-hosted
  runners can reach cdn.nba.com at all is unconfirmed** — see
  [docs/operations.md](docs/operations.md) for the marked-TBD paragraph;
  update it once the first live runs settle the question.

## Invariants / gotchas

- Game-ID prefix encodes type: `001` preseason, `002` regular season, `003`
  all-star, `004` playoffs, `005` play-in, `006` Cup final. Only
  `{002,004,005,006}` are "stateful" (`nba_cdn.is_stateful`) — update ELO and
  get predicted. All-star games are ignored entirely; preseason only updates
  a player's team assignment (never ELO), and only if the new appearance is
  newer than what's on file.
- `daily_state.py` rescans from **7 days before the last logged game**
  through the target date, not just the target date — so a box score that
  wasn't available yet on its game day still gets picked up later. Idempotent
  either way: games already in the game logs / ELO state are skipped.
- `predict.py` only predicts games that haven't started yet and never
  overwrites a prediction that already has a result — a late/partial re-run
  can't clobber a resolved pick.
- `evaluate.py` recomputes `running_record` on every run (not only when a
  prediction was just resolved), and the state update in `daily_run.py
  --evaluate` still runs even if `evaluate()` itself raised.
- `RECORD_START` (`evaluate.py`, currently `"2026-10-01"`) is the only thing
  keeping the 5 retroactive `seed_finals.py` rows out of the public running
  record. Don't re-run `seed_finals.py`.
- MATCHUP string (`"XXX vs. YYY"` = home, `"XXX @ YYY"` = away) is the only
  home/away signal in the game logs — there's no dedicated column.
- The **committed model** was trained on the original dataset (`collect.py`,
  which does fetch `boxscore_summary_*.json`), so it learned real
  availability effects. The *re-downloaded* bootstrap dataset (`bootstrap_data.py`)
  does **not** fetch `boxscore_summary` — only if/when someone retrains on
  that data would availability features go neutral for training too (fix:
  add `"summary"` to `bootstrap_data.py`'s wanted endpoints and re-run phase 2
  for it before retraining, ~14k extra calls ≈ 2.5h). See [docs/data.md](docs/data.md).
- `scikit-learn==1.8.0` is pinned because `xgb_model.pkl` was pickled with
  it — don't bump it without retraining.

## Where external things live

- **Supabase** project `pxvimjflsishbfrublwp` (free tier; pauses after ~7
  days idle, kept awake by `keepalive.yml`). Service-role key in GitHub
  secrets (`SUPABASE_KEY`); anon key in Vercel env
  (`NEXT_PUBLIC_SUPABASE_ANON_KEY`) — never the same key in both places.
- **Vercel** team "icaruz-software", static export, deploys on push to `main`.
- **Portfolio embed**: `/card` is iframed from `IcaruzSoftware/portfolio` — a
  breaking change to its markup/query needs a check in that repo too.
- **GitHub Actions**: public repo, so GitHub auto-disables scheduled
  workflows after 60 days with no repo activity; `keepalive.yml` re-enables
  all three daily via `gh workflow enable` on every run.

## Known limitations

- No live injury feed — player-availability features are always neutral for
  live predictions. This is a genuine train/serve mismatch: the **committed
  model** trained on real availability data (see above), so live predictions
  are missing a signal the model actually learned to use.
- Live ELO updates (CDN box score) lack `defensiveRating` and tracking data:
  defense degrades to steals+blocks only, and hustle ELO freezes for every
  post-bootstrap game. Historical/bootstrap ELO is unaffected.
- Training features are more optimistic than live: training ELO rosters are
  each game's actual ≥10-minute participants, live rosters are approximated
  from the ELO state; training PPG/star-out weights use the full final
  season, live uses season-to-date only. Expect live accuracy below the
  67.5% backtest. Full breakdown: [docs/model.md](docs/model.md).
- `web/app/(main)/page.tsx` hardcodes the model metrics text (67.5%/0.729/
  0.209/0.606) — it does not read `model_metadata` (which nothing writes to
  anyway).
- Head-to-head and home/away-split features use all games since 2015-16, not
  just the current season — consistent between training and live, just worth
  knowing when reading a small early-season sample.

## Common changes

- **Change a job's schedule** — edit the `cron:` line in the relevant
  `.github/workflows/*.yml` (times are UTC; comments note the ET equivalent).
- **Add a feature** — add a `get_*_features()` function in `features.py`,
  wire it into `build_feature_matrix()` (both training and live call the same
  function unless it needs `use_current_elo` branching), then **you must
  retrain**: `build_dataset.py --force` → `train.py --force`, and commit the
  new `models/xgb_model.pkl`. A live-only feature with no training equivalent
  will silently read as `0.0` in training and vice versa.
- **Apply a Supabase migration** — SQL editor, see
  [docs/operations.md](docs/operations.md#applying-a-supabase-migration).
  `001` must land before deploying any web build that queries
  `game_time_utc`.
- **Deploy the web app** — push to `main`; Vercel auto-deploys. Local
  preview: `cd web && npm run build`.
- **Rebuild ELO / bootstrap from scratch** — see
  [docs/operations.md](docs/operations.md#full-historical-bootstrap--elo-rebuild)
  (~7h unattended); commit only the state files listed above, never raw data.
