"use client";

import { useEffect, useState } from "react";
import { Activity, Loader2 } from "lucide-react";
import { insightsApi } from "@/lib/api";
import type { ReadinessResponse } from "@/lib/api";

const BAND_COLOR: Record<string, string> = {
  prime: "#22c55e",
  ready: "#06b6d4",
  caution: "#f59e0b",
  rest: "#ef4444",
  unknown: "#64748b",
};

const STATUS_COLOR: Record<string, string> = {
  good: "#22c55e",
  ok: "#f59e0b",
  bad: "#ef4444",
};

export function ReadinessCard({ userId }: { userId: string }) {
  const [data, setData] = useState<ReadinessResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    insightsApi
      .readiness(userId)
      .then((d) => alive && setData(d))
      .catch(() => alive && setData(null))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [userId]);

  if (loading) {
    return (
      <div className="rounded-2xl border p-5 mb-5 flex items-center gap-2"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
        <Loader2 size={16} className="animate-spin" style={{ color: "var(--text-muted)" }} />
        <span className="text-xs" style={{ color: "var(--text-muted)" }}>正在评估今日状态…</span>
      </div>
    );
  }

  if (!data) return null;

  const color = BAND_COLOR[data.band] ?? BAND_COLOR.unknown;
  const score = data.score;
  const circumference = 2 * Math.PI * 26;
  const pct = score != null ? score / 100 : 0;

  return (
    <div className="rounded-2xl border p-5 mb-5"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
      <div className="flex items-center gap-2 mb-4">
        <Activity size={16} style={{ color }} />
        <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>今日训练准备度</h3>
      </div>

      <div className="flex items-center gap-4">
        {/* Gauge */}
        <div className="relative shrink-0" style={{ width: 64, height: 64 }}>
          <svg width={64} height={64} className="-rotate-90">
            <circle cx={32} cy={32} r={26} fill="none" strokeWidth={6}
              stroke="var(--surface2)" />
            {score != null && (
              <circle cx={32} cy={32} r={26} fill="none" strokeWidth={6}
                stroke={color} strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={circumference * (1 - pct)} />
            )}
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-lg font-bold leading-none" style={{ color }}>
              {score ?? "--"}
            </span>
          </div>
        </div>

        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium mb-0.5" style={{ color }}>{data.label}</p>
          <p className="text-xs leading-snug" style={{ color: "var(--text-muted)" }}>
            {data.recommendation}
          </p>
        </div>
      </div>

      {/* Factors */}
      {data.factors.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-4">
          {data.factors.map((f, i) => (
            <span key={i}
              className="text-[11px] px-2 py-1 rounded-lg inline-flex items-center gap-1"
              style={{ background: "var(--surface2)", color: "var(--text-muted)" }}>
              <span className="w-1.5 h-1.5 rounded-full"
                style={{ background: STATUS_COLOR[f.status] ?? "var(--text-muted)" }} />
              {f.label} {f.value}
            </span>
          ))}
        </div>
      )}

      {data.based_on_sessions === 0 && (
        <p className="text-[11px] mt-3" style={{ color: "var(--text-muted)" }}>
          完成并记录一次训练后，准备度评分会更精准。
        </p>
      )}
    </div>
  );
}
