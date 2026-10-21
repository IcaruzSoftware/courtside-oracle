#!/usr/bin/env python3
"""Calm soundtrack for the 11.2 s seamless-loop opener (web/app/opener/page.tsx).

Reuses soundtrack.py unchanged (instruments, buses, reverb, limiter, self-checks) by importing it
and swapping in this timeline, compose blocks and a gentler master. Writes trailer-export/opener-audio/.

    python opener_soundtrack.py

Soft pad bed (F minor, one chord per 1.6 s bar), one soft pluck per component as it appears,
very quiet ticks during the count-ups. Starts near-silent, fades to silence 9.2-11.2 s (loop seam).
No drums, impacts, risers, whooshes or ducking.
"""
import numpy as np

import soundtrack as st

DUR = 11.2
FADE_AT = 9.2
TARGET_LUFS = -18.0  # calm bed: quieter than the trailer's -14
# page.tsx AT: brand, kicker, header, subline, card 1-3, footer stats, URL
APPEAR = [("brand", 0.3), ("kicker", 0.6), ("header", 0.9), ("subline", 1.2), ("card 1", 1.5),
          ("card 2", 1.8), ("card 3", 2.1), ("footer stats", 2.4), ("URL", 2.7)]
FILL_DELAY, FILL_DUR = 0.35, 1.0

st.DUR, st.N = DUR, round(st.SR * DUR)
st.OUT = st.OUT.parent / "opener-audio"
st.SCENES, st.STARTS = [("Opener", 11200)], [0.0]
st.music, st.pumped, st.sfx = st.Bus(), st.Bus(), st.Bus()  # re-sized to 11.2 s


def compose_music():
    chords = ["Fm", "Db", "Bbm", "Eb", "Fm", "Db", "Fm"]  # 7 bars x 1.6 s = 11.2 s
    for i, chord in enumerate(chords):
        t0 = i * 1.6
        st.music.add(st.pad(st.CH[chord][1], 1.6, cutoff=900, attack=0.9 if i == 0 else 0.4), t0, 0.35, send=0.4)
        n = int(1.9 * st.SR)
        env = np.minimum(1, st.secs(n) / 0.4) * np.clip((1.9 - st.secs(n)) / 0.3, 0, 1)
        st.music.add(st.sine(st.mtof(st.CH[chord][0] + 12), n) * env, t0, 0.12)
        st.cue(t0, f"bar {i + 1}", f"music: soft low-passed pad ({chord}) + warm root sine")
    st.cue(FADE_AT, "fade out", "music + sfx: fade to silence by 11.2 s (loop seam)")


def soft_ticks(t0, dur, label, n_ticks=10):
    """Very quiet ticks, decelerating with EASE_OUT like the count-up."""
    for j in range(1, n_ticks):
        st.tick(t0 + dur * st.EASE_OUT_INV(j / n_ticks), 2200 + 300 * (j % 3), 0.018, pan=(-0.25, 0.25)[j % 2])
    st.cue(t0, f"{label} count-up ({dur} s)", "sfx: very quiet ticks, decelerating with EASE_OUT")


def compose_sfx():
    notes = [65, 68, 70, 72, 75, 77, 80, 82, 84]  # F minor pentatonic, rising in reading order
    for (name, t), m in zip(APPEAR, notes):
        st.sfx.add(st.pluck(m, bright=0.3), t, 0.5, pan=-0.3 + 0.075 * notes.index(m), send=0.45)
        st.cue(t, f"{name} fades in", f"sfx: soft pluck (MIDI {m})")
    for name, t in APPEAR[4:7]:
        soft_ticks(t + FILL_DELAY, FILL_DUR, f"{name} bar + %")
    soft_ticks(2.4 + 0.1, 0.8, "67.5 %")


FADE = np.clip((DUR - st.secs(st.N)) / (DUR - FADE_AT), 0, 1)
FADE = (np.sin(FADE * np.pi / 2) ** 2)[:, None]  # smooth 1 -> 0 over 9.2-11.2 s


def master():
    m = st.hp(st.render_music(), 30) * FADE
    s = st.hp(st.render_sfx(), 30) * st.SFX_GAIN * FADE
    gain = 1.0
    for _ in range(6):
        gain *= 10 ** ((TARGET_LUFS - st.lufs(st.limiter(st.softclip((m + s) * gain)))) / 20)
    return (st.limiter(st.softclip(m * gain)), st.limiter(st.softclip(s * gain)),
            st.limiter(st.softclip((m + s) * gain)), gain)


st.compose_music, st.compose_sfx, st.master = compose_music, compose_sfx, master

if __name__ == "__main__":
    st.main()
    sheet = st.OUT / "cue-sheet.md"
    sheet.write_text(sheet.read_text().replace("web/app/trailer/page.tsx", "web/app/opener/page.tsx")
                     .replace("`render/soundtrack.py`", "`tools/trailer/opener_soundtrack.py`")
                     .replace("the groove restarts on a downbeat at every cut", "calm pad bed, no drums"))
    for name in ("music", "sfx", "mix"):  # loop seam: both ends silent
        x, _ = st.sf.read(st.OUT / f"{name}.wav")
        head, tail = np.abs(x[:48]).max(), np.abs(x[-480:]).max()
        print(f"{name}: seam |first 1 ms| {head:.2e}  |last 10 ms| {tail:.2e}")
        assert head < 1e-3 and tail < 1e-4
    print("seam ok")
