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

## The four GitHub Actions workflows

All four live in `.github/workflows/` and run on `ubuntu-latest` with Python
3.12 (matches the local `.venv`).

### `daily_predict.yml` — Daily Predictions

- **Trigger:** `workflow_run` on `daily_evaluate.yml` completing (any
  conclusion), not its own cron — so it always runs right after evaluate
  commits fresh state, regardless of scheduler delay. Also `workflow_dispatch`
  (manual trigger from the Actions tab).
- **Runs:** `python src/scripts/daily_run.py --predict`.
- **Commits nothing.** Only writes to Supabase (`predictions`, `shap_values`)
  via `SUPABASE_URL` / `SUPABASE_KEY`.

### `daily_evaluate.yml` — Daily Evaluate

- **Schedule:** `58 6 * * *` (06:58 UTC ≈ 3:00 AM ET, 1:58 AM in winter/EST,
  after West Coast games are final; off the full hour to dodge GitHub's busiest scheduler slot). Also `workflow_dispatch`.
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

### `insta_post.yml` — Instagram Post

- **Trigger:** `workflow_run` on "Daily Predictions" completing (runs only if
  it succeeded), plus `workflow_dispatch` (manual trigger from the Actions
  tab). No cron of its own.
- **Runs:** `python src/scripts/post_instagram.py` — see
  [Instagram auto-posting](#instagram-auto-posting).
- **Separate run on purpose:** a failed post can never affect the predictions.
  With the IG secrets missing it exits 0 (green no-op).
- **Commits nothing.** Reads `predictions`, writes `instagram_posts` and the
  `instagram` storage bucket.

### `keepalive.yml` — Keepalive

- **Schedule:** `17 6 * * *` (06:17 UTC, off the hour on purpose).
  Also `workflow_dispatch`.
- **Purpose 1:** Supabase free-tier projects auto-pause after ~7 days with no
  activity. A `curl -f` authenticated read against `running_record` keeps the
  project awake and fails the job loudly if Supabase is unreachable/paused.
- **Purpose 2:** GitHub disables scheduled workflows in public repos after 60
  days with no repository activity (this already happened to both
  `daily_*.yml` once, in August 2026). The second step runs
  `gh workflow enable daily_evaluate.yml / daily_predict.yml / insta_post.yml / keepalive.yml`
  on every run (`if: always()`, so it still re-enables the workflows even if
  the Supabase ping above failed), keeping all four workflows alive (keepalive itself included)
  indefinitely. Needs `permissions: actions: write`.
- **The daily CDN calls go through residential proxies** (`NBA_PROXIES`
  secret): cdn.nba.com returns 403 from GitHub-hosted runners (NBA blacklists
  cloud IP ranges), so direct access only works locally. See the "NBA CDN
  block / 403" entry under "When a job fails" below.

## Required GitHub secrets

| Secret | Used by | Notes |
|---|---|---|
| `SUPABASE_URL` | `daily_predict.yml`, `daily_evaluate.yml`, `insta_post.yml`, `keepalive.yml` | Public project URL, safe to also keep in local `.env` |
| `SUPABASE_KEY` | same (`insta_post.yml` needs write access: service-role key) | **Service-role key** — bypasses RLS, full read/write. Never expose this to the web app (see `web`'s `NEXT_PUBLIC_SUPABASE_ANON_KEY`, which is a different, RLS-restricted key baked in at build time via `web/.env.local` — not a GitHub secret, see "Deploying the web app" below) |
| `NBA_PROXIES` | `daily_predict.yml`, `daily_evaluate.yml`, `check_nba_proxies.yml` | 1–3 static residential proxies, comma-separated `http(s)://user:pass@host:port`. URL-encode special characters in the password (e.g. `@`→`%40`) or urllib3 fails to parse it. Unset/empty → direct connection (local dev). Required in CI (see below). |
| `IG_ACCESS_TOKEN` | `insta_post.yml` | Optional. Long-lived system-user token for the Instagram Graph API. Feature is off (no-op) without it. See [Instagram auto-posting](#instagram-auto-posting). |
| `IG_USER_ID` | `insta_post.yml` | Optional. Instagram professional account ID (`instagram_business_account.id`). Feature is off without it. |

`PROXIES` (singular, no `NBA_` prefix) is **obsolete** — it was only ever read
by `collect.py`'s proxy pool, which nothing in the current daily pipeline uses.
Safe to delete from repo secrets. The pipeline's proxy support is the separate
`NBA_PROXIES` secret above (CDN failover), not `PROXIES`.

## When a job fails

Check the failed run's logs in the Actions tab first — every pipeline script
logs at `INFO` level with timestamps. Common causes:

- **Supabase paused / unreachable.** `predict.py` / `evaluate.py` raise
  `EnvironmentError` or a `supabase` client exception; `keepalive.yml`'s ping
  step will also be failing. Reopen the project in the Supabase dashboard
  (unpausing is manual on the free tier) and re-run the workflow
  (`workflow_dispatch`).
- **NBA CDN block / 403.** **Confirmed on the first live runs:** cdn.nba.com
  returns 403 from GitHub-hosted runners even with the correct `CDN_HEADERS`
  (NBA blacklists cloud IP ranges); stats.nba.com times out from runners too;
  ESPN's endpoints are reachable. Because the owner wants to keep NBA data, the
  daily jobs route the CDN calls through the residential proxies in the
  `NBA_PROXIES` secret. `nba_cdn` tries the proxies in order, sticks to the last
  one that worked, and treats an Akamai 403 (no `x-amz-*` headers, HTML body) or
  a connection error/timeout from a proxy as "this IP is blocked → fail over to
  the next". A missing box score is still normal (game not played yet →
  `fetch_boxscore()` returns `None`): a 404, or a 403 from the S3 origin
  (`x-amz-request-id` header, XML `AccessDenied` body). If **every** proxy fails,
  the fetch raises a summary naming each `proxy #i (host:port): <reason>` —
  host:port only, never credentials — and the job fails loudly (silently skipping
  a day's state update would be worse). **Fix:** rotate or replace the blocked
  proxy in the `NBA_PROXIES` secret and re-run the workflow. **Verify proxies
  first** with the manual **Check NBA Proxies** workflow (`check_nba_proxies.yml`,
  `workflow_dispatch`) or locally:
  `NBA_PROXIES='http://user:pass@host:port' python src/pipeline/nba_cdn.py --check`
  — it fetches the schedule + a box score through each proxy individually and
  prints status / size / latency, exiting 0 if at least one proxy fully works.
- **State conflict / merge conflict on push.** `daily_evaluate.yml`'s commit
  step already does `git pull --rebase origin <branch>` before `git push`, so
  the common case — another commit landed on `main` between the checkout and
  the push (e.g. a manual `workflow_dispatch` overlapping the schedule) — is
  handled automatically. A genuine conflict (two runs racing on the *same*
  state file, so the rebase itself can't apply cleanly) still needs manual
  resolution — re-run `daily_state.py` locally against the current `main` and
  push the result.
- **Missing box score yet.** Not a failure — a 404, or an S3-origin 403 (with an
  `x-amz-request-id` header), from the CDN is the normal case for a game that
  hasn't been played yet. `daily_state.py` logs
  `"box score not available yet"` and simply skips that game until a later
  run picks it up (it re-scans from `LOOKBACK_DAYS` before the last logged
  game every time, so nothing is lost).

## Re-enabling disabled workflows manually

If `keepalive.yml` itself is disabled (or hasn't run yet) and the daily
workflows stop firing:

```bash
gh workflow enable daily_evaluate.yml --repo <owner>/courtside-oracle
gh workflow enable daily_predict.yml  --repo <owner>/courtside-oracle
gh workflow enable insta_post.yml     --repo <owner>/courtside-oracle
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

Migration `src/supabase/migrations/002_instagram.sql` (also mirrored in
`schema.sql`) creates the `instagram_posts` table (RLS on, no policies →
service role only) and the public storage bucket `instagram`. Apply it before
enabling [Instagram auto-posting](#instagram-auto-posting).

**Apply migration 001 before deploying any web build that queries
`game_time_utc`** (the `/card` page's live/upcoming/tipoff-label logic reads
this column via `getCardPrediction()` in `web/lib/supabase.ts`) — querying a
column that doesn't exist yet fails that request outright on an
unmigrated database.

## Instagram auto-posting

`src/scripts/post_instagram.py` posts today's picks (ET) to Instagram. It is
run by its own workflow, `insta_post.yml` ("Instagram Post"), after "Daily
Predictions" succeeds — see [above](#insta_postyml--instagram-post).

1. Reads today's rows from Supabase `predictions`.
2. Builds one 1080x1350 slide per game (split confidence bar, 50% marker, team
   colors + tricodes, no NBA logos). 1 game → single-image post; 2–10 games →
   carousel. **More than 10 games → only the first 10 by tip-off time are
   posted, and the caption lists only those.** The caption stays within
   Instagram's limits (≤ 2,200 characters, ≤ 30 hashtags).
3. Renders them with headless Chrome (`google-chrome` / `chromium`) to PNG,
   converts to JPEG with Pillow (Instagram rejects PNG).
4. Uploads to the public Supabase Storage bucket `instagram` at
   `<date>/<i>.jpg`.
5. Posts via the Graph API (graph.facebook.com v23.0): one container per
   image, a CAROUSEL container (skipped for a single image), poll status,
   `media_publish`.

No NBA CDN calls are involved (data comes from Supabase), so no proxy is
needed. **No-op (exit 0)** if `IG_ACCESS_TOKEN` or `IG_USER_ID` is unset, or
there are no predictions for the date.

### Dry run

Needs `SUPABASE_URL` + `SUPABASE_KEY` (the read-only anon key from
`web/.env.local` is enough) and Chrome/Chromium + Pillow locally. Renders the
JPEGs, prints their paths and the caption; no upload, no table writes, no Graph
calls.

```bash
python src/scripts/post_instagram.py --dry-run --date 2026-10-20
```

Other flags: `--date YYYY-MM-DD` (default today ET), `--out DIR` (default
`instagram-out/`, gitignored; output lands in `<out>/<date>/`).

### Idempotency / re-posting

Table `instagram_posts` (`post_date` PK, `media_id`, `created_at`):

- Row for the date exists → skip.
- A claim row is inserted **before** publishing and deleted if a step before
  the final `media_publish` call fails (render, upload, container creation),
  so the next run retries; `media_id` is set on success.
- If `media_publish` itself fails (e.g. a timeout), the post may still have
  gone out, so the claim (with `media_id` NULL) is kept and the run fails red.
  The same applies to a crash between publish and the `media_id` update: that
  day is skipped, so it never double-posts.

To force a re-post of a day, delete that row in the Supabase table editor —
**only if you're sure it didn't post** (check the Instagram account first).

### Troubleshooting

A failed post shows as a red "Instagram Post" run in the Actions tab; the
predictions are unaffected (separate run). Open the run's log. Missing IG
secrets are not a failure (green no-op). Common Graph API errors:

| Error | Cause / fix |
|---|---|
| code `190` | Token expired or invalid. Generate a new system-user token (setup step 5), update `IG_ACCESS_TOKEN`. |
| code `10` / `200` | Missing permission. Check the token's permissions and that the Page, Instagram account and app are assigned to the system user; if the app is in Development mode, switch it to Live. |
| image URL not fetchable | Graph fetches each image by URL, so it must be publicly reachable. Check the `instagram` bucket exists and is public, and that `<date>/<i>.jpg` opens in a logged-out browser. |

Chrome missing locally: install `google-chrome` or `chromium`
(ubuntu-latest has Chrome preinstalled).

### Owner setup

Menu names and requirements at Meta change from time to time; treat these
steps as a guide, not gospel.

The route is Facebook Login (Instagram Business account linked to a Facebook
Page, Meta Business portfolio, System User token, graph.facebook.com). It is
used because a System User token can have expiration "Never", avoiding the
60-day token expiry of the "Instagram API with Instagram Login" route.

1. Instagram app → Settings → Account type and tools → switch to a
   professional account (Business or Creator).
2. Create a Facebook Page (any name, can stay minimal) and link the Instagram
   account to it (Page settings → Linked accounts → Instagram, or via Meta
   Business Suite).
3. Create a Meta Business portfolio at business.facebook.com; add the Page and
   the Instagram account to it (Business settings → Accounts → Pages /
   Instagram accounts).
4. developers.facebook.com → My Apps → Create app, type Business, connected to
   that business portfolio. Add the Instagram product with "API setup with
   Facebook login". The app can stay in Development mode for posting to your
   own accounts; if publishing fails with a permission error, switch it to
   Live (needs a privacy policy URL).
5. Business settings → Users → System users → Add (role Admin). "Assign
   assets": the Page and the Instagram account (full control) and the app.
   "Generate new token": pick the app, expiration "Never", permissions
   `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
   `pages_read_engagement`, `business_management`. The token is shown once —
   paste it straight into the GitHub secret, never into chat, an issue, or a
   commit.
6. Get the IG user ID (token read from an env var, not typed into the
   command); the ID is `instagram_business_account.id` in the response:
   ```bash
   curl -s -H "Authorization: Bearer $IG_ACCESS_TOKEN" "https://graph.facebook.com/v23.0/me/accounts?fields=name,instagram_business_account"
   ```
7. Run `src/supabase/migrations/002_instagram.sql` in the Supabase SQL editor
   (see [Applying a Supabase migration](#applying-a-supabase-migration)). It
   creates the public `instagram` bucket; to create it by hand instead:
   Supabase dashboard → Storage → New bucket → name `instagram`, toggle
   "Public bucket" on.
8. Add the GitHub secrets `IG_ACCESS_TOKEN` and `IG_USER_ID`.
9. Test: run the local `--dry-run` for a past date with games (e.g.
   `2026-10-20`, 3 games) and look at the JPEGs in `instagram-out/2026-10-20/`.
   Then run "Instagram Post" manually via `workflow_dispatch` (Actions tab) and
   check the Instagram account.

## Deploying the web app

**Not automatic — pushing to `main` does not update the live site.** The
site is a static export (`output: "export"` in `next.config.ts`) served from
the owner's own Plesk/nginx server (confirmed: `courtside-oracle.gerritvisser.de`
and `gerritvisser.de` both resolve to the same server, 185.45.149.138; the
live `/card` files on it date from 2026-06-19). There's a Vercel project
somewhere in this repo's history too, but what's actually serving the live
site is that Plesk server — treat Vercel as not relevant to the deploy
procedure below.

Because it's a static export, all data fetching happens client-side in the
browser directly against Supabase (anon key) — so changes to the *data*
(predictions, running record) show up immediately with no redeploy. Only
code/layout changes need the steps below.

Deploy procedure:

1. Create `web/.env.local` (gitignored, never commit it) with the two
   build-time env vars — both are public values that get baked into the
   static JS bundle, not secrets:
   ```
   NEXT_PUBLIC_SUPABASE_URL=https://pxvimjflsishbfrublwp.supabase.co
   NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon key>
   ```
2. **If this build is the first one to query `game_time_utc`**, confirm
   [migration 001 has been applied](#applying-a-supabase-migration) to the
   target Supabase project first — otherwise the `/card` page's
   `getCardPrediction()` query fails outright.
3. Build locally:
   ```bash
   cd web && npm run build
   ```
   This produces the static export in `web/out/`.
4. Manually upload the contents of `web/out/` to the
   `courtside-oracle.gerritvisser.de` subdomain's document root on the Plesk
   server.

**The CSP `frame-ancestors` header that allows `/card` to be iframed on
gerritvisser.de is set by the server/nginx config, not by the Next.js app** —
a static export can't set response headers itself (`next.config.ts`'s
`headers()` doesn't run in `output: "export"`). That header must stay
configured server-side independently of anything in this repo; it won't
survive a server/vhost change unless someone re-adds it there.

Local dev: `cd web && npm install && npm run dev`. `npm run lint` runs
`next lint`.

The `/card` route (420×260) is the standalone widget embedded as an iframe on
the portfolio site (`IcaruzSoftware/portfolio`, https://gerritvisser.de) —
the iframe points at `https://courtside-oracle.gerritvisser.de/card`, so
uploading a new build updates the embedded card too; there is nothing to
change in the portfolio repo itself unless the iframe URL changes.

## Season rollover

Nothing to run manually — season boundaries are derived from dates
everywhere (`_season_of()` / `_date_to_season()`: October or later = new
season). 2026-27: preseason from 2026-10-03, regular season opens
2026-10-20. The public running record is all-time: it accumulates across seasons and
includes the 5 retroactively seeded 2026 Finals rows from `seed_finals.py`.
If you ever want a per-season reset, reintroduce a `game_date` cutoff in
`evaluate.py`'s `_recompute_running_record`.
