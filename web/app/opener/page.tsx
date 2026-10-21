"use client";

import { useEffect, useState } from "react";
import { MotionConfig, animate, motion, useMotionValue, useTransform } from "motion/react";
import { teamLogoUrl } from "@/lib/teams";

// 11.2 s seamless-loop opener (4:5, 1080x1350), calm cut: the graphic builds itself in reading
// order 0-3.5 s, holds still until 9.2 s, then fades to the bare background (gone by 11.1 s, so the
// last frames equal frame 0). CountUp/EASE_OUT copied from app/trailer/page.tsx (a page module
// can't export them).

const LOOP_MS = 11200;
const FADE_AT = 9.2;
const FADE_DUR = 1.9;
// appear times (s), 0.3 s apart: brand, kicker, header, subline, card 1-3, footer stats, URL
const AT = { brand: 0.3, kicker: 0.6, header: 0.9, sub: 1.2, cards: [1.5, 1.8, 2.1], stats: 2.4, url: 2.7 };
const FILL_DELAY = 0.35; // bar fill + % count-up start, after the card appears
const FILL_DUR = 1.0;

const EASE_OUT = [0.16, 1, 0.3, 1] as const;

/** Sizes are authored in px of the 1080-wide design (post-graphic.html) and scale with the frame. */
const u = (px: number) => `${(px / 10.8).toFixed(4)}cqw`;

/** Soft fade-in + 14 px slide-up. */
const appear = (at: number) => ({
  initial: { opacity: 0, y: u(14) },
  animate: { opacity: 1, y: "0cqw" },
  transition: { delay: at, duration: 0.45, ease: EASE_OUT },
});

function CountUp({
  to,
  decimals = 0,
  suffix = "",
  delay = 0,
  duration = 1.2,
}: {
  to: number;
  decimals?: number;
  suffix?: string;
  delay?: number;
  duration?: number;
}) {
  const value = useMotionValue(0);
  const text = useTransform(
    value,
    (v) =>
      v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + suffix,
  );
  useEffect(() => {
    const controls = animate(value, to, { delay, duration, ease: EASE_OUT });
    return () => controls.stop();
  }, [value, to, delay, duration]);
  return <motion.span className="tabular-nums">{text}</motion.span>;
}

// ---------- content (facts: see brief / post-graphic.html) ----------

const PICKS = [
  { win: "BOS", lose: "DET", time: "3:00 PM ET", name: "Celtics", pct: 71 },
  { win: "PHI", lose: "NYK", time: "7:00 PM ET", name: "76ers", pct: 52 },
  { win: "OKC", lose: "SAS", time: "9:30 PM ET", name: "Thunder", pct: 58 },
];

function Logo({ abbrev }: { abbrev: string }) {
  return (
    <img
      src={teamLogoUrl(abbrev)}
      alt={abbrev}
      style={{ width: u(64), height: u(64), filter: abbrev === "SAS" ? "invert(1)" : undefined }}
    />
  );
}

function PickCard({ p, at }: { p: (typeof PICKS)[number]; at: number }) {
  const fill = { delay: at + FILL_DELAY, duration: FILL_DUR, ease: EASE_OUT };
  return (
    <motion.div
      className="border border-[#2a2a2a] bg-brand-card"
      style={{ borderRadius: u(22), padding: `${u(24)} ${u(34)}` }}
      {...appear(at)}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center font-semibold text-[#9ca3af]" style={{ gap: u(16), fontSize: u(26) }}>
          <Logo abbrev={p.win} />
          <span className="font-extrabold text-white">{p.win}</span> @ <Logo abbrev={p.lose} />
          {p.lose}
        </div>
        <div className="font-semibold text-brand-muted" style={{ fontSize: u(22) }}>
          {p.time}
        </div>
      </div>
      <div className="flex items-baseline justify-between" style={{ marginTop: u(10) }}>
        <div className="font-black" style={{ fontSize: u(44) }}>
          {p.name}
        </div>
        <div className="font-black text-brand-green" style={{ fontSize: u(52) }}>
          <CountUp to={p.pct} suffix="%" {...fill} />
          <small className="font-semibold text-brand-muted" style={{ fontSize: u(22), marginLeft: u(8) }}>
            confidence
          </small>
        </div>
      </div>
      <div className="relative flex justify-between" style={{ marginTop: u(18), height: u(14), gap: u(4) }}>
        <motion.div
          className="bg-gradient-to-r from-brand-dark to-brand-green"
          style={{ borderRadius: u(7) }}
          initial={{ width: "0%" }}
          animate={{ width: `${p.pct}%` }}
          transition={fill}
        />
        <motion.div
          className="bg-[#3a3a3a]"
          style={{ borderRadius: u(7) }}
          initial={{ width: "0%" }}
          animate={{ width: `${100 - p.pct}%` }}
          transition={fill}
        />
        <div
          className="absolute left-1/2 bg-white opacity-70"
          style={{ top: u(-6), bottom: u(-6), width: u(2), marginLeft: u(-1) }}
        />
      </div>
      <div
        className="relative flex justify-between font-semibold text-brand-muted"
        style={{ marginTop: u(10), fontSize: u(20) }}
      >
        <span className="text-brand-green">
          {p.win} {p.pct}%
        </span>
        <span className="absolute left-1/2 -translate-x-1/2 text-[#4b5563]">50%</span>
        <span>
          {p.lose} {100 - p.pct}%
        </span>
      </div>
    </motion.div>
  );
}

function Opener() {
  return (
    <motion.div
      className="absolute inset-0 flex flex-col"
      style={{ padding: `${u(72)} ${u(72)} ${u(64)}`, lineHeight: "normal" }}
      initial={{ opacity: 1 }}
      animate={{ opacity: 0 }}
      transition={{ delay: FADE_AT, duration: FADE_DUR, ease: "easeInOut" }}
    >
      <motion.div
        className="flex items-center font-extrabold tracking-[.04em]"
        style={{ gap: u(18), fontSize: u(30) }}
        {...appear(AT.brand)}
      >
        <span style={{ fontSize: u(40) }}>🏀</span>COURTSIDE <span className="text-brand-green">ORACLE</span>
      </motion.div>
      <motion.div
        className="whitespace-nowrap font-extrabold tracking-[.18em] text-[#ea580c]"
        style={{ marginTop: u(40), fontSize: u(26) }}
        {...appear(AT.kicker)}
      >
        OPENING NIGHT · OCT 20, 2026
      </motion.div>
      <motion.h1
        className="whitespace-nowrap font-black leading-none tracking-[-.02em]"
        style={{ marginTop: u(14), fontSize: u(92) }}
        {...appear(AT.header)}
      >
        Tonight&apos;s picks
      </motion.h1>
      <motion.div className="text-[#9ca3af]" style={{ marginTop: u(18), fontSize: u(28) }} {...appear(AT.sub)}>
        Machine-learning predictions, locked in before tip-off.
      </motion.div>

      <div className="flex flex-col" style={{ marginTop: u(40), gap: u(20) }}>
        {PICKS.map((p, i) => (
          <PickCard key={p.win} p={p} at={AT.cards[i]} />
        ))}
      </div>

      <div className="relative mt-auto flex items-end justify-between" style={{ paddingTop: u(26) }}>
        <motion.div
          className="absolute inset-x-0 top-0 h-px bg-[#2a2a2a]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: AT.stats, duration: 0.45, ease: EASE_OUT }}
        />
        <motion.div className="flex" style={{ gap: u(48) }} {...appear(AT.stats)}>
          <div>
            <b className="block font-black" style={{ fontSize: u(40) }}>
              <CountUp to={67.5} decimals={1} suffix="%" delay={AT.stats + 0.1} duration={0.8} />
            </b>
            <span className="tracking-[.06em] text-brand-muted" style={{ fontSize: u(20) }}>
              BACKTEST ACCURACY
            </span>
          </div>
          <div>
            <b className="block font-black" style={{ fontSize: u(40) }}>
              4 / 5
            </b>
            <span className="tracking-[.06em] text-brand-muted" style={{ fontSize: u(20) }}>
              2026 FINALS
            </span>
          </div>
        </motion.div>
        <motion.div className="text-right font-semibold text-[#9ca3af]" style={{ fontSize: u(22) }} {...appear(AT.url)}>
          courtside-oracle
          <br />
          .gerritvisser.de
        </motion.div>
      </div>
    </motion.div>
  );
}

export default function OpenerPage() {
  const [loop, setLoop] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => setLoop((l) => l + 1), LOOP_MS);
    return () => clearTimeout(t);
  }, [loop]);

  return (
    <MotionConfig reducedMotion="user">
      <main className="fixed inset-0 flex select-none items-center justify-center overflow-hidden bg-brand-bg text-white">
        <div
          className="relative aspect-[4/5] w-[min(100vw,80vh)] overflow-hidden bg-brand-bg"
          style={{
            containerType: "inline-size",
            backgroundImage:
              "radial-gradient(circle at 85% 0%, rgba(34,197,94,.14), transparent 45%), radial-gradient(circle at 0% 100%, rgba(234,88,12,.10), transparent 40%)",
          }}
        >
          <Opener key={loop} />
        </div>
      </main>
    </MotionConfig>
  );
}
