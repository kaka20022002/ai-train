"use client";

import { useEffect, useState } from "react";
import { Loader2, CheckCircle, Dumbbell, TrendingUp } from "lucide-react";
import { usersApi, insightsApi } from "@/lib/api";
import type { LogSessionRequest, ExercisePerformance, NextSetSuggestion } from "@/lib/api";
import { INJURY_LOCATIONS, JOINT_CN, RPE_HINT, formatRpe } from "@/lib/constants";

interface ExerciseInput {
  name: string;
  sets: number;
  reps: string;
}

interface Props {
  userId: string;
  programId?: string;
  programWeek?: number;
  workoutType?: string;
  planId?: string;
  exercises?: ExerciseInput[];
  onSuccess?: () => void;
  onCancel?: () => void;
}

interface PerfRow {
  name: string;
  weight: string;        // kg, free text to allow blank
  reps: string[];        // one entry per set
}

function defaultSetCount(sets: number): number {
  return Math.max(1, Math.min(6, sets || 3));
}

export function SessionLogForm({
  userId, programId, programWeek, workoutType, planId, exercises, onSuccess, onCancel,
}: Props) {
  const [rpe, setRpe] = useState(7);
  const [completion, setCompletion] = useState(90);
  const [hasPain, setHasPain] = useState(false);
  const [painLoc, setPainLoc] = useState("knee");
  const [painSev, setPainSev] = useState(5);
  const [fatigue, setFatigue] = useState(5);
  const [sleep, setSleep] = useState(7);
  const [stress, setStress] = useState(4);
  const [duration, setDuration] = useState(60);
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  // ── Per-exercise performance (drives progressive overload) ──────────────────
  const [logPerf, setLogPerf] = useState(true);
  const [perf, setPerf] = useState<PerfRow[]>(
    () =>
      (exercises ?? []).map((e) => ({
        name: e.name,
        weight: "",
        reps: Array(defaultSetCount(e.sets)).fill(""),
      }))
  );
  const [suggestions, setSuggestions] = useState<Record<string, NextSetSuggestion>>({});

  // Fetch prior progression suggestions to prefill weights & show guidance.
  useEffect(() => {
    if (!exercises || exercises.length === 0) return;
    let alive = true;
    insightsApi
      .progression(userId)
      .then((res) => {
        if (!alive) return;
        const map: Record<string, NextSetSuggestion> = {};
        for (const r of res.reports) map[r.exercise_name] = r.suggestion;
        setSuggestions(map);
        // Prefill weight with the suggested load when available and still blank.
        setPerf((prev) =>
          prev.map((row) => {
            const s = map[row.name];
            if (s?.suggested_weight_kg != null && row.weight === "") {
              return { ...row, weight: String(s.suggested_weight_kg) };
            }
            return row;
          })
        );
      })
      .catch(() => void 0);
    return () => {
      alive = false;
    };
  }, [userId, exercises]);

  const updateRow = (i: number, patch: Partial<PerfRow>) =>
    setPerf((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  const updateRep = (rowIdx: number, setIdx: number, value: string) =>
    setPerf((prev) =>
      prev.map((r, idx) =>
        idx === rowIdx
          ? { ...r, reps: r.reps.map((v, s) => (s === setIdx ? value : v)) }
          : r
      )
    );

  const buildPerformance = (): ExercisePerformance[] | undefined => {
    if (!logPerf) return undefined;
    const out: ExercisePerformance[] = [];
    for (const row of perf) {
      const reps = row.reps.map((r) => parseInt(r, 10)).filter((n) => !Number.isNaN(n) && n > 0);
      const weight = parseFloat(row.weight);
      const hasWeight = !Number.isNaN(weight) && weight > 0;
      if (!hasWeight && reps.length === 0) continue; // nothing logged for this exercise
      out.push({
        name: row.name,
        weight_kg: hasWeight ? weight : undefined,
        sets_completed: reps.length || undefined,
        reps_per_set: reps.length ? reps : undefined,
      });
    }
    return out.length ? out : undefined;
  };

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);
    try {
      const body: LogSessionRequest = {
        rpe,
        completion_rate: completion / 100,
        workout_type: workoutType,
        duration_minutes: duration,
        program_id: programId,
        program_week: programWeek,
        plan_id: planId,
        pain_feedback: hasPain
          ? { has_pain: true, pain_location: painLoc, pain_severity: painSev }
          : { has_pain: false },
        fatigue_feedback: { overall_fatigue: fatigue, sleep_quality_last_night: sleep, stress_level: stress },
        exercise_performance: buildPerformance(),
        notes: notes || undefined,
      };
      await usersApi.logSession(userId, body);
      setDone(true);
      onSuccess?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setLoading(false);
    }
  };

  if (done) {
    return (
      <div className="rounded-2xl p-6 border text-center"
        style={{ background: "rgba(34,197,94,0.08)", borderColor: "rgba(34,197,94,0.3)" }}>
        <CheckCircle size={32} className="mx-auto mb-2" style={{ color: "var(--success)" }} />
        <p className="font-medium mb-1" style={{ color: "var(--text)" }}>训练记录已保存</p>
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          下次生成计划时将参考本次自觉强度与反馈
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border p-5 flex flex-col gap-4"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
      <h3 className="text-sm font-semibold" style={{ color: "var(--text)" }}>记录本次训练</h3>

      <label className="text-xs" style={{ color: "var(--text-muted)" }}>
        {formatRpe(rpe)}
        <p className="text-[10px] mt-0.5 mb-1 opacity-80">{RPE_HINT}</p>
        <input type="range" min={1} max={10} value={rpe}
          onChange={(e) => setRpe(+e.target.value)} className="w-full" />
      </label>

      <label className="text-xs" style={{ color: "var(--text-muted)" }}>
        完成率：{completion}%
        <input type="range" min={0} max={100} step={5} value={completion}
          onChange={(e) => setCompletion(+e.target.value)} className="w-full mt-1" />
      </label>

      <label className="text-xs flex flex-col gap-1" style={{ color: "var(--text-muted)" }}>
        训练时长（分钟）
        <input type="number" min={10} max={180} value={duration}
          onChange={(e) => setDuration(+e.target.value)}
          className="rounded-lg px-3 py-2 text-sm border outline-none"
          style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }} />
      </label>

      <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text)" }}>
        <input type="checkbox" checked={hasPain}
          onChange={(e) => setHasPain(e.target.checked)} />
        训练中有疼痛
      </label>

      {hasPain && (
        <div className="grid grid-cols-2 gap-3">
          <select value={painLoc} onChange={(e) => setPainLoc(e.target.value)}
            className="rounded-lg px-3 py-2 text-sm border outline-none"
            style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }}>
            {INJURY_LOCATIONS.map((l) => (
              <option key={l} value={l}>{JOINT_CN[l]}</option>
            ))}
          </select>
          <input type="number" min={1} max={10} value={painSev}
            onChange={(e) => setPainSev(+e.target.value)} placeholder="疼痛强度 1-10"
            className="rounded-lg px-3 py-2 text-sm border outline-none"
            style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }} />
        </div>
      )}

      <label className="text-xs" style={{ color: "var(--text-muted)" }}>
        疲劳度：{fatigue}
        <input type="range" min={1} max={10} value={fatigue}
          onChange={(e) => setFatigue(+e.target.value)} className="w-full mt-1" />
      </label>

      <label className="text-xs" style={{ color: "var(--text-muted)" }}>
        昨晚睡眠质量：{sleep}
        <input type="range" min={1} max={10} value={sleep}
          onChange={(e) => setSleep(+e.target.value)} className="w-full mt-1" />
      </label>

      <label className="text-xs" style={{ color: "var(--text-muted)" }}>
        当前压力水平：{stress}
        <input type="range" min={1} max={10} value={stress}
          onChange={(e) => setStress(+e.target.value)} className="w-full mt-1" />
      </label>

      {/* 逐动作重量/次数记录 → 渐进超负荷 */}
      {exercises && exercises.length > 0 && (
        <div className="rounded-xl border p-3 flex flex-col gap-3"
          style={{ borderColor: "var(--border)", background: "var(--surface2)" }}>
          <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text)" }}>
            <input type="checkbox" checked={logPerf}
              onChange={(e) => setLogPerf(e.target.checked)} />
            <Dumbbell size={14} style={{ color: "var(--accent)" }} />
            记录每个动作的重量/次数（用于渐进超负荷）
          </label>

          {logPerf && perf.map((row, i) => {
            const s = suggestions[row.name];
            return (
              <div key={row.name} className="flex flex-col gap-1.5 pb-2 border-b last:border-b-0"
                style={{ borderColor: "var(--border)" }}>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium truncate" style={{ color: "var(--text)" }}>
                    {row.name}
                  </span>
                  {s?.est_1rm != null && (
                    <span className="text-[10px] shrink-0" style={{ color: "var(--text-muted)" }}>
                      估算1RM {s.est_1rm}kg
                    </span>
                  )}
                </div>

                {s && (
                  <p className="text-[11px] inline-flex items-start gap-1" style={{ color: "var(--accent-light)" }}>
                    <TrendingUp size={11} className="mt-0.5 shrink-0" />
                    <span>{s.rationale}</span>
                  </p>
                )}

                <div className="flex items-center gap-2">
                  <input type="number" inputMode="decimal" step="0.5" min={0} value={row.weight}
                    onChange={(e) => updateRow(i, { weight: e.target.value })}
                    placeholder="重量kg"
                    className="w-20 rounded-lg px-2 py-1.5 text-sm border outline-none"
                    style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }} />
                  <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>kg ×</span>
                  <div className="flex flex-wrap gap-1.5">
                    {row.reps.map((rv, si) => (
                      <input key={si} type="number" inputMode="numeric" min={0} value={rv}
                        onChange={(e) => updateRep(i, si, e.target.value)}
                        placeholder={`组${si + 1}`}
                        className="w-12 rounded-lg px-1.5 py-1.5 text-sm border outline-none text-center"
                        style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }} />
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
          {logPerf && (
            <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>
              填写后，系统会在下次训练给出加重/加次建议。留空的动作会被忽略。
            </p>
          )}
        </div>
      )}

      <textarea value={notes} onChange={(e) => setNotes(e.target.value)}
        placeholder="备注（可选）" rows={2}
        className="w-full rounded-lg px-3 py-2 text-sm border outline-none resize-none"
        style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }} />

      {error && <p className="text-xs" style={{ color: "var(--danger)" }}>{error}</p>}

      <div className="flex gap-2">
        {onCancel && (
          <button type="button" onClick={onCancel}
            className="flex-1 py-2.5 rounded-xl text-sm border"
            style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}>
            取消
          </button>
        )}
        <button type="button" onClick={handleSubmit} disabled={loading}
          className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium disabled:opacity-50"
          style={{ background: "var(--accent)", color: "#fff" }}>
          {loading && <Loader2 size={14} className="animate-spin" />}
          保存训练记录
        </button>
      </div>
    </div>
  );
}
