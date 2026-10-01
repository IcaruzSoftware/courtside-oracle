# Operations runbook

## Background

The original build PC was reset and `src/data/raw/` / the ELO parquet state
were never committed — the pre-fix `.gitignore` ignored the `data/` dirs
wholesale, and git cannot re-include a file whose parent directory is itself
ignored, so the `!` negations for the state files silently did nothing. The
historical data was re-downloaded from scratch with `src/scripts/bootstrap_data.py`
(2015-16..2025-26, 14,128 games, traditional/advanced/tracking box scores) and
the ELO rebuilt. The fixed `.gitignore` now ignores `src/data/raw/*` and
`src/data/processed/*` but whitelists the state files listed in
[data.md](data.md), so this shouldn't recur — but if `git status` ever shows
none of the state files tracked after a fresh clone, that's the symptom to
check for.

## The three GitHub Actions workflows

All three live in `.github/workflows/` and run on `ubuntu-latest` with Python
3.12 (matches the local `.venv`).

### `daily_predict.yml` — Daily Predictions

- **Schedule:** `0 15 * * *` (15:00 UTC = 11:00 AM ET, before most tip-offs).
  Also `workflow_dispatch` (manual trigger from the Actions tab).
- **Runs:** `python src/scripts/daily_run.py --predict`.
- **Commits nothing.** Only writes to Supabase (`predictions`, `shap_values`)
  via `SUPABASE_URL` / `SUPABASE_KEY`.

### `daily_evaluate.yml` — Daily Evaluate

- **Schedule:** `0 12 * * *` (12:00 UTC = 8:00 AM ET, after overnight games
  are final). Also `workflow_dispatch`.
- **Runs:** `python src/scripts/daily_run.py --evaluate`, which runs two
  independent steps, each in its own try/except: first `evaluate.py` (resolve
  pending predictions, recompute `running_record`), then `daily_state.run()`
  (advance the committed game logs / player stats / ELO state from the CDN).
  A failure in the first does not skip the second — either failing still
  fails the job (non-zero exit) so the workflow shows red.
- **Commits:** `git add src/data/` then commits + pushes only if that stages
  a diff (`git diff --cached --quiet` gate). Since `.gitignore` only allows
  the whitelisted state files under `src/data/`, this can only ever commit
  `game_log_*.csv`, `player_season_stats_*.csv`, `player_elo_current.parquet`,
  and `player_elo_recent.parquet` — never raw box scores. Commit message:
  `chore: daily state update [skip ci]`. Needs `permissions: contents: write`
  (already set).

### `keepalive.yml` — Keepalive

- **Schedule:** `17 6 * * *` (06:17 UTC, off the hour on purpose).
  Also `workflow_dispatch`.
- **Purpose 1:** Supabase free-tier projects auto-pause after ~7 days with no
  activity. A `curl -f` authenticated read against `running_record` keeps the
  project awake and fails the job loudly if Supabase is unreachable/paused.
- **Purpose 2:** GitHub disables scheduled workflows in public repos after 60
  days with no repository activity (this already happened to both
  `daily_*.yml` once, in August 2026). The second step runs
  `gh workflow enable daily_evaluate.yml / daily_predict.yml / keepalive.yml`
  on every run (`if: always()`, so it still re-enables the workflows even if
  the Supabase ping above failed), keeping all three schedules alive
  indefinitely. Needs `permissions: actions: write`.
- **NBA CDN reachability from GitHub-hosted runners is unconfirmed** — see
  the note under "Common failure causes" below.

## Required GitHub secrets

| Secret | Used by | Notes |
|---|---|---|
| `SUPABASE_URL` | `daily_predict.yml`, `daily_evaluate.yml`, `keepalive.yml` | Public project URL, safe to also keep in local `.env` |
| `SUPABASE_KEY` | same | **Service-role key** — bypasses RLS, full read/write. Never expose this to the web app (see `web`'s `NEXT_PUBLIC_SUPABASE_ANON_KEY`, which is a different, RLS-restricted key set in Vercel, not GitHub) |

`PROXIES` is **obsolete** — it was only ever read by `collect.py`'s proxy
pool, which nothing in the current daily pipeline uses (the CDN path needs no
proxy). Safe to delete from repo secrets.

## When a job fails

Check the failed run's logs in the Actions tab first — every pipeline script
logs at `INFO` level with timestamps. Common causes:

- **Supabase paused / unreachable.** `predict.py` / `evaluate.py` raise
  `EnvironmentError` or a `supabase` client exception; `keepalive.yml`'s ping
  step will also be failing. Reopen the project in the Supabase dashboard
  (unpausing is manual on the free tier) and re-run the workflow
  (`workflow_dispatch`).
- **NBA CDN block / 403.** `nba_cdn.fetch_boxscore()` treats a 404 as normal
  (game not played yet — returns `None`, not an error) but **raises** on any
  other non-200 status, e.g. 403 after Akamai rejects the request
  (missing/stale `Origin`/`Referer`/`Sec-Fetch-*` headers, or the runner's IP
  being blocked outright); `fetch_schedule()` raises on any HTTP error. This
  fails the job loudly by design — silently skipping a day's state update
  would be worse than a visible failure. **Whether GitHub-hosted runners can
  reach cdn.nba.com at all is being verified on the first live runs — treat
  this as an open question until confirmed, and update this paragraph once it
  is.** If it turns out GitHub's IP ranges are blocked, the fix is a proxy or
  a self-hosted runner; no such fallback exists yet.
- **State conflict / merge conflict on push.** `daily_evaluate.yml`'s commit
  step already does `git pull --rebase origin <branch>` before `git push`, so
  the common case — another commit landed on `main` between the checkout and
  the push (e.g. a manual `workflow_dispatch` overlapping the schedule) — is
  handled automatically. A genuine conflict (two runs racing on the *same*
  state file, so the rebase itself can't apply cleanly) still needs manual
  resolution — re-run `daily_state.py` locally against the current `main` and
  push the result.
- **Missing box score yet.** Not a failure — a 404 from the CDN is the normal
  case for a game that hasn't been played yet. `daily_state.py` logs
  `"box score not available yet"` and simply skips that game until a later
  run picks it up (it re-scans from `LOOKBACK_DAYS` before the last logged
  game every time, so nothing is lost).

## Re-enabling disabled workflows manually

If `keepalive.yml` itself is disabled (or hasn't run yet) and the daily
workflows stop firing:

```bash
gh workflow enable daily_evaluate.yml --repo <owner>/courtside-oracle
gh workflow enable daily_predict.yml  --repo <owner>/courtside-oracle
gh workflow enable keepalive.yml      --repo <owner>/courtside-oracle
```

## Full historical bootstrap / ELO rebuild

Only needed if the raw data or ELO state is lost again, or to extend the
historical window to a new season from scratch. Expect this to run for
several hours unattended — the script is written for that (see
`bootstrap_data.py`'s module docstring for the sleep-prevention and backoff
behavior).

```bash
python src/scripts/bootstrap_data.py                 # phase 1 then phase 2, ~7h total
python src/scripts/bootstrap_data.py --phase 1        # game logs + player season stats only (fast)
python src/scripts/bootstrap_data.py --phase 2 --limit 3   # box scores, first 3 pending games (smoke test)
```

Exit code is `2` if any game is still missing a box score at the end of a
phase-2 run (see `src/data/raw/missing_boxscores.txt` for which ones) — safe
to just re-run, it resumes from wherever it left off and never re-downloads a
complete game.

Then rebuild ELO from the downloaded box scores:

```bash
python src/pipeline/elo.py --force
```

This writes `player_elo.parquet` (full history, not committed) and the two
committed state files (`player_elo_current.parquet`,
`player_elo_recent.parquet`). **Commit only the state files** — never the
contents of `src/data/raw/` or `player_elo.parquet` (see [data.md](data.md)
for exactly what `.gitignore` allows through).

If you also need to retrain the model against the new data, continue with
`python src/pipeline/build_dataset.py` then `python src/pipeline/train.py`
(see [model.md](model.md)).

## Applying a Supabase migration

New setups: run `src/supabase/schema.sql` once in the Supabase SQL editor —
it already includes everything, including `game_time_utc` and the RLS
policies.

Existing deployments created before `game_time_utc` / RLS existed: apply
`src/supabase/migrations/001_game_time_and_rls.sql` in the SQL editor. It's
idempotent (`ADD COLUMN IF NOT EXISTS`, `DROP POLICY IF EXISTS` before each
`CREATE POLICY`) — safe to re-run.

**Apply migration 001 before deploying any web build that queries
`game_time_utc`** (the `/card` page's live/upcoming/tipoff-label logic reads
this column via `getCardPrediction()` in `web/lib/supabase.ts`) — querying a
column that doesn't exist yet fails that request outright on an
unmigrated database.

## Deploying the web app

Hosted on Vercel (team "icaruz-software"), static export
(`output: "export"` in `next.config.ts` — no server runtime, so all data
fetching is client-side; Next's `headers()` and ISR do not apply here).
Deploys on push to `main` via Vercel's GitHub integration. Required env vars
in the Vercel project settings (not GitHub secrets — this is a separate,
public-safe anon key):

- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`

Local dev: `cd web && npm install && npm run dev`. `npm run build` runs the
static export; `npm run lint` runs `next lint`.

The `/card` route (420×260) is the standalone widget embedded as an iframe on
the portfolio site (`IcaruzSoftware/portfolio`, https://gerritvisser.de) —
that embed lives in a different repo, so a breaking change to `/card`'s
markup or query shape needs a corresponding check there.

## Season rollover

Nothing to run manually — season boundaries are derived from dates
everywhere (`_season_of()` / `_date_to_season()`: October or later = new
season). 2026-27: preseason from 2026-10-03, regular season opens
2026-10-20. The public running record only counts predictions with
`game_date >= RECORD_START` (currently `"2026-10-01"`, in `evaluate.py`) —
bump this constant if you want the ticker to reset for a new season instead
of accumulating across seasons. The 5 rows inserted by `seed_finals.py` (the
2026 Finals, predicted retroactively) have earlier `game_date`s and are
excluded by this cutoff regardless.
