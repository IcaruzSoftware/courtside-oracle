"use client";

import { useEffect, useState, type ReactNode } from "react";
import {
  AnimatePresence,
  MotionConfig,
  animate,
  motion,
  useAnimate,
  useMotionValue,
  useReducedMotion,
  useTransform,
} from "motion/react";
import { teamLogoUrl } from "@/lib/teams";

// ~30s auto-looping promo trailer. One scene index drives everything.

const EASE_OUT = [0.16, 1, 0.3, 1] as const;
const SLAM = { type: "spring", stiffness: 520, damping: 24 } as const;
const GLOW = "[text-shadow:0_0_40px_rgba(34,197,94,0.7)]";

// Deterministic pseudo-random so the static export hydrates without mismatches.
const rnd = (i: number) => (((i + 1) * 2654435761) % 4294967296) / 4294967296;

// ---------- building blocks ----------

/** Full-screen scene stage that screen-shakes at the given seconds. */
function Stage({ shakeAt = [], children }: { shakeAt?: number[]; children: ReactNode }) {
  const [scope, animateScope] = useAnimate<HTMLDivElement>();
  const reduce = useReducedMotion();
  useEffect(() => {
    if (reduce) return;
    const timers = shakeAt.map((t) =>
      setTimeout(
        () =>
          animateScope(
            scope.current,
            { x: [0, -18, 15, -10, 6, -2, 0], y: [0, 10, -8, 5, -3, 1, 0], rotate: [0, -0.6, 0.5, -0.3, 0] },
            { duration: 0.4 },
          ),
        t * 1000,
      ),
    );
    return () => timers.forEach(clearTimeout);
    // shakeAt is a per-scene literal; fire once per mount
  }, [reduce]);
  return (
    <div ref={scope} className="absolute inset-0 flex items-center justify-center px-5 sm:px-12">
      {children}
    </div>
  );
}

function Flash({ at, green = false }: { at: number; green?: boolean }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={`pointer-events-none absolute inset-0 z-10 ${green ? "bg-brand-green" : "bg-white"}`}
      initial={{ opacity: 0 }}
      animate={reduce ? undefined : { opacity: [0, 0.5, 0] }}
      transition={{ delay: at, duration: 0.35, times: [0, 0.12, 1] }}
    />
  );
}

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

/** Letters drop in one by one; words never break mid-word. */
function StaggerText({ text, delay = 0, className = "" }: { text: string; delay?: number; className?: string }) {
  let n = 0;
  return (
    <span className={className}>
      {text.split(" ").map((word, w) => (
        <span key={w}>
          {w > 0 && " "}
          <span className="inline-block whitespace-nowrap">
            {[...word].map((ch, i) => {
              const d = delay + n++ * 0.035;
              return (
                <motion.span
                  key={i}
                  className="inline-block"
                  initial={{ y: "-110%", opacity: 0, rotate: -12 }}
                  animate={{ y: 0, opacity: 1, rotate: 0 }}
                  transition={{ delay: d, type: "spring", stiffness: 500, damping: 22, opacity: { delay: d, duration: 0.1 } }}
                >
                  {ch}
                </motion.span>
              );
            })}
          </span>
        </span>
      ))}
    </span>
  );
}

function Kicker({ children, delay = 0 }: { children: ReactNode; delay?: number }) {
  return (
    <motion.div
      className="mb-2 flex items-center gap-3 text-[10px] font-black tracking-[0.35em] text-brand-green sm:text-sm"
      initial={{ opacity: 0, x: -30 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay, duration: 0.3, ease: EASE_OUT }}
    >
      <span className="h-[3px] w-8 bg-brand-green" />
      {children}
    </motion.div>
  );
}

function SpeedLines({ count = 16 }: { count?: number }) {
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {Array.from({ length: count }, (_, i) => (
        <motion.div
          key={i}
          className="absolute left-full h-px bg-gradient-to-r from-transparent via-white to-transparent"
          style={{ top: `${rnd(i + 300) * 100}%`, width: `${20 + rnd(i + 400) * 30}vw`, opacity: 0.15 + rnd(i + 600) * 0.5 }}
          animate={{ x: ["0vw", "-180vw"] }}
          transition={{ duration: 0.35 + rnd(i + 700) * 0.5, delay: rnd(i + 800) * 0.8, repeat: Infinity, ease: "linear" }}
        />
      ))}
    </div>
  );
}

function Ball({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 100" className={className}>
      <circle cx="50" cy="50" r="47" fill="#ea580c" stroke="#111" strokeWidth="3" />
      <path
        d="M50 3v94M3 50h94M18 16c18 18 18 50 0 68M82 16c-18 18-18 50 0 68"
        fill="none"
        stroke="#111"
        strokeWidth="3"
      />
    </svg>
  );
}

const COURT_PATHS = [
  "M40 40H1560V860H40Z",
  "M800 40V860",
  "M980 450A180 180 0 1 1 620 450A180 180 0 1 1 980 450",
  "M40 310H420V590H40",
  "M1560 310H1180V590H1560",
  "M40 140H260A330 330 0 0 1 260 760H40",
  "M1560 140H1340A330 330 0 0 0 1340 760H1560",
];

// ---------- scenes ----------

function ColdOpen() {
  const nouns = ["GAME.", "PLAYER.", "NIGHT."];
  const hits = [0.5, 1.55, 2.6];
  return (
    <Stage shakeAt={hits.map((h) => h + 0.08)}>
      <svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" className="absolute inset-0 h-full w-full">
        {COURT_PATHS.map((d, i) => (
          <motion.path
            key={d}
            d={d}
            fill="none"
            stroke="white"
            strokeOpacity={0.14}
            strokeWidth={3}
            initial={{ pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ delay: i * 0.08, duration: 1.2, ease: EASE_OUT }}
          />
        ))}
      </svg>
      <motion.div
        className="absolute inset-y-0 left-0 w-[30vw] bg-gradient-to-r from-transparent via-brand-green/25 to-transparent"
        initial={{ x: "-40vw", skewX: -20 }}
        animate={{ x: "140vw", skewX: -20 }}
        transition={{ delay: 0.1, duration: 1.2, ease: "easeInOut" }}
      />
      <motion.div
        className="absolute bottom-[12%] left-0"
        initial={{ x: "-20vw", rotate: 0 }}
        animate={{ x: "120vw", rotate: 900 }}
        transition={{ duration: 2.8, ease: "linear" }}
      >
        <Ball className="h-14 w-14 sm:h-24 sm:w-24" />
      </motion.div>
      {nouns.map((noun, i) => {
        const last = i === nouns.length - 1;
        return (
          <motion.h1
            key={noun}
            className="absolute whitespace-nowrap text-[clamp(2.5rem,9vw,9rem)] font-black italic leading-none tracking-tighter"
            initial={{ opacity: 0, scale: 2.6, skewX: -18 }}
            animate={
              last
                ? { opacity: 1, scale: 1, skewX: -8 }
                : { opacity: [0, 1, 1, 0], scale: [2.6, 1, 1.05, 1.12], skewX: [-18, -8, -8, -8] }
            }
            transition={
              last
                ? { delay: hits[i], ...SLAM, opacity: { delay: hits[i], duration: 0.06 } }
                : { delay: hits[i], duration: 1.0, times: [0, 0.12, 0.92, 1], ease: "easeOut" }
            }
          >
            EVERY <span className={`text-brand-green ${GLOW}`}>{noun}</span>
          </motion.h1>
        );
      })}
      {hits.map((h) => (
        <Flash key={h} at={h + 0.08} />
      ))}
    </Stage>
  );
}

function DigitRain() {
  return (
    <div className="absolute inset-0 flex justify-between overflow-hidden px-2 font-mono text-sm leading-tight text-brand-green [mask-image:linear-gradient(transparent,black_20%,black_80%,transparent)]">
      {Array.from({ length: 22 }, (_, c) => {
        const digits = Array.from({ length: 60 }, (_, k) => Math.floor(rnd(c * 97 + k) * 10)).join("\n");
        return (
          <motion.div
            key={c}
            className="whitespace-pre"
            style={{ opacity: 0.1 + rnd(c + 500) * 0.35 }}
            initial={{ y: "-50%" }}
            animate={{ y: "0%" }}
            transition={{ duration: 1 + rnd(c + 900) * 1.5, repeat: Infinity, ease: "linear" }}
          >
            {digits + "\n" + digits}
          </motion.div>
        );
      })}
    </div>
  );
}

function DataStorm() {
  const stats = [
    { to: 14108, label: "GAMES" },
    { to: 11, label: "SEASONS" },
    { to: 7, label: "SKILL DIMENSIONS" },
  ];
  const hits = [0.25, 1.05, 1.85];
  return (
    <Stage shakeAt={hits.map((h) => h + 0.15)}>
      <DigitRain />
      <SpeedLines />
      <div className="relative flex flex-col gap-1 sm:gap-3">
        {stats.map((s, i) => (
          <motion.div
            key={s.label}
            className={`flex items-baseline gap-3 sm:gap-5 ${i % 2 ? "self-end" : "self-start"}`}
            initial={{ x: i % 2 ? "100vw" : "-100vw", skewX: i % 2 ? 30 : -30, opacity: 0 }}
            animate={{ x: 0, skewX: -6, opacity: 1 }}
            transition={{ delay: hits[i], ...SLAM, opacity: { delay: hits[i], duration: 0.05 } }}
          >
            <span className="text-[clamp(3rem,13vw,10rem)] font-black italic leading-none">
              <CountUp to={s.to} delay={hits[i]} duration={0.9} />
            </span>
            <span className={`text-[clamp(0.9rem,3vw,2rem)] font-black tracking-tight text-brand-green ${GLOW}`}>
              {s.label}
            </span>
          </motion.div>
        ))}
        <motion.p
          className="mt-3 self-center font-mono text-xs tracking-[0.3em] text-brand-muted sm:text-base"
          initial={{ opacity: 0, letterSpacing: "1em" }}
          animate={{ opacity: 1, letterSpacing: "0.3em" }}
          transition={{ delay: 2.6, duration: 0.6, ease: EASE_OUT }}
        >
          2015-16 → 2025-26
        </motion.p>
      </div>
      {hits.map((h) => (
        <Flash key={h} at={h + 0.15} green />
      ))}
    </Stage>
  );
}

const SKILLS = ["SCORING", "PLAYMAKING", "DEFENSE", "REBOUNDING", "EFFICIENCY", "HUSTLE", "THREE-POINT"];
const SKILL_FILL = [0.92, 0.74, 0.81, 0.66, 0.88, 0.7, 0.79]; // illustrative bar lengths, no numbers shown

function EloScene() {
  return (
    <Stage>
      <SpeedLines count={8} />
      <div className="relative w-full max-w-3xl">
        <Kicker>PER-PLAYER ELO</Kicker>
        <h2 className="text-[clamp(2rem,7vw,5rem)] font-black italic leading-none tracking-tighter">
          <StaggerText text="7 SKILL DIMENSIONS" delay={0.1} />
        </h2>
        <div className="mt-6 space-y-2 sm:mt-8 sm:space-y-3">
          {SKILLS.map((skill, i) => (
            <motion.div
              key={skill}
              className="flex items-center gap-3"
              initial={{ opacity: 0, x: -60, skewX: -20 }}
              animate={{ opacity: 1, x: 0, skewX: 0 }}
              transition={{ delay: 0.5 + i * 0.12, ...SLAM }}
            >
              <span className="w-24 shrink-0 text-right text-[10px] font-black tracking-widest text-white/80 sm:w-40 sm:text-sm">
                {skill}
              </span>
              <div className="relative h-3 flex-1 overflow-hidden rounded-sm bg-white/5 sm:h-5">
                <motion.div
                  className="absolute inset-y-0 left-0 w-full origin-left bg-gradient-to-r from-brand-dark to-brand-green shadow-[0_0_20px_rgba(34,197,94,0.6)]"
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: SKILL_FILL[i] }}
                  transition={{ delay: 0.7 + i * 0.12, type: "spring", stiffness: 120, damping: 14 }}
                />
              </div>
            </motion.div>
          ))}
        </div>
        <motion.p
          className="mt-6 text-center text-xs font-black tracking-[0.3em] text-brand-green sm:text-base"
          initial={{ opacity: 0, scale: 1.4 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 2.3, ...SLAM }}
        >
          GENERAL ELO = Σ ALL SEVEN
        </motion.p>
      </div>
    </Stage>
  );
}

function TeamSlam({ abbrev, name, tag, from, delay }: { abbrev: string; name: string; tag: string; from: 1 | -1; delay: number }) {
  return (
    <motion.div
      className="flex flex-1 flex-col items-center"
      initial={{ x: `${from * 70}vw`, rotate: from * 35, scale: 1.8, opacity: 0 }}
      animate={{ x: 0, rotate: 0, scale: 1, opacity: 1 }}
      transition={{ delay, type: "spring", stiffness: 600, damping: 26, opacity: { delay, duration: 0.05 } }}
    >
      <img
        src={teamLogoUrl(abbrev)}
        alt={name}
        className="h-[clamp(5rem,20vw,13rem)] w-[clamp(5rem,20vw,13rem)] object-contain drop-shadow-[0_0_30px_rgba(255,255,255,0.15)]"
      />
      <div className="mt-2 text-[clamp(1rem,3.5vw,2.25rem)] font-black italic tracking-tight">{name}</div>
      <div className="text-[10px] font-bold tracking-[0.3em] text-brand-muted sm:text-xs">{tag}</div>
    </motion.div>
  );
}

function Matchup() {
  return (
    <Stage shakeAt={[0.4, 0.62, 3.05]}>
      <SpeedLines />
      <div className="relative flex w-full max-w-4xl flex-col items-center">
        <Kicker>THE PICK</Kicker>
        <div className="mt-2 flex w-full items-center justify-between gap-2">
          <TeamSlam abbrev="NYK" name="KNICKS" tag="HOME" from={-1} delay={0.15} />
          <motion.div
            className={`text-[clamp(2.5rem,9vw,7rem)] font-black italic text-brand-green ${GLOW}`}
            initial={{ scale: 5, opacity: 0, rotate: -20 }}
            animate={{ scale: 1, opacity: 1, rotate: 0 }}
            transition={{ delay: 0.55, ...SLAM, opacity: { delay: 0.55, duration: 0.05 } }}
          >
            VS
          </motion.div>
          <TeamSlam abbrev="BOS" name="CELTICS" tag="AWAY" from={1} delay={0.35} />
        </div>

        <motion.div
          className="mt-6 w-full sm:mt-10"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 1.1, duration: 0.3 }}
        >
          <div className="mb-2 flex items-end justify-between font-black italic">
            <span className={`text-[clamp(2rem,7vw,4.5rem)] leading-none text-brand-green ${GLOW}`}>
              <CountUp to={62.9} decimals={1} suffix="%" delay={1.3} duration={1.4} />
            </span>
            <span className="self-center text-[10px] font-bold not-italic tracking-[0.3em] text-brand-muted sm:text-xs">
              WIN PROBABILITY
            </span>
            <span className="text-[clamp(1.25rem,4vw,2.5rem)] leading-none text-white/50">
              <CountUp to={37.1} decimals={1} suffix="%" delay={1.3} duration={1.4} />
            </span>
          </div>
          <div className="relative h-4 skew-x-[-12deg] overflow-hidden rounded-sm bg-white/10 sm:h-6">
            <motion.div
              className="absolute inset-y-0 left-0 bg-gradient-to-r from-brand-dark to-brand-green shadow-[0_0_30px_rgba(34,197,94,0.8)]"
              initial={{ width: "0%" }}
              animate={{ width: "62.9%" }}
              transition={{ delay: 1.3, duration: 1.4, ease: EASE_OUT }}
            />
            <div className="absolute inset-y-0 left-1/2 w-px bg-white/40" />
          </div>
        </motion.div>

        <motion.div
          className="mt-6 border-4 border-brand-green px-4 py-1 text-[clamp(1.25rem,4vw,2.5rem)] font-black italic tracking-tight text-brand-green shadow-[0_0_40px_rgba(34,197,94,0.5)]"
          initial={{ scale: 3, opacity: 0, rotate: -14 }}
          animate={{ scale: 1, opacity: 1, rotate: -6 }}
          transition={{ delay: 3.0, ...SLAM, opacity: { delay: 3.0, duration: 0.05 } }}
        >
          PICK: KNICKS
        </motion.div>
      </div>
      <Flash at={0.6} green />
      <Flash at={3.05} />
    </Stage>
  );
}

const SHAP: [string, number][] = [
  ["Net rating last 10", 0.19],
  ["Home general ELO", -0.11],
  ["Home efficiency ELO", -0.1],
  ["Net efficiency advantage", 0.1],
  ["General ELO diff", 0.06],
];

function Shap() {
  return (
    <Stage>
      <div className="relative w-full max-w-3xl">
        <Kicker>SHAP · TOP 5 FACTORS</Kicker>
        <h2 className="text-[clamp(2rem,7vw,5rem)] font-black italic leading-none tracking-tighter">
          <StaggerText text="WHY THE KNICKS?" delay={0.1} />
        </h2>
        <div className="mt-6 space-y-2 sm:mt-8 sm:space-y-3">
          {SHAP.map(([label, v], i) => {
            const d = 0.55 + i * 0.18;
            const pos = v > 0;
            const w = (Math.abs(v) / 0.19) * 40; // % of the row; leaves room for the value label
            return (
              <motion.div
                key={label}
                className="grid grid-cols-[6.5rem_1fr] items-center gap-3 sm:grid-cols-[14rem_1fr]"
                initial={{ opacity: 0, x: 80, skewX: -20 }}
                animate={{ opacity: 1, x: 0, skewX: 0 }}
                transition={{ delay: d, ...SLAM }}
              >
                <span className="text-right text-[11px] font-bold leading-tight text-white/80 sm:text-base">{label}</span>
                <div className="relative flex h-6 items-center sm:h-9">
                  <div className="absolute inset-y-0 left-1/2 w-px bg-white/30" />
                  <motion.div
                    className={`absolute inset-y-1 ${
                      pos
                        ? "left-1/2 origin-left bg-brand-green shadow-[0_0_20px_rgba(34,197,94,0.7)]"
                        : "right-1/2 origin-right bg-red-500 shadow-[0_0_20px_rgba(239,68,68,0.7)]"
                    }`}
                    style={{ width: `${w}%` }}
                    initial={{ scaleX: 0 }}
                    animate={{ scaleX: 1 }}
                    transition={{ delay: d + 0.15, type: "spring", stiffness: 260, damping: 18 }}
                  />
                  <motion.span
                    className={`absolute text-xs font-black tabular-nums sm:text-base ${pos ? "text-brand-green" : "text-red-500"}`}
                    style={pos ? { left: `calc(50% + ${w}% + 6px)` } : { right: `calc(50% + ${w}% + 6px)` }}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    transition={{ delay: d + 0.4 }}
                  >
                    {pos ? "+" : "−"}
                    {Math.abs(v).toFixed(2)}
                  </motion.span>
                </div>
              </motion.div>
            );
          })}
        </div>
        <motion.div
          className="mt-6 flex justify-center gap-6 text-[10px] font-black tracking-[0.25em] sm:text-xs"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 2.4 }}
        >
          <span className="text-brand-green">+ FOR NYK</span>
          <span className="text-red-500">− AGAINST NYK</span>
        </motion.div>
      </div>
    </Stage>
  );
}

function Stats() {
  const side = [
    { to: 0.729, label: "AUC-ROC", d: 1.2, from: -1 },
    { to: 0.209, label: "BRIER SCORE", d: 2.0, from: 1 },
  ];
  return (
    <Stage shakeAt={[0.3, 1.35, 2.15]}>
      <SpeedLines />
      <div className="relative flex flex-col items-center text-center">
        <motion.div
          initial={{ scale: 3.2, opacity: 0, skewX: -20, filter: "blur(12px)" }}
          animate={{ scale: 1, opacity: 1, skewX: -8, filter: "blur(0px)" }}
          transition={{ delay: 0.15, ...SLAM, opacity: { delay: 0.15, duration: 0.1 }, filter: { delay: 0.15, duration: 0.25 } }}
        >
          <div className={`text-[clamp(4.5rem,20vw,15rem)] font-black italic leading-[0.85] tracking-tighter text-brand-green ${GLOW}`}>
            <CountUp to={67.5} decimals={1} suffix="%" delay={0.15} duration={1} />
          </div>
          <div className="mt-2 text-[clamp(1rem,3.5vw,2.25rem)] font-black tracking-tight">ACCURACY</div>
          <div className="text-[10px] font-bold tracking-[0.25em] text-brand-muted sm:text-sm">ON 2,116 HELD-OUT GAMES</div>
        </motion.div>
        <div className="mt-6 flex gap-8 sm:mt-10 sm:gap-20">
          {side.map((s) => (
            <motion.div
              key={s.label}
              initial={{ x: `${s.from * 60}vw`, skewX: s.from * -30, opacity: 0 }}
              animate={{ x: 0, skewX: -8, opacity: 1 }}
              transition={{ delay: s.d, ...SLAM, opacity: { delay: s.d, duration: 0.05 } }}
            >
              <div className="text-[clamp(2.5rem,10vw,7rem)] font-black italic leading-none">
                <CountUp to={s.to} decimals={3} delay={s.d} duration={0.8} />
              </div>
              <div className="mt-1 text-xs font-black tracking-[0.25em] text-brand-green sm:text-base">{s.label}</div>
            </motion.div>
          ))}
        </div>
        <motion.p
          className="mt-8 text-[10px] font-bold tracking-[0.25em] text-brand-muted sm:text-sm"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 2.9, duration: 0.4 }}
        >
          XGBOOST · PLATT-CALIBRATED · 14,108 GAMES · 11 SEASONS
        </motion.p>
      </div>
      <Flash at={0.3} green />
      <Flash at={1.35} />
      <Flash at={2.15} />
    </Stage>
  );
}

function LogoReveal() {
  return (
    <Stage shakeAt={[1.0]}>
      <div className="relative flex flex-col items-center text-center">
        <motion.div
          className="text-[clamp(3rem,10vw,6rem)] leading-none"
          initial={{ y: "-60vh", rotate: -360 }}
          animate={{ y: 0, rotate: 0 }}
          transition={{ type: "spring", stiffness: 180, damping: 12 }}
        >
          🏀
        </motion.div>
        <div className="relative mt-3 overflow-hidden px-2">
          <h1 className="flex flex-wrap justify-center gap-x-[0.25em] text-[clamp(2.5rem,7vw,7rem)] font-black leading-none tracking-tight">
            <StaggerText text="COURTSIDE" delay={0.35} />
            <motion.span
              className={`inline-block text-brand-green ${GLOW}`}
              initial={{ scale: 3.5, opacity: 0, skewX: -20 }}
              animate={{ scale: 1, opacity: 1, skewX: 0 }}
              transition={{ delay: 0.95, ...SLAM, opacity: { delay: 0.95, duration: 0.05 } }}
            >
              ORACLE
            </motion.span>
          </h1>
          <motion.div
            className="pointer-events-none absolute inset-y-0 left-0 w-1/3 bg-gradient-to-r from-transparent via-white/40 to-transparent"
            initial={{ x: "-150%", skewX: -20 }}
            animate={{ x: "400%", skewX: -20 }}
            transition={{ delay: 1.5, duration: 0.8, ease: "easeInOut" }}
          />
        </div>
        <motion.p
          className="mt-5 text-[clamp(1.1rem,3.5vw,2rem)] font-bold italic text-white/90"
          initial={{ opacity: 0, letterSpacing: "0.5em", filter: "blur(8px)" }}
          animate={{ opacity: 1, letterSpacing: "0em", filter: "blur(0px)" }}
          transition={{ delay: 1.6, duration: 0.6, ease: EASE_OUT }}
        >
          The machine sees the game.
        </motion.p>
        <motion.div
          className="mt-6 rounded-full border border-brand-green/40 bg-brand-green/10 px-4 py-1.5 font-mono text-xs text-brand-green sm:text-base"
          initial={{ opacity: 0, scale: 0.6 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 2.2, ...SLAM }}
        >
          courtside-oracle.gerritvisser.de
        </motion.div>
        <motion.p
          className="mt-4 text-[10px] font-bold tracking-[0.3em] text-brand-muted sm:text-xs"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 2.6, duration: 0.4 }}
        >
          FRESH PREDICTIONS EVERY GAME DAY
        </motion.p>
      </div>
      <Flash at={1.0} green />
    </Stage>
  );
}

// ---------- timeline ----------

const SCENES = [
  { ms: 4000, Scene: ColdOpen },
  { ms: 4200, Scene: DataStorm },
  { ms: 4200, Scene: EloScene },
  { ms: 5000, Scene: Matchup },
  { ms: 4400, Scene: Shap },
  { ms: 4200, Scene: Stats },
  { ms: 4800, Scene: LogoReveal },
];

function Hud({ scene }: { scene: number }) {
  return (
    <>
      <div className="absolute left-4 top-4 z-30 flex items-center gap-2 text-[10px] font-black tracking-[0.2em] sm:text-xs">
        <motion.span
          className="h-2 w-2 rounded-full bg-red-500"
          animate={{ opacity: [1, 0.2, 1] }}
          transition={{ duration: 1, repeat: Infinity }}
        />
        <span>
          COURTSIDE <span className="text-brand-green">ORACLE</span>
        </span>
      </div>
      <div className="absolute right-4 top-4 z-30 font-mono text-[10px] tabular-nums text-brand-muted sm:text-xs">
        {String(scene + 1).padStart(2, "0")} / {String(SCENES.length).padStart(2, "0")}
      </div>
      <div className="absolute inset-x-4 bottom-4 z-30 flex gap-1.5">
        {SCENES.map((s, i) => (
          <div key={i} className="h-1 flex-1 overflow-hidden rounded-full bg-white/10">
            {i <= scene && (
              <motion.div
                key={i === scene ? "running" : "done"}
                className="h-full w-full origin-left bg-brand-green"
                initial={{ scaleX: i < scene ? 1 : 0 }}
                animate={{ scaleX: 1 }}
                transition={{ duration: s.ms / 1000, ease: "linear" }}
              />
            )}
          </div>
        ))}
      </div>
    </>
  );
}

/** Diagonal broadcast wipe; remounted (keyed) on every cut. */
function Wipe() {
  return (
    <motion.div
      className="pointer-events-none absolute inset-y-[-10%] left-0 z-20 flex w-[70vw]"
      initial={{ x: "-110vw", skewX: -20 }}
      animate={{ x: "150vw", skewX: -20 }}
      transition={{ duration: 0.6, ease: [0.7, 0, 0.3, 1] }}
    >
      <div className="w-1/4 bg-brand-green" />
      <div className="w-1/2 bg-black" />
      <div className="w-1/4 bg-brand-green/60" />
    </motion.div>
  );
}

export default function TrailerPage() {
  const [scene, setScene] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => setScene((s) => (s + 1) % SCENES.length), SCENES[scene].ms);
    return () => clearTimeout(t);
  }, [scene]);

  const { Scene } = SCENES[scene];

  return (
    <MotionConfig reducedMotion="user">
      <main className="fixed inset-0 select-none overflow-hidden bg-brand-bg text-white">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(34,197,94,0.12),transparent_60%)]" />
        <AnimatePresence>
          <motion.div
            key={scene}
            className="absolute inset-0"
            initial={{ opacity: 0, scale: 1.08 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.92, skewX: -6, filter: "blur(10px)", transition: { duration: 0.25 } }}
            transition={{ duration: 0.25, ease: EASE_OUT }}
          >
            <Scene />
          </motion.div>
        </AnimatePresence>
        <Wipe key={`wipe-${scene}`} />
        {/* scanlines + vignette */}
        <div className="pointer-events-none absolute inset-0 z-20 opacity-[0.04] [background-image:repeating-linear-gradient(0deg,#fff_0,#fff_1px,transparent_1px,transparent_4px)]" />
        <div className="pointer-events-none absolute inset-0 z-20 bg-[radial-gradient(ellipse_at_center,transparent_50%,rgba(0,0,0,0.85))]" />
        <Hud scene={scene} />
      </main>
    </MotionConfig>
  );
}
