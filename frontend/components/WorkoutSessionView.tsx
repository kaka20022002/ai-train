"use client";

import { useState } from "react";
import { Clock, Dumbbell } from "lucide-react";
import type { ProgramSession, WorkoutPhases, PlanExercise } from "@/lib/api";
import { PHASE_META, WORKOUT_TYPE_CN } from "@/lib/constants";
import { muscleCn } from "@/lib/exercise-labels";
import { translateIntensityNote } from "@/lib/term-labels";
import { ExerciseName } from "@/components/ExerciseName";
import { ExerciseGuide, ExerciseGuideThumb } from "@/components/ExerciseGuide";

const PHASE_ORDER = [
  "warm_up", "activation", "main_lifts", "accessories", "cool_down",
] as const;

interface Props {
  session: ProgramSession;
  weekLabel?: string;
}

export function WorkoutSessionView({ session, weekLabel }: Props) {
  const phases = session.phases;
  const hasPhases = phases && PHASE_ORDER.some((k) => (phases[k]?.length ?? 0) > 0);
  const [activePhase, setActivePhase] = useState<string>("main_lifts");

  return (
    <div className="flex flex-col gap-4">
      {/* Header card */}
      <div className="rounded-2xl p-4 border"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
        <div className="flex items-start justify-between gap-3 mb-1">
          <div>
            {weekLabel && (
              <p className="text-xs mb-1" style={{ color: "var(--accent-light)" }}>{weekLabel}</p>
            )}
            <h2 className="text-lg font-bold" style={{ color: "var(--text)" }}>{session.label}</h2>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
              {WORKOUT_TYPE_CN[session.workout_type] ?? session.workout_type}
              {session.source_plan_id && " · 已与生成计划同步"}
            </p>
          </div>
          <div className="flex items-center gap-1 text-xs shrink-0" style={{ color: "var(--text-muted)" }}>
            <Clock size={13} /> {session.estimated_duration_minutes} 分钟
          </div>
        </div>
        {session.notes && (
          <p className="text-xs leading-relaxed mt-2" style={{ color: "var(--text-muted)" }}>
            {session.notes}
          </p>
        )}
      </div>

      {/* Exercises */}
      {hasPhases && phases
        ? <PhasedView phases={phases} activePhase={activePhase} onPhaseChange={setActivePhase} />
        : <FlatExerciseList exercises={session.key_exercises ?? []} />}
    </div>
  );
}

function PhasedView({
  phases, activePhase, onPhaseChange,
}: {
  phases: WorkoutPhases;
  activePhase: string;
  onPhaseChange: (p: string) => void;
}) {
  const list = (phases[activePhase as keyof WorkoutPhases] ?? []) as PlanExercise[];

  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-4">
        {PHASE_ORDER.map((key) => {
          const count = phases[key]?.length ?? 0;
          if (count === 0) return null;
          const meta = PHASE_META[key];
          const active = activePhase === key;
          return (
            <button key={key} onClick={() => onPhaseChange(key)}
              className="text-xs px-3 py-1.5 rounded-lg border transition-colors"
              style={{
                borderColor: active ? meta.color : "var(--border)",
                background: active ? `${meta.color}22` : "var(--surface)",
                color: active ? meta.color : "var(--text-muted)",
              }}>
              {meta.cn} ({count})
            </button>
          );
        })}
      </div>
      <ExerciseCards exercises={list} />
    </div>
  );
}

function FlatExerciseList({ exercises }: { exercises: ProgramSession["key_exercises"] }) {
  const mapped: PlanExercise[] = exercises.map((ex) => ({
    name: ex.name,
    sets: ex.sets,
    reps: ex.reps,
    rest_seconds: ex.rest_seconds,
    notes: ex.intensity_note,
    target_muscle: ex.target_muscle,
  }));
  return <ExerciseCards exercises={mapped} />;
}

function ExerciseCards({ exercises }: { exercises: PlanExercise[] }) {
  if (exercises.length === 0) {
    return (
      <p className="text-sm text-center py-8" style={{ color: "var(--text-muted)" }}>
        暂无动作安排
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {exercises.map((ex, i) => (
        <div key={`${ex.name}-${i}`} className="rounded-xl border p-4"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
          <div className="flex gap-3">
            <ExerciseGuideThumb name={ex.name} size={72} />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-mono" style={{ color: "var(--text-muted)" }}>
                  #{i + 1}
                </span>
                <ExerciseName name={ex.name} showEnglish={false} className="font-semibold text-sm" />
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs" style={{ color: "var(--accent-light)" }}>
                <span className="flex items-center gap-1">
                  <Dumbbell size={11} /> {ex.sets} × {ex.reps}
                </span>
                <span>休息 {ex.rest_seconds}s</span>
                {ex.target_muscle && (
                  <span style={{ color: "var(--text-muted)" }}>{muscleCn(ex.target_muscle)}</span>
                )}
              </div>
              {ex.notes && (
                <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                  {translateIntensityNote(ex.notes)}
                </p>
              )}
              <ExerciseGuide name={ex.name} techniqueOnly defaultOpen={false} />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
