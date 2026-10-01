"use client";

import { useEffect, useState } from "react";
import { getCardPrediction, getRunningRecord } from "@/lib/supabase";
import { TEAM_NAMES } from "@/lib/teams";
import type { Prediction, RunningRecord } from "@/lib/types";
import TeamLogo from "@/components/TeamLogo";

const THREE_HOURS_MS = 3 * 60 * 60 * 1000;

export default function CardPage() {
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [isUpcoming, setIsUpcoming] = useState(true);
  const [record, setRecord] = useState<RunningRecord | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [card, rec] = await Promise.all([
          getCardPrediction(),
          getRunningRecord(),
        ]);
        if (cancelled) return;
        setPrediction(card?.prediction ?? null);
        setIsUpcoming(card?.isUpcoming ?? true);
        setRecord(rec);
      } catch {
        if (cancelled) return;
        setPrediction(null);
        setRecord(null);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const correct = record?.total_correct ?? 0;
  const incorrect = record?.total_incorrect ?? 0;
  const total = correct + incorrect;
  const accuracy = total > 0 ? ((correct / total) * 100).toFixed(1) : "--";
  const confidence = prediction ? Math.round(prediction.confidence * 100) : null;
  const homeName = prediction ? (TEAM_NAMES[prediction.home_team] ?? prediction.home_team) : null;
  const awayName = prediction ? (TEAM_NAMES[prediction.away_team] ?? prediction.away_team) : null;
  const winnerName = prediction
    ? (TEAM_NAMES[prediction.predicted_team] ?? prediction.predicted_team)
    : null;

  const tipoffMs = prediction?.game_time_utc ? new Date(prediction.game_time_utc).getTime() : null;
  const now = Date.now();
  const isLive = isUpcoming && tipoffMs !== null && tipoffMs <= now && now < tipoffMs + THREE_HOURS_MS;
  const tipoffLabel = isUpcoming && !isLive && tipoffMs !== null
    ? new Date(tipoffMs).toLocaleString("en-US", {
        timeZone: "America/New_York",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      }) + " ET"
    : null;

  return (
    <div className="w-full h-screen bg-brand-bg flex flex-col overflow-hidden">

      {/* Header */}
      <div className="px-5 py-3 border-b border-brand-border flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className="text-brand-green text-lg">🏀</span>
          <span className="font-black tracking-tight text-white text-sm">
            NBA <span className="text-brand-green">PREDICTIONS</span>
          </span>
        </div>
        {isLive && (
          <div className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-brand-green" />
            <span className="text-[10px] text-brand-green tracking-widest uppercase font-bold">LIVE</span>
          </div>
        )}
        {!isLive && tipoffLabel && (
          <span className="text-[10px] text-brand-muted tracking-widest uppercase font-bold">
            {tipoffLabel}
          </span>
        )}
      </div>

      {/* Game + Predicted winner */}
      <div className="flex-1 grid grid-cols-2 divide-x divide-brand-border border-b border-brand-border min-h-0">

        {/* Game */}
        <div className="px-5 py-4 flex flex-col">
          <p className="text-[9px] tracking-widest uppercase text-brand-muted mb-3">
            📅 {isUpcoming ? "NEXT GAME" : "LAST GAME"}
          </p>
          {prediction ? (
            <div className="flex items-center gap-3 flex-1">
              <div className="flex flex-col items-center gap-1">
                <TeamLogo abbrev={prediction.home_team} teamId={prediction.home_team_id} size={40} />
                <span className="text-[10px] font-bold text-white tracking-wide uppercase">{homeName}</span>
              </div>
              <span className="text-brand-muted text-[10px] font-semibold">VS</span>
              <div className="flex flex-col items-center gap-1">
                <TeamLogo abbrev={prediction.away_team} teamId={prediction.away_team_id} size={40} />
                <span className="text-[10px] font-bold text-white tracking-wide uppercase">{awayName}</span>
              </div>
            </div>
          ) : (
            <p className="text-xs text-brand-muted">No upcoming game</p>
          )}
        </div>

        {/* Predicted winner / result */}
        <div className="px-5 py-4 flex flex-col">
          <p className="text-[9px] tracking-widest uppercase text-brand-muted mb-3">
            🏆 {isUpcoming ? "PREDICTED WINNER" : "RESULT"}
          </p>
          {prediction ? (
            <div className="flex-1 flex flex-col justify-center">
              <p className="text-xl font-black text-white tracking-tight leading-none uppercase">
                {winnerName}
              </p>
              {isUpcoming ? (
                <p className="text-xs text-brand-green font-semibold mt-1.5">
                  ({confidence}% Confidence)
                </p>
              ) : (
                <p className={`text-xs font-semibold mt-1.5 ${prediction.correct ? "text-brand-green" : "text-red-400"}`}>
                  {prediction.correct ? "✓ Correct" : "✗ Wrong"} ({confidence}% Confidence)
                </p>
              )}
            </div>
          ) : (
            <p className="text-xs text-brand-muted">No prediction yet</p>
          )}
        </div>
      </div>

      {/* Running record */}
      <div className="px-5 py-4 flex-shrink-0">
        <p className="text-[9px] tracking-widest uppercase text-brand-muted mb-3">
          📊 RUNNING RECORD
        </p>
        <div className="grid grid-cols-3 gap-2">
          <div>
            <div className="flex items-end gap-1">
              <span className="text-2xl font-black text-brand-green">{correct}</span>
              <span className="text-brand-green text-base mb-0.5">✓</span>
            </div>
            <p className="text-[9px] text-brand-muted tracking-widest">CORRECT</p>
          </div>
          <div>
            <div className="flex items-end gap-1">
              <span className="text-2xl font-black text-red-400">{incorrect}</span>
              <span className="text-red-400 text-base mb-0.5">✗</span>
            </div>
            <p className="text-[9px] text-brand-muted tracking-widest">INCORRECT</p>
          </div>
          <div>
            <div className="flex items-end gap-1">
              <span className="text-2xl font-black text-white">{accuracy}%</span>
              <span className="text-brand-green text-base mb-0.5">🎯</span>
            </div>
            <p className="text-[9px] text-brand-muted tracking-widest">ACCURACY</p>
          </div>
        </div>
      </div>

    </div>
  );
}
