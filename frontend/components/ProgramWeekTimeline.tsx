"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Clock, Dumbbell } from "lucide-react";
import type { ProgramWeek, ProgramSession } from "@/lib/api";
import { WEEK_TYPE_CN, WORKOUT_TYPE_CN } from "@/lib/constants";
import { muscleCn } from "@/lib/exercise-labels";
import { translateIntensityNote } from "@/lib/term-labels";
import { ExerciseName } from "@/components/ExerciseName";
import { ExerciseGuide, ExerciseGuideThumb } from "@/components/ExerciseGuide";

interface Props {
  weeks: ProgramWeek[];
  currentWeek: number;
}

export function ProgramWeekTimeline({ weeks, currentWeek }: Props) {
  const [expanded, setExpanded] = useState<Set<number>>(
    () => new Set([currentWeek, 1])
  );
  const [expandAll, setExpandAll] = useState(false);

  const toggle = (wn: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(wn)) next.delete(wn);
      else next.add(wn);
      return next;
    });
  };

  const handleExpandAll = () => {
    if (expandAll) {
      setExpanded(new Set([currentWeek]));
      setExpandAll(false);
    } else {
      setExpanded(new Set(weeks.map((w) => w.week_number)));
      setExpandAll(true);
    }
  };

  if (weeks.length === 0) {
    return (
      <p className="text-sm text-center py-8" style={{ color: "var(--text-muted)" }}>
        暂无周次数据，请重新生成训练计划
      </p>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>
          完整训练日历（{weeks.length} 周）
        </h2>
        <button
          onClick={handleExpandAll}
          className="text-xs px-2.5 py-1 rounded-lg border"
          style={{ borderColor: "var(--border)", color: "var(--accent-light)" }}
        >
          {expandAll ? "收起全部" : "展开全部周次"}
        </button>
      </div>

      <div className="flex flex-col gap-3">
        {weeks.map((week) => (
          <WeekCard
            key={week.week_number}
            week={week}
            isCurrent={week.week_number === currentWeek}
            isPast={week.week_number < currentWeek}
            isOpen={expanded.has(week.week_number)}
            onToggle={() => toggle(week.week_number)}
          />
        ))}
      </div>
    </div>
  );
}

function WeekCard({
  week, isCurrent, isPast, isOpen, onToggle,
}: {
  week: ProgramWeek;
  isCurrent: boolean;
  isPast: boolean;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const weekType = week.actual_week_type ?? week.week_type ?? "";
  const sessions = week.sessions ?? [];
  const totalSets = sessions.reduce(
    (n, s) => n + (s.key_exercises?.reduce((a, e) => a + (e.sets ?? 0), 0) ?? 0), 0
  );

  return (
    <div
      className="rounded-xl border overflow-hidden"
      style={{
        borderColor: isCurrent ? "var(--accent)" : "var(--border)",
        background: isCurrent ? "rgba(108,99,255,0.06)" : "var(--surface)",
      }}
    >
      {/* Week header — clickable */}
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3.5 text-left hover:opacity-90 transition-opacity"
      >
        {isOpen
          ? <ChevronDown size={16} style={{ color: "var(--accent-light)" }} />
          : <ChevronRight size={16} style={{ color: "var(--text-muted)" }} />}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold" style={{ color: isCurrent ? "var(--accent-light)" : "var(--text)" }}>
              {week.label ?? `第 ${week.week_number} 周`}
            </span>
            {isCurrent && (
              <span className="text-[10px] px-1.5 py-0.5 rounded font-medium" style={{ background: "var(--accent)", color: "#fff" }}>
                当前周
              </span>
            )}
            {isPast && !isCurrent && (
              <span className="text-[10px]" style={{ color: "var(--success)" }}>✓ 已过</span>
            )}
            {weekType && (
              <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: "var(--surface2)", color: "var(--text-muted)" }}>
                {WEEK_TYPE_CN[weekType] ?? weekType}
              </span>
            )}
          </div>
          <p className="text-xs mt-0.5 truncate" style={{ color: "var(--text-muted)" }}>
            {sessions.length} 次训练 · 共 {totalSets} 组
            {week.intensity_note ? ` · ${week.intensity_note}` : ""}
          </p>
        </div>
      </button>

      {/* Expanded sessions */}
      {isOpen && (
        <div className="px-4 pb-4 flex flex-col gap-3 border-t" style={{ borderColor: "var(--border)" }}>
          {week.intensity_note && (
            <p className="text-xs pt-3" style={{ color: "var(--warning)" }}>
              📋 本周强度指引：{week.intensity_note}
              {week.volume_modifier != null && week.volume_modifier !== 1 && (
                <span>（训练量 ×{week.volume_modifier}）</span>
              )}
            </p>
          )}

          {sessions.length === 0 ? (
            <p className="text-xs py-2" style={{ color: "var(--text-muted)" }}>本周暂无训练安排</p>
          ) : (
            sessions.map((session) => (
              <SessionCard key={session.session_number} session={session} />
            ))
          )}

          {week.adaptation_notes && week.adaptation_notes.length > 0 && (
            <div className="text-xs rounded-lg p-2.5" style={{ background: "var(--surface2)", color: "var(--text-muted)" }}>
              {week.adaptation_notes.map((n, i) => <p key={i}>· {n}</p>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SessionCard({ session }: { session: ProgramSession }) {
  const exercises = session.key_exercises ?? [];
  return (
    <div
      className="rounded-xl border mt-3"
      style={{ background: "var(--surface2)", borderColor: "var(--border)" }}
    >
      {/* Session header */}
      <div className="px-4 py-3 border-b flex items-start justify-between gap-2" style={{ borderColor: "var(--border)" }}>
        <div>
          <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>
            训练 {session.session_number}：{session.label}
          </p>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
            {WORKOUT_TYPE_CN[session.workout_type] ?? session.workout_type}
          </p>
        </div>
        <div className="flex items-center gap-1 text-xs shrink-0" style={{ color: "var(--text-muted)" }}>
          <Clock size={12} />
          {session.estimated_duration_minutes} 分钟
        </div>
      </div>

      {/* Exercise table */}
      {exercises.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr style={{ color: "var(--text-muted)" }}>
                <th className="text-left px-4 py-2 font-medium w-8">#</th>
                <th className="text-left px-2 py-2 font-medium w-[100px]">演示</th>
                <th className="text-left px-2 py-2 font-medium">动作</th>
                <th className="text-left px-2 py-2 font-medium">组×次</th>
                <th className="text-left px-2 py-2 font-medium">休息</th>
                <th className="text-left px-2 py-2 font-medium hidden sm:table-cell">肌群</th>
                <th className="text-left px-4 py-2 font-medium hidden md:table-cell">强度</th>
              </tr>
            </thead>
            <tbody>
              {exercises.map((ex, i) => (
                <tr key={i} className="border-t align-top" style={{ borderColor: "var(--border)" }}>
                  <td className="px-4 py-3" style={{ color: "var(--text-muted)" }}>{i + 1}</td>
                  <td className="px-2 py-3">
                    <ExerciseGuideThumb name={ex.name} size={88} />
                  </td>
                  <td className="px-2 py-3 font-medium">
                    <ExerciseName name={ex.name} showEnglish={false} />
                    <ExerciseGuide name={ex.name} techniqueOnly defaultOpen={false} />
                  </td>
                  <td className="px-2 py-3 whitespace-nowrap" style={{ color: "var(--accent-light)" }}>
                    {ex.sets} × {ex.reps}
                  </td>
                  <td className="px-2 py-3 whitespace-nowrap" style={{ color: "var(--text-muted)" }}>
                    {ex.rest_seconds}s
                  </td>
                  <td className="px-2 py-3 hidden sm:table-cell" style={{ color: "var(--text-muted)" }}>
                    {muscleCn(ex.target_muscle ?? "")}
                  </td>
                  <td className="px-4 py-3 hidden md:table-cell" style={{ color: "var(--text-muted)" }}>
                    {translateIntensityNote(ex.intensity_note) || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-4 py-3 text-xs" style={{ color: "var(--text-muted)" }}>暂无动作安排</p>
      )}

      {session.notes && (
        <p className="px-4 py-2.5 text-xs border-t flex items-start gap-1.5" style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}>
          <Dumbbell size={12} className="mt-0.5 shrink-0" />
          {session.notes}
        </p>
      )}
    </div>
  );
}
