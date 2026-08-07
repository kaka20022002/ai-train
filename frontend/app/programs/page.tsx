"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { CalendarDays, Loader2, Plus, TrendingUp } from "lucide-react";
import { usersApi, programsApi } from "@/lib/api";
import type { TrainingProgram, ProgramWeek } from "@/lib/api";
import { GOAL_CN, SPLIT_CN } from "@/lib/constants";
import { ProgramWeekTimeline } from "@/components/ProgramWeekTimeline";
import { useUser } from "@/contexts/UserContext";

const STATUS_LABEL: Record<string, string> = {
  active: "进行中",
  completed: "已完成",
  paused: "已暂停",
};

const STATUS_COLOR: Record<string, string> = {
  active: "var(--success)",
  completed: "var(--text-muted)",
  paused: "var(--warning)",
};

export default function ProgramsPage() {
  const { userId } = useUser();
  const [programs, setPrograms] = useState<TrainingProgram[]>([]);
  const [selected, setSelected] = useState<TrainingProgram | null>(null);
  const [advancing, setAdvancing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [advanceReport, setAdvanceReport] = useState<Record<string, unknown> | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const list = await usersApi.programs(userId);
      setPrograms(list);
      if (list.length > 0) {
        const first = await programsApi.get(list[0].program_id);
        setSelected(first);
      }
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  const selectProgram = async (p: TrainingProgram) => {
    try {
      const detail = await programsApi.get(p.program_id);
      setSelected(detail);
      setAdvanceReport(null);
    } catch {
      setSelected(p);
    }
  };

  const handleAdvance = async () => {
    if (!selected) return;
    setAdvancing(true);
    setAdvanceReport(null);
    try {
      const { adaptation_report } = await programsApi.advance(selected.program_id);
      const updated = await programsApi.get(selected.program_id);
      setPrograms((prev) => prev.map((p) => p.program_id === updated.program_id ? updated : p));
      setSelected(updated);
      setAdvanceReport(adaptation_report);
    } catch (err) {
      alert("推进失败：" + (err instanceof Error ? err.message : "未知错误"));
    } finally {
      setAdvancing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-sm" style={{ color: "var(--text-muted)" }}>加载中…</div>
      </div>
    );
  }

  return (
    <div className="flex h-full" style={{ background: "var(--bg)" }}>
      {/* Program list sidebar */}
      <div
        className="w-64 shrink-0 border-r flex flex-col"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <div className="px-4 py-3 border-b flex items-center justify-between" style={{ borderColor: "var(--border)" }}>
          <span className="text-sm font-semibold" style={{ color: "var(--text)" }}>训练计划</span>
          <Link
            href="/generate"
            className="p-1 rounded-lg hover:opacity-80"
            title="生成新计划"
            style={{ color: "var(--accent-light)" }}
          >
            <Plus size={16} />
          </Link>
        </div>
        <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-1">
          {programs.length === 0 ? (
            <div className="text-center mt-6 px-2">
              <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>暂无训练计划</p>
              <Link
                href="/generate"
                className="text-xs px-3 py-1.5 rounded-lg inline-block"
                style={{ background: "var(--accent)", color: "#fff" }}
              >
                去生成计划
              </Link>
            </div>
          ) : (
            programs.map((p) => (
              <button
                key={p.program_id}
                onClick={() => selectProgram(p)}
                className="flex items-start gap-2 px-3 py-2.5 rounded-lg text-left text-xs w-full transition-colors"
                style={{
                  background: selected?.program_id === p.program_id ? "var(--accent)" : "transparent",
                  color: selected?.program_id === p.program_id ? "#fff" : "var(--text-muted)",
                }}
              >
                <CalendarDays size={13} className="mt-0.5 shrink-0" />
                <div>
                  <p className="truncate font-medium">{p.name}</p>
                  <p className="opacity-70">
                    {GOAL_CN[p.goal] ?? p.goal} · 第 {p.current_week}/{p.total_weeks} 周
                  </p>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Detail pane */}
      <div className="flex-1 overflow-y-auto p-6">
        {!selected ? (
          <EmptyState />
        ) : (
          <ProgramDetail
            program={selected}
            onAdvance={handleAdvance}
            advancing={advancing}
            report={advanceReport}
          />
        )}
      </div>
    </div>
  );
}

function ProgramDetail({
  program, onAdvance, advancing, report,
}: {
  program: TrainingProgram;
  onAdvance: () => void;
  advancing: boolean;
  report: Record<string, unknown> | null;
}) {
  const weeks = (program.weeks ?? []) as ProgramWeek[];

  return (
    <div className="max-w-4xl">
      <div className="flex items-start justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold mb-1" style={{ color: "var(--text)" }}>{program.name}</h1>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs" style={{ color: "var(--text-muted)" }}>
            <span>目标：{GOAL_CN[program.goal] ?? program.goal}</span>
            <span>分化：{SPLIT_CN[program.split_type] ?? program.split_type}</span>
            <span>频率：每周 {program.sessions_per_week} 次</span>
            {program.forbidden_exercise_count != null && program.forbidden_exercise_count > 0 && (
              <span>已排除 {program.forbidden_exercise_count} 个高风险动作</span>
            )}
          </div>
        </div>
        <span
          className="text-xs px-2.5 py-1 rounded-full font-medium shrink-0"
          style={{
            background: "rgba(108,99,255,0.1)",
            color: STATUS_COLOR[program.status] ?? "var(--text-muted)",
          }}
        >
          {STATUS_LABEL[program.status] ?? program.status}
        </span>
      </div>

      {program.description && (
        <p className="text-sm mb-5 leading-relaxed" style={{ color: "var(--text-muted)" }}>
          {program.description}
        </p>
      )}

      {/* Progress */}
      <div
        className="rounded-2xl p-4 border mb-6"
        style={{ background: "var(--surface)", borderColor: "var(--border)" }}
      >
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium" style={{ color: "var(--text)" }}>
            第 {program.current_week} / {program.total_weeks} 周
          </span>
          {program.status === "active" && (
            <div className="flex gap-2">
              <Link
                href="/workout"
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium"
                style={{ background: "var(--success)", color: "#fff" }}
              >
                开始今日训练
              </Link>
              <button
                onClick={onAdvance}
                disabled={advancing}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg font-medium disabled:opacity-50"
                style={{ background: "var(--accent)", color: "#fff" }}
              >
                {advancing ? <Loader2 size={12} className="animate-spin" /> : <TrendingUp size={12} />}
                推进下一周
              </button>
            </div>
          )}
        </div>
        <div className="h-2 rounded-full overflow-hidden" style={{ background: "var(--surface2)" }}>
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${(program.current_week / program.total_weeks) * 100}%`,
              background: "var(--accent)",
            }}
          />
        </div>
      </div>

      {/* Advance report */}
      {report && (
        <div
          className="rounded-xl p-4 border mb-6 text-sm"
          style={{ background: "rgba(16,185,129,0.08)", borderColor: "rgba(16,185,129,0.2)", color: "var(--text)" }}
        >
          <p className="font-semibold mb-1 text-emerald-400">✓ 周次已推进</p>
          <p style={{ color: "var(--text-muted)" }}>
            完成率：{typeof report.completion_rate === "number" ? `${Math.round(report.completion_rate * 100)}%` : "—"}　
            平均自觉强度：{typeof report.avg_rpe === "number" ? `${report.avg_rpe.toFixed(1)}/10` : "—"}
          </p>
          {Array.isArray(report.adaptation_notes) && report.adaptation_notes.length > 0 && (
            <ul className="mt-2 text-xs space-y-1" style={{ color: "var(--text-muted)" }}>
              {(report.adaptation_notes as string[]).map((note, i) => (
                <li key={i}>{note}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <ProgramWeekTimeline weeks={weeks} currentWeek={program.current_week} />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center">
      <CalendarDays size={40} style={{ color: "var(--text-muted)" }} className="mb-4" />
      <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>暂无训练计划，先生成一份吧</p>
      <Link
        href="/generate"
        className="text-sm px-4 py-2 rounded-xl font-medium"
        style={{ background: "var(--accent)", color: "#fff" }}
      >
        生成训练计划
      </Link>
    </div>
  );
}
