#!/usr/bin/env python3
"""Procedural soundtrack for the 30.8 s promo trailer (web/app/trailer/page.tsx).

Everything is synthesized here: no samples, no copyrighted audio.
Writes trailer-export/audio/{music,sfx,mix}.wav (48 kHz, stereo, 24-bit, exactly 30.8 s) and
trailer-export/audio/cue-sheet.md, then self-checks duration, peak, loudness and cue alignment.

    python soundtrack.py          # needs numpy, scipy, soundfile

Music: 150 BPM (16th = 0.1 s), F minor hybrid trap / sports anthem. Every scene cut
in page.tsx is a multiple of 0.1 s, so the groove is re-anchored to a downbeat at
each cut (edit-style bar truncation). Off-grid slams (screen shakes) get tempo-free
hits layered over the groove.
"""
import pathlib

import numpy as np
import soundfile as sf
from scipy.ndimage import minimum_filter1d, uniform_filter1d
from scipy.signal import butter, fftconvolve, lfilter, resample_poly, sosfilt

SR = 48000
DUR = 30.8
N = round(SR * DUR)
OUT = pathlib.Path(__file__).resolve().parents[2] / "trailer-export" / "audio"  # untracked
STEP = 60 / 150 / 4  # 16th note at 150 BPM = 0.1 s
rng = np.random.default_rng(1977)

# ---------------------------------------------------------------- timeline (page.tsx)
SCENES = [("ColdOpen", 4000), ("DataStorm", 4200), ("EloScene", 4200), ("Matchup", 5000),
          ("Shap", 4400), ("Stats", 4200), ("LogoReveal", 4800)]
STARTS = [sum(ms for _, ms in SCENES[:i]) / 1000 for i in range(len(SCENES))]
S1, S2, S3, S4, S5, S6, S7 = STARTS  # 0, 4.0, 8.2, 12.4, 17.4, 21.8, 26.0
assert abs(sum(ms for _, ms in SCENES) / 1000 - DUR) < 1e-9

CUES = []  # (abs time, event, sound) -> cue-sheet.md


def cue(t, event, sound):
    CUES.append((round(t, 3), event, sound))


def cubic_bezier(x1, y1, x2, y2):
    s = np.linspace(0, 1, 4001)
    bx = 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s ** 2 * x2 + s ** 3
    by = 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s ** 2 * y2 + s ** 3
    return (lambda x: np.interp(x, bx, by)), (lambda y: np.interp(y, by, bx))


EASE_OUT, EASE_OUT_INV = cubic_bezier(0.16, 1, 0.3, 1)  # page.tsx EASE_OUT
WIPE_EASE, _ = cubic_bezier(0.7, 0, 0.3, 1)               # Wipe transition

# ---------------------------------------------------------------- DSP helpers


def secs(n):
    return np.arange(n) / SR


def mtof(m):
    return 440.0 * 2 ** ((np.asarray(m, float) - 69) / 12)


def noise(n, seed=None):
    return (np.random.default_rng(seed) if seed is not None else rng).standard_normal(n)


def filt(x, kind, fc, order=2):
    return sosfilt(butter(order, fc, kind, fs=SR, output="sos"), x, axis=0)


def lp(x, fc, order=2):
    return filt(x, "lowpass", fc, order)


def hp(x, fc, order=2):
    return filt(x, "highpass", fc, order)


def bp(x, lo, hi, order=2):
    return filt(x, "bandpass", [lo, hi], order)


def tvf(x, fc, kind="lowpass", width=1.6, block=64):
    """Time-varying Butterworth (cutoff or band centre per sample), block-wise with state carry."""
    fc = np.broadcast_to(np.asarray(fc, float), x.shape[:1])
    y = np.empty_like(x)
    zi = np.zeros((1 if kind == "lowpass" else 2, 2))
    for i in range(0, len(x), block):
        c = float(np.clip(fc[min(i + block // 2, len(x) - 1)], 30, 0.45 * SR / (width if kind == "bandpass" else 1)))
        wn = [c / width, c * width] if kind == "bandpass" else c
        sos = butter(2, wn, kind, fs=SR, output="sos")
        y[i:i + block], zi = sosfilt(sos, x[i:i + block], zi=zi)
    return y


def blsaw(freq, n, phase0=0.0):
    """PolyBLEP band-limited sawtooth; freq scalar or per-sample array."""
    dt = np.broadcast_to(np.asarray(freq, float), (n,)) / SR
    ph = (phase0 + np.cumsum(dt)) % 1.0
    y = 2 * ph - 1
    m = ph < dt
    u = ph[m] / dt[m]
    y[m] -= u + u - u * u - 1
    m = ph > 1 - dt
    u = (ph[m] - 1) / dt[m]
    y[m] -= u * u + u + u + 1
    return y


def sine(freq, n):
    return np.sin(2 * np.pi * np.cumsum(np.broadcast_to(np.asarray(freq, float), (n,))) / SR)


def decay(t, tau, start=0.0):
    return np.where(t >= start, np.exp(-np.clip(t - start, 0, None) / tau), 0.0)


def fade_tail(x, ms=8):
    k = min(len(x), int(ms * SR / 1000))
    x[-k:] *= np.linspace(1, 0, k)[:, None] if x.ndim == 2 else np.linspace(1, 0, k)
    return x


def stereo(x, pan=0.0):
    a = (np.asarray(pan, float) + 1) * np.pi / 4
    if x.ndim == 2:  # stereo source: pan acts as balance
        return x * np.array([np.cos(a), np.sin(a)]) * np.sqrt(2)
    return np.stack([x * np.cos(a), x * np.sin(a)], 1) * np.sqrt(2)


def make_ir(rt60, length, lp_hz, seed):
    n = int(length * SR)
    t = secs(n)
    ir = noise(n * 2, seed).reshape(n, 2) * (10 ** (-3 * t / rt60))[:, None]
    ir = lp(ir, lp_hz, 1) * np.minimum(1, t / 0.004)[:, None]
    ir = np.concatenate([np.zeros((int(0.012 * SR), 2)), ir])
    return ir / np.sqrt((ir ** 2).sum(0))


class Bus:
    """Dry + reverb-send stereo bus over the whole 30.8 s timeline."""

    def __init__(self):
        self.dry = np.zeros((N, 2))
        self.wet = np.zeros((N, 2))

    def add(self, sig, t, gain=1.0, pan=0.0, send=0.0):
        sig = stereo(sig, pan) * gain
        i0 = round(t * SR)
        a, b = max(0, -i0), min(len(sig), N - i0)
        if b <= a:
            return
        self.dry[i0 + a:i0 + b] += sig[a:b]
        if send:
            self.wet[i0 + a:i0 + b] += sig[a:b] * send

    def render(self, ir):
        return self.dry + np.stack([fftconvolve(self.wet[:, c], ir[:, c])[:N] for c in range(2)], 1)


# ---------------------------------------------------------------- instruments (music)

def kick(punch=1.0, tail=0.3):
    n = int(0.6 * SR)
    t = secs(n)
    body = sine(43 + 170 * np.exp(-t / 0.025) + 30 * np.exp(-t / 0.1), n) * np.exp(-t / tail)
    click = hp(noise(n, 11), 3000) * np.exp(-t / 0.0025) * 0.35 * punch
    return fade_tail(np.tanh(2.5 * (body + click)) / np.tanh(2.5))


def clap(seed=0, pitch=1.0):
    """Layered clap (4 noise bursts) + snare (tone + noise)."""
    n = int(0.5 * SR)
    t = secs(n)
    env = sum(decay(t, 0.005, d) for d in (0, 0.008, 0.017)) + decay(t, 0.12, 0.026)
    burst = bp(noise(n, 100 + seed), 1000 * pitch, 7000) * env * 0.8
    snare = sine(190 * pitch, n) * np.exp(-t / 0.06) * 0.7 + hp(noise(n, 200 + seed), 2000) * np.exp(-t / 0.14) * 0.45
    return fade_tail(burst + snare)


METAL = [205.3, 304.4, 369.6, 522.7, 540.0, 800.0]  # TR-808 cymbal oscillator ratios


def metal(n, seed):
    t = secs(n)
    ph = np.random.default_rng(seed).uniform(0, 2 * np.pi, len(METAL))
    return sum(np.sign(np.sin(2 * np.pi * f * t + p)) for f, p in zip(METAL, ph)) / 3


def hat(seed=0, tau=0.03):
    n = int((tau * 8 + 0.01) * SR)
    t = secs(n)
    x = hp(bp(metal(n, seed) * 0.6 + noise(n, 300 + seed) * 0.5, 6000, 16000), 7000)
    return fade_tail(x * np.exp(-t / tau) * 2.0)


def crash(seed=0, tau=0.8, length=2.6):
    n = int(length * SR)
    t = secs(n)
    env = np.exp(-t / tau) * np.minimum(1, t / 0.002)
    ch = [lp(hp(metal(n, seed + c) * 0.4 + noise(n, 400 + seed + c), 3500), 13000) * env for c in range(2)]
    return fade_tail(np.stack(ch, 1), 40)


def b808(midi, dur, glide_from=None, gtime=0.07, tau=None):
    n = int((dur + 0.03) * SR)
    t = secs(n)
    f1 = mtof(midi)
    f = f1 if glide_from is None else f1 + (mtof(glide_from) - f1) * np.exp(-t / gtime)
    x = sine(f, n)
    x += 0.15 * sine(2 * f, n)
    env = np.minimum(1, t / 0.004) * np.exp(-t / (tau or max(0.3, dur))) * np.clip((dur + 0.03 - t) / 0.03, 0, 1)
    return np.tanh(2.2 * x * env) / np.tanh(2.2)


def pluck(midi, dur=0.32, bright=1.0):
    """Dark detuned-saw pluck, filter envelope, stereo detune."""
    n = int((dur + 0.05) * SR)
    t = secs(n)
    f = mtof(midi)
    cutoff = 250 + 5200 * bright * np.exp(-t / 0.06)
    env = np.minimum(1, t / 0.0015) * np.exp(-t / 0.16)
    ch = [tvf(blsaw(f * 2 ** (d / 1200), n) + 0.5 * blsaw(f * 2 ** (-d / 2400), n, 0.3), cutoff) * env
          for d in (-9, 9)]
    return fade_tail(np.stack(ch, 1) * 0.6)


def brass(midis, dur=0.5):
    """Saw-stack brass stab: fast filter open, slight pitch scoop, saturation."""
    n = int((dur + 0.45) * SR)
    t = secs(n)
    cutoff = 300 + 3800 * (1 - np.exp(-t / 0.012)) * (0.45 + 0.55 * np.exp(-t / 0.18))
    scoop = 2 ** (-0.35 / 12 * np.exp(-t / 0.03))
    env = np.minimum(1, t / 0.005) * (0.7 + 0.3 * np.exp(-t / 0.08)) * np.where(t < dur, 1, decay(t, 0.12, dur))
    ch = []
    for detunes in ((-12, 0, 11), (-7, 4, 13)):
        x = sum(blsaw(mtof(m) * scoop * 2 ** (d / 1200), n, rng.uniform()) for m in midis for d in detunes)
        ch.append(tvf(x, cutoff) * env / (len(midis) * 1.5))
    return fade_tail(np.tanh(1.6 * np.stack(ch, 1)), 20)


def pad(midis, dur, cutoff=1100, attack=0.15):
    n = int((dur + 0.3) * SR)
    t = secs(n)
    env = np.minimum(1, t / attack) * np.clip((dur + 0.3 - t) / 0.3, 0, 1)
    ch = [lp(sum(blsaw(mtof(m) * 2 ** (d / 1200), n, rng.uniform()) for m in midis), cutoff) * env / len(midis)
          for d in (-7, 7)]
    return np.stack(ch, 1)


# chord table: 808 root, pad voicing, brass voicing (F minor; C major = harmonic-minor V)
CH = {
    "Fm": (29, [53, 56, 60, 65], [41, 53, 60, 65, 68, 72]),
    "Db": (37, [49, 53, 56, 61], [37, 49, 56, 61, 65, 68]),
    "Eb": (39, [51, 55, 58, 63], [39, 51, 58, 63, 67, 70]),
    "C": (36, [48, 52, 55, 60], [36, 48, 55, 60, 64, 67]),
    "Bbm": (34, [46, 49, 53, 58], [34, 46, 53, 58, 61, 65]),
}
HOOK = {  # (16th step, midi) per bar
    "Fm": [(0, 72), (3, 68), (6, 65), (8, 72), (10, 73), (12, 72), (14, 68)],
    "Db": [(0, 73), (3, 68), (6, 65), (8, 73), (10, 75), (12, 73), (14, 72)],
    "Eb": [(0, 75), (3, 70), (6, 67), (8, 75), (10, 77), (12, 75), (14, 72)],
    "C": [(0, 76), (3, 72), (6, 67), (8, 76), (10, 77), (12, 76), (14, 71)],
    "Bbm": [(0, 73), (3, 70), (6, 65), (8, 73), (10, 75), (12, 73), (14, 72)],
}
DRIVE = {"kick": [0, 7, 10], "clap": [4, 12], "ohat": [14]}  # full-time anthem
TRAP = {"kick": [0, 11], "clap": [8], "ohat": [6]}           # half-time trap

KICK, KICK_BIG = kick(), kick(punch=1.6, tail=0.45)
CLAPS = [clap(i) for i in range(4)]
HATS = [hat(i) for i in range(6)]
OHAT = hat(9, tau=0.12)

music, pumped = Bus(), Bus()  # pumped = pads, sidechained to the kick
KICK_TIMES = []
IR_MUSIC = make_ir(1.4, 2.0, 7000, 5)


def k(t, big=False, gain=0.9):
    music.add(KICK_BIG if big else KICK, t, gain)
    KICK_TIMES.append(t)


def snare(t, gain=0.85, i=0, pitch=1.0):
    music.add(clap(i, pitch) if pitch != 1.0 else CLAPS[i % 4], t, gain, pan=0.04, send=0.25)


def cymbal(t, gain=0.22, seed=0):
    music.add(crash(seed), t, gain * 0.75, send=0.2)


def stab(t, chord, dur=0.45, gain=0.32):
    music.add(brass(CH[chord][2], dur), t, gain * 3.2, send=0.35)


def bar(t0, chord, mode, steps=16, roll=False, hook=True, hats=True, kicks=None):
    """One (possibly truncated) bar of groove starting at t0."""
    root = CH[chord][0]
    ks = [s for s in (kicks if kicks is not None else mode["kick"]) if s < steps]
    for s in ks:
        k(t0 + s * STEP)
    for i, s in enumerate(ks):  # 808 follows the kick, held until the next kick
        nxt = ks[i + 1] if i + 1 < len(ks) else steps
        glide = root + 12 if (mode is DRIVE and s == 10) or (mode is TRAP and s == 11) else None
        music.add(b808(root, (nxt - s) * STEP - 0.01, glide_from=glide), t0 + s * STEP, 0.36)
    for i, s in enumerate(p for p in mode["clap"] if p < steps):
        snare(t0 + s * STEP, i=i)
    if hats:
        for s in range(steps):
            if roll and s >= 12:
                continue
            if s in mode["ohat"]:
                music.add(OHAT, t0 + s * STEP, 0.09, pan=0.25)
                continue
            vel = (0.18, 0.08, 0.12, 0.08)[s % 4]
            music.add(HATS[(s * 7) % 6], t0 + s * STEP, vel, pan=0.3 if s % 2 else -0.2)
        if roll and steps > 12:  # 32nd-triplet hat roll over the last beat, panned across
            for j in range(6):
                music.add(HATS[j], t0 + 12 * STEP + j * 4 * STEP / 6, 0.06 + 0.018 * j, pan=-0.6 + 0.24 * j)
    pumped.add(pad(CH[chord][1], steps * STEP, cutoff=2000), t0, 0.34)
    if hook:
        for s, m in HOOK[chord]:
            if s < steps:
                music.add(pluck(m), t0 + s * STEP, 0.55, pan=-0.15, send=0.3)
                # ping-pong echo (3/16 later, quieter, opposite side)
                music.add(pluck(m, bright=0.5), t0 + (s + 3) * STEP, 0.12, pan=0.7, send=0.3)


def hit(t, chord, big=False, dur=0.45, crash_gain=0.22, label="", bass_dur=0.9):
    """Tempo-free musical hit: kick + 808 + brass stab (+ crash)."""
    k(t, big=True)
    music.add(b808(CH[chord][0], bass_dur if not big else 2.6, tau=0.5 if not big else 1.1), t, 0.42)
    stab(t, chord, dur, 0.34 if not big else 0.42)
    if crash_gain:
        cymbal(t, crash_gain, seed=int(t * 10))
    cue(t, label or "music hit", f"music: kick + 808 + brass stab ({chord})")


def snare_roll(times, g0=0.15, g1=0.5, p0=1.0, p1=1.35):
    for j, t in enumerate(times):
        x = j / max(1, len(times) - 1)
        snare(t, g0 + (g1 - g0) * x ** 1.5, i=j, pitch=p0 + (p1 - p0) * x)


def compose_music():
    # S1 ColdOpen: sub drone + dark pad, a hit per "EVERY ..." slam, snare build into the drop
    n = int(4.0 * SR)
    t = secs(n)
    swell = np.minimum(1, t / 2.5) * np.clip((3.88 - t) / 0.08, 0, 1)
    music.add((sine(mtof(29), n) + 0.25 * sine(mtof(41), n)) * swell * 0.35, S1)
    pumped.add(pad(CH["Fm"][1], 3.8, cutoff=500, attack=1.5), S1, 0.22)
    cue(S1, "ColdOpen starts", "music: F1 sub drone + low-passed Fm pad swell")
    for h, chord in zip((0.58, 1.63, 2.68), ("Fm", "Db", "C")):
        hit(S1 + h, chord, label="ColdOpen slam (shake)")
    roll = [2.8, 3.0, 3.2, 3.3, 3.4, 3.5] + list(np.arange(3.55, 3.86, 0.05))
    snare_roll([S1 + r for r in roll])
    cue(S1 + 2.8, "build into drop", "music: snare roll 8ths->16ths->32nds, pitch rising; gap 3.88-4.0")

    # S2 DataStorm: THE DROP, full-time anthem groove, stabs on the number slams
    hit(S2, "Fm", crash_gain=0.3, label="DROP (DataStorm cut)", bass_dur=0.69)  # bar() skips its step-0 kick
    bar(S2, "Fm", DRIVE, hook=False, kicks=[7, 10])
    bar(S2 + 16 * STEP, "Db", DRIVE, roll=True, hook=False)
    bar(S2 + 32 * STEP, "Eb", DRIVE, steps=10, hook=False, hats=False, kicks=[0])
    snare_roll([S2 + (34 + j) * STEP for j in range(8)], 0.18, 0.45, 1.0, 1.2)
    for h, chord in zip((0.40, 1.20, 2.00), ("Fm", "Fm", "Db")):
        stab(S2 + h, chord, 0.22, 0.24)
        cue(S2 + h, "DataStorm number slam (shake, on the snare)", f"music: short brass stab ({chord}) on the clap")
    cue(S2 + 3.4, "fill into EloScene", "music: 16th snare fill")

    # S3 EloScene: half-time trap + hook pluck
    cymbal(S3, 0.16, 3)
    bar(S3, "Fm", TRAP)
    bar(S3 + 16 * STEP, "Db", TRAP, roll=True)
    bar(S3 + 32 * STEP, "C", TRAP, steps=10)
    cue(S3, "EloScene cut", "music: half-time trap groove + dark pluck hook (ping-pong echo)")

    # S4 Matchup: anthem groove, stabs on the logo slams, build during the bar race, stop-time PICK
    cymbal(S4, 0.26, 4)
    bar(S4, "Fm", DRIVE, hook=False, steps=13)
    stab(S4 + 0.40, "Fm", 0.3, 0.3)
    stab(S4 + 0.62, "Fm", 0.3, 0.3)
    for tt, lab in ((0.40, "BOS logo slam (shake)"), (0.62, "VS slam (shake + green flash)")):
        cue(S4 + tt, lab, "music: brass stab (Fm)")
    # 1.3-2.7 s bar race: claps on every 8th then 16th, hats 32nd, 808 sliding up
    for s in range(13, 27):
        if s % 4 == 0:
            k(S4 + s * STEP, gain=0.6)
        music.add(HATS[s % 6], S4 + s * STEP, 0.1, pan=-0.3)
        music.add(HATS[(s + 3) % 6], S4 + (s + 0.5) * STEP, 0.07, pan=0.3)
    snare_roll([S4 + s * STEP for s in list(range(13, 21, 2)) + list(range(21, 27))], 0.18, 0.5, 1.0, 1.3)
    music.add(b808(29, 1.4, glide_from=24, gtime=0.5), S4 + 1.3, 0.45)
    cue(S4 + 1.3, "probability bar race starts", "music: build (snare 8ths->16ths, double-time hats), 808 slides up")
    cue(S4 + 2.7, "bar race ends", "music: stop-time gap 2.7-3.05 s")
    hit(S4 + 3.05, "Fm", big=False, dur=0.6, crash_gain=0.3, label="PICK stamp (shake + white flash)")
    bar(S4 + 36 * STEP, "Eb", DRIVE, steps=8, kicks=[0, 7])
    bar(S4 + 44 * STEP, "C", DRIVE, steps=6, kicks=[0])
    cue(S4 + 3.6, "groove resumes", "music: anthem groove + hook (Eb -> C)")

    # S5 Shap: half-time trap + hook
    cymbal(S5, 0.16, 5)
    bar(S5, "Db", TRAP)
    bar(S5 + 16 * STEP, "Bbm", TRAP, roll=True)
    bar(S5 + 32 * STEP, "C", TRAP, steps=12)
    cue(S5, "Shap cut", "music: half-time trap + hook (Db -> Bbm -> C)")

    # S6 Stats: full energy, stabs on the stat slams, then the build into the logo
    cymbal(S6, 0.28, 6)
    bar(S6, "Fm", DRIVE)
    bar(S6 + 16 * STEP, "Db", DRIVE, steps=12)
    for h, chord in zip((0.3, 1.35, 2.15), ("Fm", "Fm", "Db")):
        stab(S6 + h, chord, 0.3, 0.3)
        cue(S6 + h, "Stats slam (shake + flash)", f"music: brass stab ({chord})")
    k(S6 + 28 * STEP, big=True)
    music.add(b808(36, 1.2, glide_from=29, gtime=0.6), S6 + 28 * STEP, 0.5)
    snare_roll([S6 + 2.8 + j * 0.1 for j in range(6)] + list(S6 + np.arange(3.4, 4.06, 0.05)), 0.15, 0.55, 1.0, 1.5)
    pumped.add(pad(CH["C"][1], 1.3, cutoff=2500, attack=0.8), S6 + 2.8, 0.18)
    cue(S6 + 2.8, "build into LogoReveal", "music: snare roll 16ths->32nds over C, 808 slides F->C")

    # S7 LogoReveal: drop-out, reverse swell, FINAL hit on ORACLE, long tail
    n = int(1.0 * SR)
    music.add(sine(mtof(29), n) * np.minimum(1, secs(n) / 0.2) * 0.25, S7)
    rev = crash(77, tau=0.6)[: int(0.75 * SR)][::-1].copy()
    music.add(rev, S7 + 1.0 - len(rev) / SR, 0.3)
    cue(S7, "LogoReveal cut", "music: drop-out to sub drone only")
    cue(S7 + 0.25, "swell into ORACLE", "music: reversed cymbal swell 0.25-1.0 s")
    hit(S7 + 1.0, "Fm", big=True, dur=1.3, crash_gain=0.32, label="ORACLE slam - FINAL HIT")
    pumped.add(pad(CH["Fm"][1] + [72], 3.0, cutoff=1600, attack=0.05), S7 + 1.0, 0.2)
    for j, (s, m) in enumerate(HOOK["Fm"][:4]):  # hook echo under the tagline, fading
        music.add(pluck(m, bright=0.6), S7 + 1.6 + s * STEP, 0.13 * 0.7 ** j, pan=(-0.4, 0.4)[j % 2], send=0.6)
    cue(S7 + 1.6, "tagline", "music: hook echo (4 notes, fading, wet)")
    cue(DUR - 1.05, "outro", "music + sfx: fade to silence (ends 30.75 s)")


def render_music():
    compose_music()
    pump = np.ones(N)
    for t in KICK_TIMES:
        i = round(t * SR)
        n = min(N - i, int(0.35 * SR))
        pump[i:i + n] = np.minimum(pump[i:i + n], 1 - 0.55 * np.exp(-secs(n) / 0.1))
    x = music.render(IR_MUSIC) + pumped.render(IR_MUSIC) * pump[:, None]
    return x


# ---------------------------------------------------------------- SFX

sfx = Bus()
IR_SFX = make_ir(1.9, 2.6, 5000, 9)
DUCK = []  # big impacts -> music ducking


def impact(t, size=1.0, label="impact", swish=True):
    """Cinematic boom: pitch-dropping sine + noise crack + low thump (+ short pre-swish)."""
    n = int(3.0 * SR)
    tt = secs(n)
    boom = sine(38 + 120 * np.exp(-tt / 0.06) * size ** 0.3 + 22 * np.exp(-tt / 0.4), n) * np.exp(-tt / (0.4 * size))
    boom = np.tanh(3 * boom) / np.tanh(3)
    crack = np.stack([bp(noise(n, 500 + c + int(t * 100)), 700, 7000) for c in range(2)], 1) * np.exp(-tt / 0.018)[:, None]
    thump = lp(noise(n, 600 + int(t * 100)), 400) * np.exp(-tt / 0.07) * 2
    body = np.tanh(3 * bp(noise(n, 700 + int(t * 100)), 150, 1200) * np.exp(-tt / 0.1))
    click = hp(noise(n, 800 + int(t * 100)), 2000) * np.exp(-tt / 0.002)
    x = stereo(0.75 * boom + 0.5 * thump + 0.35 * body + 0.5 * click) + 0.8 * crack
    sfx.add(fade_tail(x, 50), t, 0.62 * size, send=0.35)
    if swish:  # 140 ms rising noise into the hit
        m = int(0.14 * SR)
        u = secs(m) / 0.14
        sw = tvf(noise(m, int(t * 1000)), 800 * 7 ** u, "bandpass") * u ** 2.5
        sfx.add(sw, t - 0.14, 0.12, pan=0.0)
    DUCK.append((t, size))
    cue(t, label, f"sfx: impact boom (size {size}) + {'pre-swish + ' if swish else ''}reverb" + ("; music ducked -4 dB" if size >= 0.8 else ""))


def wipe_whoosh(t0):
    """Whoosh shaped by the exact wipe motion: loudness/brightness follow band speed, pan follows position."""
    n = int(0.85 * SR)
    t = secs(n)
    p = WIPE_EASE(np.clip(t / 0.6, 0, 1))
    v = np.gradient(p)
    v /= v.max()
    amp = v ** 1.4  # ease has zero slope at both ends -> bell-shaped, peak at +0.3 s
    pan = np.clip((-75 + 260 * p - 50) / 90, -1, 1)  # band centre in vw -> pan
    x = tvf(noise(n, int(t0 * 10) + 1), 300 + 3500 * v, "bandpass", width=1.8) * amp
    x += lp(noise(n, int(t0 * 10) + 2), 350) * amp * 0.8
    sfx.add(fade_tail(stereo(x, pan), 30), t0, 0.8, send=0.15)
    cue(t0, "scene cut + green wipe (0.6 s)", "sfx: noise whoosh, peak +0.30 s, panned L->R with the wipe")


def tick(t, f=3000, gain=0.07, pan=0.0, crush=False):
    n = int(0.02 * SR)
    tt = secs(n)
    x = np.sin(2 * np.pi * f * tt) * np.exp(-tt / 0.004)
    if crush:
        x = np.round(x * 4) / 4  # 2-bit glitch
    sfx.add(x, t, gain, pan=pan)


def countup(t0, dur, label, crush=False, n_ticks=22):
    """Ticks wherever the eased value crosses k/n_ticks: dense at first, slowing down (EASE_OUT)."""
    times = [t0 + dur * EASE_OUT_INV(j / n_ticks) for j in range(1, n_ticks)]
    last = -1
    for j, t in enumerate(times):
        if t - last < 0.022:
            continue
        last = t
        tick(t, 2600 + 900 * ((j * 5) % 3), 0.1, pan=(-0.35, 0.35)[j % 2], crush=crush)
    cue(t0, f"{label} count-up ({dur} s)", f"sfx: {'bit-crushed ' if crush else ''}digital ticks, decelerating with EASE_OUT")


def zap(t, f0, f1, dur, gain=0.12, pan=0.0):
    """Electric sweep: saw + sine following an eased pitch glide, 55 Hz buzz, hiss."""
    n = int((dur + 0.12) * SR)
    tt = secs(n)
    f = f0 * (f1 / f0) ** EASE_OUT(np.clip(tt / dur, 0, 1))
    x = lp(blsaw(f, n), 4500) * (1 + 0.5 * np.sin(2 * np.pi * 55 * tt)) * 0.5 + sine(f, n) * 0.5
    x += hp(noise(n, int(t * 100)), 5000) * 0.15
    env = np.minimum(1, tt / 0.004) * np.where(tt < dur * 0.6, 1, np.exp(-(tt - dur * 0.6) / (dur * 0.25)))
    sfx.add(fade_tail(x * env), t, gain, pan=pan, send=0.15)


def stamp(t):
    """Rubber-stamp thunk: low sine drop + mid thud + slap."""
    n = int(0.4 * SR)
    tt = secs(n)
    x = sine(55 + 45 * np.exp(-tt / 0.03), n) * np.exp(-tt / 0.09)
    x += bp(noise(n, 77), 150, 900) * np.exp(-tt / 0.035) * 1.2
    x += bp(noise(n, 78), 1500, 5000) * np.exp(-tt / 0.006) * 0.6
    sfx.add(fade_tail(x), t, 0.75, send=0.2)
    cue(t, "PICK: KNICKS stamp", "sfx: stamp thunk (low sine drop + thud + slap)")


def shimmer(t0, dur):
    """Glint: bell pings (F minor pentatonic, octave 6-7) + air sweep, panned L->R like the glint."""
    notes = [77, 80, 82, 84, 87, 89, 92, 94, 96]
    for j in range(26):
        u = np.random.default_rng(j).beta(2, 2)
        n = int(0.6 * SR)
        tt = secs(n)
        f = mtof(notes[j % len(notes)])
        x = np.sin(2 * np.pi * f * tt + 1.5 * np.exp(-tt / 0.05) * np.sin(2 * np.pi * f * 3.5 * tt)) * np.exp(-tt / 0.22)
        sfx.add(fade_tail(x), t0 + u * dur, 0.035, pan=-0.9 + 1.8 * u, send=0.5)
    n = int(dur * SR)
    u = secs(n) / dur
    air = tvf(noise(n, 31), 5000 + 6000 * u, "bandpass", width=1.4) * np.sin(np.pi * u) ** 2
    sfx.add(air, t0, 0.12, pan=-0.9 + 1.8 * u)
    cue(t0, f"ORACLE glint sweep ({dur} s)", "sfx: shimmer (FM bell pings + air sweep), panned L->R")


def riser(t_end, dur, gain=0.22, label="riser"):
    n = int(dur * SR)
    u = secs(n) / dur
    band = tvf(noise(n, int(t_end)), 300 * 30 ** u, "bandpass", width=1.5)
    tone = lp(blsaw(110 * 2 ** (3 * u ** 1.5), n), 3000) * 0.3
    trem = 0.7 + 0.3 * np.sin(2 * np.pi * np.cumsum(4 + 24 * u) / SR)
    x = (band + tone) * trem * u ** 2.2
    sfx.add(fade_tail(stereo(x, 0.0) * np.stack([np.ones(n), 0.9 + 0.1 * u], 1), 10), t_end - dur, gain, send=0.2)
    cue(t_end - dur, label, f"sfx: noise+saw riser ({dur} s), ends on {t_end:.2f}")


def bounce(t, gain=0.55):
    """Basketball on hardwood: low body thump + skin slap + ring, gym reverb."""
    n = int(0.3 * SR)
    tt = secs(n)
    x = sine(95 + 80 * np.exp(-tt / 0.01), n) * np.exp(-tt / 0.07)
    x += bp(noise(n, 88), 1000, 4000) * np.exp(-tt / 0.008) * 0.6
    x += np.sin(2 * np.pi * 1100 * tt) * np.exp(-tt / 0.02) * 0.08
    sfx.add(fade_tail(x), t, gain, send=0.5)


def compose_sfx():
    for s in STARTS:
        wipe_whoosh(s)

    # S1 ColdOpen
    n = int(2.8 * SR)
    u = secs(n) / 2.8
    roll = lp(noise(n, 5), 250) * (0.6 + 0.4 * np.sin(2 * np.pi * 3.6 * secs(n))) * np.sin(np.pi * u) ** 0.5
    sfx.add(roll, S1, 0.3, pan=-1 + 2 * u)
    cue(S1, "ball rolls across (2.8 s)", "sfx: low rolling rumble, seam flutter, panned L->R")
    for h, size in zip((0.58, 1.63, 2.68), (0.9, 1.0, 1.15)):
        impact(S1 + h, size, "ColdOpen 'EVERY ...' slam (shake + white flash)")
    riser(S2, 1.1, 0.16, "riser into the drop")

    # S2 DataStorm
    for h in (0.40, 1.20, 2.00):
        impact(S2 + h, 0.85, "DataStorm number slam (shake + green flash)")
    for h, lab in zip((0.25, 1.05, 1.85), ("14,108 GAMES", "11 SEASONS", "7 SKILL DIMENSIONS")):
        countup(S2 + h, 0.9, lab, crush=True)
    r = np.random.default_rng(42)
    for j in range(36):  # digit-rain data chatter
        tick(S2 + r.uniform(0, 4.0), r.uniform(900, 5000), 0.025, pan=r.uniform(-0.9, 0.9), crush=True)
    cue(S2, "digit rain", "sfx: sparse bit-crushed data chatter across the scene")

    # S3 EloScene
    for j in range(16):  # "7 SKILL DIMENSIONS" letters land
        tick(S3 + 0.1 + j * 0.035 + 0.08, 1800 + 120 * (j % 4), 0.05, pan=-0.5 + j / 16)
    cue(S3 + 0.18, "headline letters drop (16)", "sfx: soft letter clicks, 35 ms apart")
    scale = [53, 55, 56, 58, 60, 61, 63]  # bars zap up the F minor scale
    for i, fill in enumerate([0.92, 0.74, 0.81, 0.66, 0.88, 0.7, 0.79]):
        t = S3 + 0.7 + i * 0.12
        zap(t, mtof(scale[i]), mtof(scale[i] + 12 * fill + 5), 0.45, 0.17, pan=-0.3 + 0.1 * i)
        cue(t, f"ELO bar {i + 1} fills", f"sfx: electric zap up (MIDI {scale[i]})")
    impact(S3 + 2.4, 0.5, "'GENERAL ELO = SUM ALL SEVEN' slam", swish=False)

    # S4 Matchup
    for tt, pan, lab in ((0.15, -0.7, "NYK logo flies in"), (0.35, 0.7, "BOS logo flies in")):
        m = int(0.12 * SR)
        u = secs(m) / 0.12
        sfx.add(tvf(noise(m, int(tt * 100)), 1000 * 5 ** u, "bandpass") * np.sin(np.pi * u), S4 + tt, 0.3, pan=pan * (1 - u))
        cue(S4 + tt, lab, "sfx: short swish from that side")
    impact(S4 + 0.25, 0.5, "NYK logo lands", swish=False)
    impact(S4 + 0.40, 1.0, "BOS logo slam (shake)", swish=False)
    impact(S4 + 0.62, 1.05, "VS slam (shake + green flash)", swish=False)
    zap(S4 + 1.3, 180, 180 * 2 ** 2.5, 1.4, 0.2)
    cue(S4 + 1.3, "win-probability bar races to 62.9 % (1.3-2.7 s)", "sfx: long electric zap, pitch follows EASE_OUT bar width")
    countup(S4 + 1.3, 1.4, "62.9 % / 37.1 %", n_ticks=28)
    stamp(S4 + 3.05)
    impact(S4 + 3.05, 1.0, "PICK stamp (shake + white flash)", swish=True)

    # S5 Shap
    for j in range(13):  # "WHY THE KNICKS?"
        tick(S5 + 0.1 + j * 0.035 + 0.08, 1800 + 120 * (j % 4), 0.05, pan=-0.5 + j / 13)
    cue(S5 + 0.18, "headline letters drop (13)", "sfx: soft letter clicks")
    for i, v in enumerate([0.19, -0.11, -0.1, 0.1, 0.06]):
        t = S5 + 0.55 + i * 0.18 + 0.15
        f0 = mtof(60 + 2 * i)
        zap(t, f0, f0 * (2 ** (abs(v) / 0.19 * 1.5) if v > 0 else 2 ** (-abs(v) / 0.19)), 0.25, 0.17, pan=0.4 if v > 0 else -0.4)
        cue(t, f"SHAP bar {i + 1} ({v:+.2f})", f"sfx: zap {'up (green, +)' if v > 0 else 'down (red, -)'}")
    tick(S5 + 2.4, 1400, 0.05)
    cue(S5 + 2.4, "legend fades in", "sfx: single soft blip")

    # S6 Stats
    for h, size, lab in ((0.3, 1.0, "67.5 % ACCURACY slam"), (1.35, 0.9, "AUC 0.729 slam"), (2.15, 0.95, "BRIER 0.209 slam")):
        impact(S6 + h, size, f"{lab} (shake + flash)")
    countup(S6 + 0.15, 1.0, "67.5 %")
    countup(S6 + 1.2, 0.8, "0.729")
    countup(S6 + 2.0, 0.8, "0.209")
    riser(S7, 1.4, 0.24, "riser into the logo reveal")

    # S7 LogoReveal (ball spring 180/12 first reaches rest at +0.17 s)
    m = int(0.17 * SR)
    sfx.add(tvf(noise(m, 3), 600 * 4 ** (secs(m) / 0.17), "bandpass") * (secs(m) / 0.17) ** 2, S7, 0.25)
    bounce(S7 + 0.17)
    cue(S7 + 0.17, "ball drops in and lands", "sfx: falling swish + basketball bounce (gym reverb)")
    for j in range(9):  # COURTSIDE letters
        tick(S7 + 0.35 + j * 0.035 + 0.08, 1700 + 150 * (j % 3), 0.05, pan=-0.4 + j / 10)
    cue(S7 + 0.43, "COURTSIDE letters drop (9)", "sfx: soft letter clicks")
    m = int(0.6 * SR)
    sw = tvf(noise(m, 4), 400 * 12 ** (secs(m) / 0.6), "bandpass") * (secs(m) / 0.6) ** 3
    sfx.add(sw, S7 + 1.0 - 0.6, 0.3)
    impact(S7 + 1.0, 1.6, "ORACLE slam (shake + green flash) - FINAL", swish=False)
    shimmer(S7 + 1.5, 0.8)
    m = int(0.08 * SR)
    sfx.add(np.sin(2 * np.pi * np.cumsum(900 + 600 * secs(m) / 0.08) / SR) * np.exp(-secs(m) / 0.02), S7 + 2.31, 0.09, send=0.3)
    cue(S7 + 2.31, "URL pill pops in", "sfx: rising pop blip")


def render_sfx():
    compose_sfx()
    return sfx.render(IR_SFX)


# ---------------------------------------------------------------- mix / master


SFX_GAIN = 1.6  # sfx bus vs music bed (+4 dB)


def duck_curve(db=-4.0):
    """Sidechain-style gain: 5 ms attack, 80 ms hold, 300 ms release after each big impact."""
    g = np.zeros(N)
    for t, size in DUCK:
        if size < 0.8:
            continue
        i = round(t * SR)
        tt = secs(int(0.9 * SR)) - 0.005
        shape = np.where(tt < 0, np.clip(1 + tt / 0.005, 0, 1), np.where(tt < 0.08, 1, np.exp(-(tt - 0.08) / 0.3)))
        a = i - int(0.005 * SR)
        seg = shape[: N - a]
        g[a:a + len(seg)] = np.maximum(g[a:a + len(seg)], seg * min(1.0, size))
    return 10 ** (db * g / 20)


def softclip(x, thr=0.6):
    a = np.abs(x)
    return np.where(a <= thr, x, np.sign(x) * (thr + (1 - thr) * np.tanh((a - thr) / (1 - thr))))


def limiter(x, ceiling_db=-1.5, look=0.002, release=0.08):
    ceil = 10 ** (ceiling_db / 20)
    need = np.minimum(1, ceil / np.maximum(np.abs(x).max(1), 1e-9))
    L = int(look * SR)
    g = minimum_filter1d(need, 2 * L + 1)
    step = 1 / (release * SR)
    g = g.tolist()
    for i in range(1, len(g)):  # ponytail: per-sample python loop (~0.5 s); numba if this gets slow
        if g[i] > g[i - 1] + step:
            g[i] = g[i - 1] + step
    g = uniform_filter1d(np.array(g), L + 1)
    return np.clip(x * g[:, None], -ceil, ceil)


def lufs(x):
    """ITU-R BS.1770-4 integrated loudness (48 kHz K-weighting, 400 ms blocks, gated)."""
    y = lfilter([1.53512485958697, -2.69169618940638, 1.19839281085285], [1, -1.69065929318241, 0.73248077421585], x, axis=0)
    y = lfilter([1.0, -2.0, 1.0], [1, -1.99004745483398, 0.99007225036621], y, axis=0)
    blk, hop = int(0.4 * SR), int(0.1 * SR)
    z = np.array([(y[i:i + blk] ** 2).mean(0).sum() for i in range(0, len(y) - blk + 1, hop)])
    lk = -0.691 + 10 * np.log10(z + 1e-12)
    z = z[lk > -70]
    rel = -0.691 + 10 * np.log10(z.mean()) - 10
    z = z[-0.691 + 10 * np.log10(z) > rel]
    return -0.691 + 10 * np.log10(z.mean())


def true_peak_db(x):
    return 20 * np.log10(np.abs(resample_poly(x, 4, 1, axis=0)).max())


def onset(x, t, win=0.04):
    """Time of the steepest rise of a centred 3 ms RMS envelope (>300 Hz) within +-win of t."""
    e = (hp(x, 300) ** 2).sum(1)
    i0, i1 = round((t - win) * SR), round((t + win) * SR)
    r = np.sqrt(uniform_filter1d(e[i0:i1], int(0.003 * SR)))
    h = int(0.0005 * SR)
    return (i0 + int(np.argmax(r[h:] - r[:-h])) + h // 2) / SR


def master():
    m, s = hp(render_music(), 30), hp(render_sfx(), 30) * SFX_GAIN
    m *= duck_curve()[:, None]
    tail = np.clip((DUR - 0.05 - secs(N)) / 1.0, 0, 1) ** 2  # fade to silence over the last ~1 s
    m *= tail[:, None]
    s *= tail[:, None]
    gain = 1.0
    for _ in range(6):  # converge on -14 LUFS through soft clip + limiter
        mix = limiter(softclip((m + s) * gain))
        gain *= 10 ** ((-14.0 - lufs(mix)) / 20)
    mix = limiter(softclip((m + s) * gain))
    music_out, sfx_out = limiter(softclip(m * gain)), limiter(softclip(s * gain))
    return music_out, sfx_out, mix, gain


def write_cue_sheet():
    rows = sorted(set(CUES))
    lines = [
        "# Trailer soundtrack - cue sheet",
        "",
        "Generated by `render/soundtrack.py` from the timings in `web/app/trailer/page.tsx`.",
        "Scene starts (s): " + ", ".join(f"{n} {s:.1f}" for (n, _), s in zip(SCENES, STARTS)) + f"; end {DUR}.",
        "Music: 150 BPM (16th = 0.1 s, bar = 1.6 s), F minor; the groove restarts on a downbeat at every cut.",
        "Frames are at 30 / 60 fps (frame = floor(t * fps)).",
        "",
        "| Time (s) | F@30 | F@60 | Scene | Event | Sound |",
        "|---:|---:|---:|---|---|---|",
    ]
    for t, ev, snd in rows:
        i = max(i for i, s in enumerate(STARTS) if s <= t + 1e-9)
        lines.append(f"| {t:.3f} | {int(t * 30 + 1e-6)} | {int(t * 60 + 1e-6)} | {SCENES[i][0]} +{t - STARTS[i]:.2f} | {ev} | {snd} |")
    (OUT / "cue-sheet.md").write_text("\n".join(lines) + "\n")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    music_out, sfx_out, mix, gain = master()
    for name, x in (("music", music_out), ("sfx", sfx_out), ("mix", mix)):
        sf.write(OUT / f"{name}.wav", x, SR, subtype="PCM_24")
    write_cue_sheet()

    # self-check: length, peaks, loudness, transient alignment
    for name in ("music", "sfx", "mix"):
        x, sr = sf.read(OUT / f"{name}.wav")
        pk = 20 * np.log10(np.abs(x).max())
        print(f"{name:5s}: {len(x) / sr:.4f} s  {x.shape}  peak {pk:6.2f} dBFS  true-peak {true_peak_db(x):6.2f} dBTP  {lufs(x):6.2f} LUFS")
        assert len(x) == N and sr == SR and x.shape[1] == 2 and pk < -0.5
    print(f"master gain {20 * np.log10(gain):+.2f} dB")
    for t, size in DUCK:  # every shake/slam impact
        if size < 0.8:
            continue
        d_sfx, d_mix = (onset(x, t) - t for x in (sfx_out, mix))
        print(f"cue {t:6.2f}s  onset sfx {d_sfx * 1000:+5.1f} ms  mix {d_mix * 1000:+5.1f} ms")
        assert abs(d_mix) <= 0.010
    print("ok")


if __name__ == "__main__":
    main()
