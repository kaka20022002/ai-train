"use client";

import { useState } from "react";
import { Download, ShieldAlert, Clock, Dumbbell } from "lucide-react";
import type { GeneratePlanResponse, PlanExercise } from "@/lib/api";
import { PHASE_META, WORKOUT_TYPE_CN } from "@/lib/constants";
import { muscleCn, translateExerciseText } from "@/lib/exercise-labels";
import { translateIntensityNote, translateCoachText } from "@/lib/term-labels";
import { ExerciseName } from "@/components/ExerciseName";
import { ExerciseGuide } from "@/components/ExerciseGuide";

const PHASE_ORDER = ["warm_up", "activation", "main_lifts", "accessories", "cool_down"] as const;

interface Props {
  plan: GeneratePlanResponse;
  elapsed?: number;
}

export function PlanResult({ plan, elapsed }: Props) {
  const [activePhase, setActivePhase] = useState<string>("main_lifts");
  const phases = plan.phases;
  const totalEx = PHASE_ORDER.reduce((n, k) => n + (phases[k]?.length ?? 0), 0);
  const totalSets = PHASE_ORDER.reduce(
    (n, k) => n + (phases[k]?.reduce((s, e) => s + (e.sets ?? 0), 0) ?? 0), 0
  );

  const version = plan.generator_version;
  const isLlm = version.includes("llm");
  const isFallback = version.includes("fallback");

  return (
    <div className="flex flex-col gap-5">
      {/* Status badge */}
      <div
        className="inline-flex self-start items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium"
        style={{
          background: isLlm && !isFallback ? "rgba(108,99,255,0.15)" : isFallback ? "rgba(239,68,68,0.12)" : "rgba(245,158,11,0.12)",
          color: isLlm && !isFallback ? "var(--accent-light)" : isFallback ? "var(--danger)" : "var(--warning)",
        }}
      >
        {isLlm && !isFallback ? "✅ 大模型生成" : isFallback ? "⚠️ 大模型不可用，已降级为本地模板" : "📦 本地模板模式"}
        {elapsed != null && ` · ${elapsed.toFixed(1)}s`}
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Metric label="训练类型" value={WORKOUT_TYPE_CN[plan.workout_type] ?? plan.workout_type} />
        <Metric label="预计时长" value={`${plan.estimated_duration_minutes} 分钟`} icon={<Clock size={14} />} />
        <Metric label="动作总数" value={String(totalEx)} icon={<Dumbbell size={14} />} />
        <Metric label="总组数" value={String(totalSets)} />
      </div>

      <p className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
        计划 {plan.plan_id} · 用户 {plan.user_id}
      </p>

      {/* Risk summary */}
      <div
        className="rounded-xl p-4 border"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <div className="flex items-center gap-2 mb-3">
          <ShieldAlert size={15} style={{ color: "var(--warning)" }} />
          <span className="text-sm font-semibold" style={{ color: "var(--text)" }}>风险分析摘要</span>
        </div>
        <div className="grid grid-cols-3 gap-3 text-center text-sm mb-3">
          <div>
            <p className="text-xl font-bold text-red-400">{plan.risk_analysis.forbidden_exercises.length}</p>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>禁止动作</p>
          </div>
          <div>
            <p className="text-xl font-bold text-emerald-400">{plan.risk_analysis.safe_exercise_count}</p>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>可用动作</p>
          </div>
          <div>
            <p className="text-xl font-bold text-yellow-400">{plan.risk_analysis.constraints.length}</p>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>动态约束</p>
          </div>
        </div>
        {plan.risk_analysis.forbidden_exercises.length > 0 && (
          <details className="text-xs">
            <summary className="cursor-pointer mb-2" style={{ color: "var(--text-muted)" }}>
              查看 {plan.risk_analysis.forbidden_exercises.length} 个禁止动作
            </summary>
            <ul className="space-y-2">
              {plan.risk_analysis.forbidden_exercises.map((ex) => (
                <li key={ex.name} className="rounded-lg p-2" style={{ background: "var(--surface2)" }}>
                  <p className="font-medium text-red-300">🚫 <ExerciseName name={ex.name} showEnglish={false} /></p>
                  <p style={{ color: "var(--text-muted)" }}>{ex.reason}</p>
                  <p className="text-emerald-400">替代：{translateExerciseText(ex.substitution)}</p>
                </li>
              ))}
            </ul>
          </details>
        )}
        {plan.safety_notes.length > 0 && (
          <div className="mt-3 pt-3 border-t" style={{ borderColor: "var(--border)" }}>
            <p className="text-xs font-medium mb-1" style={{ color: "var(--text)" }}>安全提示</p>
            <ul className="text-xs space-y-1" style={{ color: "var(--text-muted)" }}>
              {plan.safety_notes.map((n, i) => <li key={i}>· {n}</li>)}
            </ul>
          </div>
        )}
      </div>

      {/* Phase tabs */}
      <div>
        <h3 className="text-sm font-semibold mb-3" style={{ color: "var(--text)" }}>详细训练安排</h3>
        <div className="flex flex-wrap gap-2 mb-4">
          {PHASE_ORDER.map((key) => {
            const count = phases[key]?.length ?? 0;
            if (count === 0) return null;
            const meta = PHASE_META[key];
            return (
              <button
                key={key}
                onClick={() => setActivePhase(key)}
                className="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
                style={{
                  background: activePhase === key ? "var(--accent)" : "var(--surface2)",
                  color: activePhase === key ? "#fff" : "var(--text-muted)",
                }}
              >
                {meta.cn} · {count}
              </button>
            );
          })}
        </div>
        <div className="flex flex-col gap-3">
          {(phases[activePhase as keyof typeof phases] ?? []).map((ex, i) => (
            <ExerciseRow key={`${ex.name}-${i}`} ex={ex} index={i + 1} />
          ))}
        </div>
      </div>

      {/* Download */}
      <button
        onClick={() => {
          const blob = new Blob([JSON.stringify(plan, null, 2)], { type: "application/json" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = `${plan.plan_id}.json`;
          a.click();
          URL.revokeObjectURL(url);
        }}
        className="flex items-center justify-center gap-2 py-2 rounded-xl text-sm border"
        style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
      >
        <Download size={14} /> 下载 JSON 计划
      </button>
    </div>
  );
}

function Metric({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div className="rounded-xl p-3 border text-center" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
      {icon && <div className="flex justify-center mb-1 opacity-60">{icon}</div>}
      <p className="text-lg font-bold" style={{ color: "var(--text)" }}>{value}</p>
      <p className="text-xs" style={{ color: "var(--text-muted)" }}>{label}</p>
    </div>
  );
}

function ExerciseRow({ ex, index }: { ex: PlanExercise; index: number }) {
  return (
    <div
      className="flex flex-col gap-3 rounded-xl p-4 border"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
      <div className="flex gap-4">
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-sm" style={{ color: "var(--text)" }}>
            {index}. <ExerciseName name={ex.name} />
          </p>
          <p className="text-xs mt-1" style={{ color: "var(--accent-light)" }}>
            {ex.sets} 组 × {ex.reps} · 休息 {ex.rest_seconds}s
          </p>
          {ex.target_muscle && (
            <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>目标肌群：{muscleCn(ex.target_muscle)}</p>
          )}
        {ex.notes && (
          <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>💡 {translateCoachText(ex.notes)}</p>
        )}
        </div>
      </div>
      <ExerciseGuide name={ex.name} />
    </div>
  );
}
