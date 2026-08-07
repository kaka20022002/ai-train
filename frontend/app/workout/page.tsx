"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, Dumbbell, ChevronRight, TrendingUp } from "lucide-react";
import { programsApi, usersApi } from "@/lib/api";
import type { NextSessionResponse, ProgramSession } from "@/lib/api";
import { useUser } from "@/contexts/UserContext";
import { WorkoutSessionView } from "@/components/WorkoutSessionView";
import { SessionLogForm } from "@/components/SessionLogForm";
import { ReadinessCard } from "@/components/ReadinessCard";

/** 提取本次训练的主项+辅助动作（用于逐动作重量/次数记录）。 */
function sessionExercises(session: ProgramSession): { name: string; sets: number; reps: string }[] {
  if (session.phases) {
    return [...session.phases.main_lifts, ...session.phases.accessories].map((e) => ({
      name: e.name,
      sets: e.sets,
      reps: e.reps,
    }));
  }
  return session.key_exercises.map((e) => ({ name: e.name, sets: e.sets, reps: e.reps }));
}

export default function WorkoutPage() {
  const { userId } = useUser();
  const [loading, setLoading] = useState(true);
  const [next, setNext] = useState<NextSessionResponse | null>(null);
  const [programName, setProgramName] = useState<string>("");
  const [activeProgramId, setActiveProgramId] = useState<string>("");
  const [showLog, setShowLog] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setShowLog(false);
    try {
      const programs = await usersApi.programs(userId);
      const active = programs.find((p) => p.status === "active");
      if (!active) {
        setNext(null);
        setProgramName("");
        setActiveProgramId("");
        return;
      }
      setProgramName(active.name);
      setActiveProgramId(active.program_id);
      const data = await programsApi.nextSession(active.program_id);
      setNext(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--accent)" }} />
      </div>
    );
  }

  const session = next?.next_session;
  const weekLabel = next
    ? `第 ${next.current_week} 周 · 本周 ${next.sessions_completed_this_week}/${next.sessions_planned_this_week} 次`
    : undefined;

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text)" }}>今日训练</h1>
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          {programName ? `当前计划：${programName}` : "完成训练并记录反馈，系统会自动优化下次计划"}
        </p>
      </div>

      {error && (
        <div className="rounded-xl p-4 text-sm border mb-4"
          style={{ background: "rgba(239,68,68,0.1)", borderColor: "rgba(239,68,68,0.3)", color: "var(--danger)" }}>
          {error}
        </div>
      )}

      {/* 今日训练准备度评分 */}
      {!showLog && <ReadinessCard userId={userId} />}

      {/* 无进行中的计划 */}
      {!next && !error && <NoProgram />}

      {/* 本周全部完成 */}
      {next && !session && !showLog && (
        <WeekDone
          message={next.message}
          programId={activeProgramId}
          onAdvanced={load}
        />
      )}

      {/* 展示当前训练 */}
      {session && !showLog && (
        <>
          <p className="text-sm mb-3 px-1" style={{ color: "var(--accent-light)" }}>
            {next?.message}
          </p>
          <WorkoutSessionView session={session} weekLabel={weekLabel} />
          <button onClick={() => setShowLog(true)}
            className="w-full mt-6 py-3 rounded-xl font-medium text-sm"
            style={{ background: "var(--accent)", color: "#fff" }}>
            完成训练，记录反馈
          </button>
        </>
      )}

      {/* 训练记录表单 */}
      {session && showLog && (
        <SessionLogForm
          userId={userId}
          programId={activeProgramId}
          programWeek={next?.current_week}
          workoutType={session.workout_type}
          planId={session.source_plan_id}
          exercises={sessionExercises(session)}
          onSuccess={load}
          onCancel={() => setShowLog(false)}
        />
      )}
    </div>
  );
}

function NoProgram() {
  return (
    <div className="rounded-2xl p-10 text-center border"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
      <Dumbbell size={40} className="mx-auto mb-4" style={{ color: "var(--text-muted)" }} />
      <p className="text-sm mb-2" style={{ color: "var(--text)" }}>暂无进行中的训练计划</p>
      <p className="text-xs mb-6" style={{ color: "var(--text-muted)" }}>
        先在「生成计划」创建一份，系统会自动生成 4 周周期计划
      </p>
      <Link href="/generate"
        className="inline-flex items-center gap-1 text-sm px-4 py-2 rounded-xl font-medium"
        style={{ background: "var(--accent)", color: "#fff" }}>
        去生成计划 <ChevronRight size={14} />
      </Link>
    </div>
  );
}

function WeekDone({
  message, programId, onAdvanced,
}: {
  message: string;
  programId: string;
  onAdvanced: () => void;
}) {
  const [advancing, setAdvancing] = useState(false);

  const handleAdvance = async () => {
    setAdvancing(true);
    try {
      await programsApi.advance(programId);
      onAdvanced();
    } catch (e) {
      alert(e instanceof Error ? e.message : "推进失败");
    } finally {
      setAdvancing(false);
    }
  };

  return (
    <div className="rounded-2xl p-8 text-center border"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
      <p className="text-sm mb-6" style={{ color: "var(--text)" }}>{message}</p>
      <div className="flex flex-col sm:flex-row gap-3 justify-center">
        <button onClick={handleAdvance} disabled={advancing}
          className="flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50"
          style={{ background: "var(--accent)", color: "#fff" }}>
          {advancing
            ? <Loader2 size={14} className="animate-spin" />
            : <TrendingUp size={14} />}
          推进到下一周
        </button>
        <Link href="/programs"
          className="px-4 py-2.5 rounded-xl text-sm border"
          style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}>
          查看训练计划
        </Link>
      </div>
    </div>
  );
}
