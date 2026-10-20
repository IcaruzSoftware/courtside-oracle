"use client";

import { useEffect, useState } from "react";
import GameCard from "./GameCard";
import type { Prediction, ShapValue } from "@/lib/types";

const ROTATE_MS = 7000;
const SLIDE_MS = 500;

interface Props {
  predictions: Prediction[];
  shapMap: Record<string, ShapValue[]>;
}

export default function GameCarousel({ predictions, shapMap }: Props) {
  // ms = transition duration of the last move (longer for multi-slide sweeps).
  const [{ index, ms }, setSlide] = useState({ index: 0, ms: SLIDE_MS });
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);

  const n = predictions.length;
  const active = index < n ? index : 0;
  const hasMany = n > 1;

  // Wrapping sweeps the track back across every slide in one motion.
  const go = (target: number) => {
    const distance = Math.abs(target - active);
    if (distance === 0) return;
    setSlide({ index: target, ms: Math.min(900, SLIDE_MS + 200 * (distance - 1)) });
  };
  const next = () => go((active + 1) % n);

  // Re-armed on every index change, so manual navigation also resets the timer.
  useEffect(() => {
    if (!hasMany || hovered || focused) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const t = setTimeout(next, ROTATE_MS);
    return () => clearTimeout(t);
  }, [active, n, hasMany, hovered, focused]);

  if (!hasMany) {
    return n === 1 ? <GameCard prediction={predictions[0]} shap={shapMap[predictions[0].id]} /> : null;
  }

  return (
    <div
      role="region"
      aria-roledescription="carousel"
      aria-label="Today's games"
      onPointerEnter={e => e.pointerType === "mouse" && setHovered(true)}
      onPointerLeave={() => setHovered(false)}
      // Only keyboard focus pauses; a mouse click on an arrow shouldn't stop rotation.
      onFocus={e => e.target.matches(":focus-visible") && setFocused(true)}
      onBlur={e => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocused(false);
      }}
    >
      <div className="relative px-8 sm:px-10">
        {/* overflow-hidden clips the track; the arrows sit outside it in the padded wrapper. */}
        <div className="overflow-hidden">
          {/* Flex row: height = tallest card, so there's no layout jump between slides. */}
          <div
            className="flex items-start transition-transform ease-in-out motion-reduce:transition-none"
            style={{ transform: `translateX(-${active * 100}%)`, transitionDuration: `${ms}ms` }}
          >
            {predictions.map((p, i) => (
              <div key={p.id} aria-hidden={i !== active} className="w-full shrink-0">
                <GameCard prediction={p} shap={shapMap[p.id]} />
              </div>
            ))}
          </div>
        </div>

        <button
          type="button"
          aria-label="Previous game"
          onClick={() => go((active - 1 + n) % n)}
          className="absolute left-0 top-1/2 -translate-y-1/2 w-8 sm:w-10 text-4xl leading-none text-white hover:text-brand-green"
        >
          ‹
        </button>
        <button
          type="button"
          aria-label="Next game"
          onClick={next}
          className="absolute right-0 top-1/2 -translate-y-1/2 w-8 sm:w-10 text-4xl leading-none text-white hover:text-brand-green"
        >
          ›
        </button>
      </div>

      <div className="mt-3 flex items-center justify-center gap-1.5">
        {predictions.map((p, i) => (
          <button
            key={p.id}
            type="button"
            aria-label={`Show game ${i + 1} of ${n}`}
            aria-current={i === active}
            onClick={() => go(i)}
            className={`w-6 h-1.5 rounded-full ${i === active ? "bg-brand-green" : "bg-brand-border hover:bg-brand-muted"}`}
          />
        ))}
      </div>
    </div>
  );
}
