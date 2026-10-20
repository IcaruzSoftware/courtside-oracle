# Courtside Oracle v2: improvement plan (lessons from Riftside Oracle)

Written 2026-10-16 for a fresh session on the owner's home PC. That PC has the
full stats.nba.com bootstrap data (box scores) locally. Read this file first,
then [CLAUDE.md](CLAUDE.md) and [docs/model.md](docs/model.md) ("Honest
caveats"). This file is the brief; where it conflicts with older docs, it wins.

## Why

The League of Legends fork, [IcaruzSoftware/riftside-oracle](https://github.com/IcaruzSoftware/riftside-oracle),
rebuilt this architecture and measured carefully what actually predicts. See
its `HANDOFF.md`. Three findings carry over to Courtside:

1. **A results-based outcome Elo was by far the strongest signal.**
   - Riftside has the same within-game skill ELOs that Courtside has, plus an outcome Elo: classic Elo on wins and losses, per player.
   - The outcome Elo diff was the #1 feature.
   - On the major leagues it held almost all of the predictive power. XGBoost on top added only a little.
   - **Courtside has no outcome Elo at all.** Its 7 skill ELOs rank players within a game, and none of them learns directly from who won.
2. **Three refinements improved the outcome Elo measurably** (walk-forward validated, significant):
   - a margin-of-victory multiplier on K
   - a 20% off-season pull toward the mean
   - a doubled K for a player's first 20 games

   The NBA has real point margins, so the margin-of-victory part should work even better here.
3. **Training must see exactly what live sees.**
   - Riftside enforces one feature path with a day-level point-in-time rule. Its training features are provably equal to its live features (there are tests for it).
   - Courtside documents several train/serve mismatches (see below). They make the 67.5% backtest optimistic.
   - Fixing them makes the backtest honest and should bring live accuracy closer to it.

Nothing guarantees a gain. Measure first (Phase A/B), then build.

## Current Courtside facts (from the docs)

- **Model:** XGBoost + Platt. About 100 features in 9 groups: ELO (7 skills + general), rolling team stats, home/away splits, rest, H2H, player availability, efficiency diff, player form, streaks.
- **Backtest:** 67.5% accuracy, AUC 0.729, Brier 0.209, log loss 0.606. Measured on 2,116 test games, out of 14,108 games from 2015-16 to 2025-26.
- **Known mismatches** (`docs/model.md`, "Honest caveats"):
  - **ELO lineups:** training uses the players who actually played 10+ minutes. Live uses the last-known roster from `player_elo_current`.
  - **PPG weights / star-out:** training uses the **full final-season** stats file, which includes games after the one being featured (look-ahead). Live uses season-to-date.
  - **Availability features:** real in training, always neutral live, because there is no injury feed. The re-downloaded bootstrap data has no `boxscore_summary`, so a retrain on it loses the signal entirely.
  - **Optuna:** its CV runs on train+calibration (85%).
  - **Daily CDN updates:** they lack `defensiveRating` and tracking data, so defense degrades and hustle freezes after the bootstrap.
- **Status:** live. The NBA 2026-27 season starts around 2026-10-20, the daily workflows commit state every morning, and the public running record is all-time (includes the 5 seeded 2026 Finals rows).

## Ground rules

1. **Don't break the live pipeline.** Work on a branch, or keep `main` deployable at every commit. A new model only goes live when the owner says so.
2. **Measurement protocol** (this is what made Riftside's numbers trustworthy):
   - Choose every setting on **validation only**. Use walk-forward windows: train on everything before a window, score the window. Use several seasons before the test season.
   - **Freeze the test slice:** the most recent full season(s). Score it **once** at the end, for the final configuration. If you must look again after a bug fix, say so in the report.
   - Report against baselines, with paired-bootstrap 95% CIs:
     - (a) home team always wins
     - (b) outcome Elo alone, `p = 1/(1+10^(-(diff+HCA)/400))`
     - (c) the current committed model
   - Accept a change only if the CI says it isn't noise.
   - Lead with **game-winner accuracy**, which is what the site's record counts. Log loss is the less noisy secondary metric.
3. **One feature path.** Training and live call the same functions on the same data shape. Add a test that training-mode features equal live-mode features for the same state.
4. **Day-level point-in-time.** A game on day d uses only data from before day d. ELO is "as of the start of day d", so no same-day results.
5. **Committed-state contract.** Any new state file needs its `.gitignore` negation and a mention in CLAUDE.md. Never commit raw data.
6. Commit per phase. Push or deploy only when the owner asks. Python 3.12, local `.venv`. `scikit-learn==1.8.0` and `xgboost==3.2.0` are pinned for the pickle; re-pin both together only at a retrain.

## Phases

### Phase A: evaluation harness and cheap fixes

- **Rewrite the split in `train.py` to:**
  - run Optuna CV on the **train slice only** (not train+calibration)
  - make the objective **log loss** instead of AUC
  - set `tree_method="hist"`
  - cap `n_jobs` at about half the cores; all cores was about 6× slower in Riftside
- **Add to `train_metrics.json`:**
  - baselines (a) and (b)
  - per-season metrics
  - a GATE line: the model must beat baseline (b) on both log loss and accuracy
- **Write one evaluation script that:**
  - reproduces the current committed model's metrics on a fixed test season
  - computes paired-bootstrap CIs, resampling whole days, not single games
- ✅ The current model's numbers are reproduced, and the harness runs.

### Phase B: team outcome Elo (cheap, decides whether the rest is worth it)

- **Data:** the committed game logs `src/data/raw/game_log_*.csv` have `GAME_ID, GAME_DATE, TEAM_ID, MATCHUP, WL, PTS, PLUS_MINUS`. MATCHUP is `"XXX vs. YYY"` for home and `"XXX @ YYY"` for away. That is enough; no box scores are needed.
- **The rating:** team Elo with:
  - a home-court term (HCA)
  - a margin-of-victory multiplier; a FiveThirtyEight-style starting point is `((MOV+3)^0.8) / (7.5 + 0.006·elo_diff_of_winner)`
  - K around 20
  - an off-season regression toward the mean (start at 0.25; Riftside's best was 0.2)

  Choose all of these on validation.
- **Evaluate in two ways:**
  - (1) the Elo alone as baseline (b)
  - (2) as extra features (`home/away/diff_team_outcome_elo`) in the existing model
- ✅ A report with numbers. If the team Elo alone is already close to the model, or the feature adds a significant gain, continue to Phase C.

### Phase C: per-player outcome Elo (needs the box scores on the home PC)

- **Rating per player:**
  - A team rating = **minutes-weighted** mean of its players' outcome Elo. In Riftside it is a plain mean, because all 5 play the whole game; NBA minutes vary.
  - E as in classic Elo.
  - Each player moves by `K · mov_mult · (result − E)`, weighted by their minutes share.
  - New players start at a prior, for example the mean of rookies or the team mean.
- **The three refinements:**
  - margin of victory
  - off-season pull of 0.2 toward the mean
  - K ×2 for a player's first ~20 games

  Validate each one separately.
- **Pitfalls Riftside hit, avoid them up front:**
  - **Take the pre-game snapshot BEFORE the off-season pull.** Use the pulled value only for E and the update. Otherwise training sees pulled values that live never sees, and a December as-of lookup leaks January's pull. Riftside's reviewers caught exactly this bug.
  - With a per-player K, the update is no longer zero-sum. Document that, and test the mixed case.
  - Guard the margin multiplier against NaN or zero inputs, so one bad row can't write NaN into the state.
  - Incremental `update_elo` must equal a full rebuild, including across a season boundary. Port Riftside's parity tests.
  - The idempotency check must not rely only on "recent snapshots". `daily_state` should pass only games not yet in the game logs.
- **Live:** `daily_state.py` updates the outcome Elo from the CDN box score. That box score has minutes, points and plus/minus, which is enough for the outcome Elo. Only the skill ELOs degrade on CDN data.
- ✅ Tests, plus a full rebuild. Show the top-10 players by outcome Elo for a sanity check.

### Phase D: make training equal live

- **Point-in-time:** day-level as-of ELO lookup, as in Riftside's `features.py`. Each player's first pre-game snapshot with date ≥ d, else current. Live reads `player_elo_current`.
- **PPG weights / star-out:** compute season-to-date stats **as of day d** in training. Drop the full-season file.
- **Lineups: choose one definition that both modes can compute.** Two options:
  - **(a) Expected rotation:** the players with the most minutes in the team's last N games before d. The same in both modes.
  - **(b) Actual players in training, last-known roster live:** this keeps the current mismatch. Riftside accepted this for LoL, where lineups are announced and stable. NBA rotations change more.

  Recommendation: (a). Validate both.
- **Availability features: an owner decision.**
  - **(a) Drop them.** This is honest, and there is no live signal anyway.
  - **(b) Add a live injury source.** For example the NBA's official injury report, published as PDFs on game days. Verify reachability and terms first. Then the feature must be computed identically in training (from what was known before the game), which is hard historically.

  Recommendation: (a) now, (b) as a separate project.
- ✅ A test that training features equal live features. Rebuild the dataset and retrain. Report against Phase A's baselines. The backtest number may drop, and that is the point: it becomes honest.

### Phase E: final model, gate, handover to the owner

- Run the full retrain with the chosen configuration, then a single test-slice evaluation:
  - model vs (a), (b) and the current model
  - CIs included
  - per season
- Update `docs/model.md`, `docs/elo.md` and CLAUDE.md (known limitations, state contract).
- Also update the hardcoded metrics text in `web/app/(main)/page.tsx`, but only when deploying.
- Give the owner a short decision memo: deploy now or at a quiet point, expected live effect, and the risks.

## Expectations (be honest with the owner)

- **The per-game ceiling.** NBA single-game accuracy has a natural limit. Upsets, rest decisions and injuries known only late in the day all cap it. ~67–69% is a typical ceiling for pre-game models. **Treat that as an estimate, not a sourced number.**
- **The current backtest is inflated.** 67.5% is optimistic because of look-ahead and real availability data. An honest v2 might backtest lower but do better live.
- **Where the biggest expected gain is:** the outcome Elo (Phase B/C) and the end of the train/serve mismatches (Phase D). More features are not the lever. In Riftside, a broad search found nothing beyond the outcome Elo: team Elo on top of player Elo, strength of schedule, ensembles, sample weights and pruning all added nothing.

## Working style the owner expects

- **Orchestration:** the owner's global CLAUDE.md asks for implementation to go to subagents: coder for normal and hard programming, writer for simple code and docs, chore for mechanical work.
- **Reviews:**
  - Each step gets a read-only review.
  - Each phase is accepted only when **two independent reviewers** both report "IN ORDNUNG".
  - Mutation-check new tests: break the code on purpose and confirm the test fails.
- **Reporting:** short, concrete, with numbers. Accuracy first.
