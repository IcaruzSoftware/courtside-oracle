# Trailer creation playbook

Goal: turn a project into a ~30 s, high-energy promo trailer — **1080p60 MP4 with a frame-synced procedural soundtrack**.

Method: build the trailer as a web page animated with Motion → render it frame by frame on a frozen browser clock → synthesize music + SFX from the page's own timings → mux.

Reference implementation (Courtside Oracle, this repo) — read these, they are the source of truth; this file only explains what isn't obvious from them:

| File | Role |
|---|---|
| `web/app/trailer/page.tsx` | the trailer page: 7 scenes, 30.8 s, all reusable primitives |
| `tools/trailer/render.mjs` | deterministic renderer → silent MP4 |
| `tools/trailer/soundtrack.py` | procedural soundtrack → `music.wav`, `sfx.wav`, `mix.wav`, `cue-sheet.md` + self-checks |
| `tools/trailer/package.json` | renderer deps (`playwright`, `ffmpeg-static`) |
| `trailer-export/` | outputs; **untracked** (in `.git/info/exclude`), never commit media |

Stack: Next.js 15 / React 19 / Tailwind 3 (or standalone Vite + React) · `motion` ^14.4 (`motion/react`) · Playwright ^1.64 + Chromium · `ffmpeg-static` ^5.3 (bundled ffmpeg with libx264) · Python 3 + numpy/scipy/soundfile via `uv`.

For another project: copy `tools/trailer/` over, use `page.tsx` as the template for the page, and adapt the project-specific parts named in each step.

## 1. Collect facts

Read the target's README, docs and UI. Build a table `fact | value | source`: name, tagline, URL, brand colors, fonts, logos, and the real numbers. Every number on screen must come from that table.

- Never invent stats. Report derived numbers (e.g. `100 − 62.9`) and illustrative visuals (bar lengths without numbers) to the user.
- If a shown example is demo/mock data, say so — don't present it as real.
- Note remote assets (CDN images, web fonts); they need handling in step 4.

## 2. Storyboard

6–8 scenes of 4–5 s. Proven arc: cold open → data storm (count-ups) → core mechanic → hero example → proof/explainability → stats punch → logo reveal + URL (then loop).

- **Every scene duration is a multiple of 0.1 s.** At 150 BPM a 16th note is 0.1 s, so every cut lands on a musical downbeat.
- List each scene's hits (slams, flashes, shakes, count-ups) relative to scene start. They become the sound cues.
- The total `T` appears in three files: `page.tsx` (`SCENES`), `render.mjs` (`FRAMES`), `soundtrack.py` (`SCENES`/`DUR`).

## 3. Build the page

Copy the structure of `page.tsx`: a `SCENES = [{ ms, Scene }]` array, one `scene` index advanced by `setTimeout`, `<AnimatePresence>` with `key={scene}` (scenes remount on every cut, so in-scene delays are relative to scene start), a keyed `Wipe` on each cut, and the primitives `Stage` (screen shake via `shakeAt`), `Flash`, `CountUp`, `StaggerText`, the `SLAM` spring and the `EASE_OUT` curve. Swap in the target's colors, fonts and content. `motion` is the only dependency you add to the project; for a non-React project, build the page as a standalone Vite + React app.

**Renderability rules** (the renderer can't control anything else):

- Animate everything with Motion. **No CSS `@keyframes`, `transition-*` or Tailwind `animate-*`** — they ignore the fake clock.
- **No `Math.random()` / `Date` in render.** Use the deterministic `rnd(i)` (also prevents hydration mismatches in a static export).
- All timing comes from `SCENES` plus per-element `delay`.
- Layout: `fixed inset-0 overflow-hidden`, sizes in `clamp()`/`vw`, `whitespace-nowrap` per word, so it works at 1920×1080 and 375 px.
- Wrap in `<MotionConfig reducedMotion="user">` and skip shakes/flashes when `useReducedMotion()` is true.

Done when: dev server shows every scene correctly at desktop and 375 px (screenshot and look), no console errors, `scrollWidth === innerWidth`, `tsc --noEmit` and the production build pass, and grep finds none of the forbidden patterns above. For Claude: have two independent read-only reviewers check the page against the fact table and these rules before moving on.

## 4. Render the video

Install the renderer once:

```bash
npm --prefix tools/trailer install
```

```bash
npm --prefix tools/trailer exec playwright install chromium
```

Build the site, then serve the static output and leave the server running:

```bash
npm --prefix web run build
```

```bash
python3 -m http.server 8765 --bind 127.0.0.1 -d web/out
```

Render (~1850 frames, several minutes):

```bash
node tools/trailer/render.mjs trailer-export/courtside-oracle-trailer.mp4
```

For another project, edit the project-specific values at the top of `render.mjs`: the URL, the duration `T`, the logo URLs and the CDN `page.route` pattern, and the font URL.

Why `render.mjs` works the way it does — each line exists because the obvious approach failed:

| Trick | Without it |
|---|---|
| `delete Element.prototype.animate` (init script) | Motion hands transforms/opacity to the Web Animations API, which runs on the real compositor clock → frozen or mistimed animation. |
| `page.clock.install()` + `pauseAt()` | Playwright's fake clock keeps running in real time → non-deterministic frames. |
| Own `requestAnimationFrame` queue, flushed once per frame | Playwright's fake rAF ticks every 16 ms and drifts against 60 fps (16.67 ms). |
| 3 `MessageChannel` ticks before the flush | React's scheduler hasn't committed the new scene / registered its timers yet. |
| `img.decode()`, `document.fonts.ready` before frame 0 | Pop-in and fallback-font frames. |
| `page.route` + Node `fetch` for logos | Some CDNs block headless Chromium (cdn.nba.com: `ERR_HTTP2_PROTOCOL_ERROR`) → empty images. Vendoring images locally also works. |
| `addStyleTag` with the font URL | The site's own Inter `@import` lands mid-stylesheet in the Tailwind build and browsers ignore it. Drop this if the target's font loads correctly. |
| Frame time `round(f·1000/FPS)` | Accumulating 16.67 ms drifts over ~1850 frames. |

Done when (check yourself, don't trust a subagent's "done"):

- The render log shows `WAAPI animations: 0` throughout.
- `ffmpeg -i` reports 1920×1080, 60 fps, duration `T` (ffmpeg-static has no ffprobe):

```bash
"$(node -p "require('./tools/trailer/node_modules/ffmpeg-static')")" -hide_banner -i trailer-export/courtside-oracle-trailer.mp4
```

- No two consecutive frames are identical (prints nothing if OK):

```bash
"$(node -p "require('./tools/trailer/node_modules/ffmpeg-static')")" -v error -i trailer-export/courtside-oracle-trailer.mp4 -f framemd5 - | awk '!/^#/{print $6}' | uniq -d | head
```

- Stills from the middle of every scene look right (`-ss <t> -frames:v 1 still.png`). A still taken mid count-up or mid flash looks broken but isn't — re-take it 0.5–1 s later before calling it a bug.

## 5. Synthesize the soundtrack

```bash
uv venv tools/trailer/.venv
```

```bash
uv pip install --python tools/trailer/.venv numpy scipy soundfile
```

```bash
tools/trailer/.venv/bin/python tools/trailer/soundtrack.py
```

(`uv` because `python3 -m venv` fails on systems without ensurepip.) Output goes to `trailer-export/audio/`; the script prints `ok` only if every self-check passes. Fixed seeds: same input, bit-identical output.

`soundtrack.py` is organized so that only the timeline parts are project-specific:

| Part | Project-specific? |
|---|---|
| `SCENES`, scene starts `S1…S7`, `DUR` | **yes** — copy from `page.tsx` |
| `cue()` registry → `cue-sheet.md` | no (every sound registers itself; never hand-write the sheet) |
| `cubic_bezier` mirrors of `EASE_OUT` and the wipe easing | only if the page's curves change |
| DSP helpers, instruments (kick, clap, 808 hat, crash, 808 bass, pluck, brass, pad), `Bus`, reverb IR | no |
| Chords/hook (F minor), patterns `DRIVE` (full-time) / `TRAP` (half-time) | optional (taste) |
| `compose_music()` / `compose_sfx()` — one block per scene | **yes** — rewrite per scene |
| Mix, ducking (−4 dB under impacts), soft-clip, limiter, −14 LUFS, self-checks | no |

Writing the per-scene blocks:

- Cue time = scene start + the value in `page.tsx`: a `Stage shakeAt` entry → `impact()`; `CountUp delay/duration` → `countup()`; staggered bars → one `zap()` each; letters → a click every 35 ms; each scene start → `wipe_whoosh()`.
- Cue a slam at its **visual hit** (the shake + flash time), not at its `delay` — the spring is still in flight at `delay`.
- Energy arc: tense intro with a `hit()` per slam → drop on the first cut → half-time `TRAP` for explanatory scenes, `DRIVE` for punchy ones → a gap of silence before the biggest stamp → riser → final `hit(big=True)` on the name slam → fade to silence by `T`.

Done when the script prints `ok`. It checks: length exactly `T`, 48 kHz stereo; peak below −0.5 dBFS; about −14 LUFS; every big impact's transient within ±10 ms of its cue.

Be honest in the report: this gives a tight, punchy *procedural* trailer sound, not library or orchestral quality, and **nobody (including Claude) has listened to it** — it was tuned by measurement. For produced music, an AI service (e.g. the Creative Claw plugin: ElevenLabs SFX + Mureka music) can replace the bed; keep the cue sheet to sync it.

## 6. Mux and deliver

```bash
"$(node -p "require('./tools/trailer/node_modules/ffmpeg-static')")" -y -i trailer-export/courtside-oracle-trailer.mp4 -i trailer-export/audio/mix.wav -map 0:v -map 1:a -c:v copy -c:a aac -b:a 320k -shortest -movflags +faststart trailer-export/courtside-oracle-trailer-sound.mp4
```

Deliver the silent and sound MP4s, the stems (`music.wav`, `sfx.wav`, `mix.wav`) and `cue-sheet.md`. In the report: file paths, duration/fps/resolution, loudness, the flagged derived/illustrative/demo facts, and the "nobody listened" note. Commit nothing unless asked.

## Workflow for Claude

Do steps 1–3 yourself or with one coder agent, then freeze the page. Steps 4 and 5 are independent — run them as two parallel subagents, each with a self-contained brief (paths, `T`, scene/hit table, rules, expected outputs). Verify their outputs yourself before delivering.

## Pitfalls

- **Changing any timing** in `page.tsx` means updating `render.mjs` (`FRAMES`) and `soundtrack.py` (`SCENES` and the cue times in the per-scene blocks), then re-rendering and re-synthesizing. `soundtrack.py` asserts the total, not the in-scene delays.
- Scene durations that aren't multiples of 0.1 s fall off the 150 BPM grid.
- Headless Chromium defaults to no reduced-motion preference; setting `reducedMotion: 'reduce'` in Playwright removes the shakes and flashes from the render.
