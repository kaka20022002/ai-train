"use client";

import { useState } from "react";
import { Search, Loader2, Save } from "lucide-react";
import { riskApi, usersApi } from "@/lib/api";
import type { RiskAnalysisResult } from "@/lib/api";
import { FITNESS_CN, JOINT_CN } from "@/lib/constants";
import { translateExerciseText } from "@/lib/exercise-labels";
import { ExerciseName } from "@/components/ExerciseName";
import { InjuryEditor, injuriesToMedicalHistory, newInjury, type InjuryDraft } from "@/components/InjuryEditor";
import { useUser } from "@/contexts/UserContext";
import { formatSafetyRevalidation } from "@/lib/safety-revalidation";

export default function RiskPage() {
  const { userId, setUserId, profile, refreshProfile } = useUser();
  const [fitnessLevel, setFitnessLevel] = useState("intermediate");
  const [injuries, setInjuries] = useState<InjuryDraft[]>([newInjury()]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RiskAnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState<string | null>(null);

  const analyze = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await riskApi.analyze({
        user_id: userId,
        basic_info: { age: 28, gender: "male" },
        fitness_level: fitnessLevel as "beginner" | "intermediate" | "advanced",
        medical_history: injuriesToMedicalHistory(injuries),
      });
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "分析失败");
    } finally {
      setLoading(false);
    }
  };

  const syncToProfile = async () => {
    setSyncing(true);
    setSyncMsg(null);
    setError(null);
    const medical_history = injuriesToMedicalHistory(injuries);
    try {
      let updated;
      try {
        await usersApi.get(userId);
        updated = await usersApi.update(userId, {
          medical_history,
          fitness_level: fitnessLevel as "beginner" | "intermediate" | "advanced",
        });
      } catch {
        const bi = profile?.basic_info;
        updated = await usersApi.create({
          user_id: userId,
          basic_info: {
            age: bi?.age ?? 28,
            gender: bi?.gender ?? "male",
            height_cm: bi?.height_cm,
            weight_kg: bi?.weight_kg,
          },
          fitness_level: fitnessLevel as "beginner" | "intermediate" | "advanced",
          fitness_goal: profile?.fitness_goal,
          training_frequency: profile?.training_frequency,
          available_equipment: profile?.available_equipment,
          medical_history,
        });
      }
      await refreshProfile();
      setSyncMsg(formatSafetyRevalidation(updated.safety_revalidation));
    } catch (e) {
      setError(e instanceof Error ? e.message : "同步失败");
    } finally {
      setSyncing(false);
    }
  };

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text)" }}>伤病风险分析</h1>
      <p className="text-sm mb-6" style={{ color: "var(--text-muted)" }}>
        输入伤病史，查看哪些动作应被禁止及推荐替代
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="flex flex-col gap-4">
          <label className="text-xs flex flex-col gap-1" style={{ color: "var(--text-muted)" }}>
            用户 ID
            <input value={userId} onChange={(e) => setUserId(e.target.value)}
              className="rounded-lg px-3 py-2 text-sm border"
              style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }} />
          </label>
          <label className="text-xs flex flex-col gap-1" style={{ color: "var(--text-muted)" }}>
            训练水平
            <select value={fitnessLevel} onChange={(e) => setFitnessLevel(e.target.value)}
              className="rounded-lg px-3 py-2 text-sm border"
              style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }}>
              {Object.entries(FITNESS_CN).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </label>
          <InjuryEditor injuries={injuries} onChange={setInjuries} />
          <button type="button" onClick={analyze} disabled={loading}
            className="flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-medium disabled:opacity-50"
            style={{ background: "var(--accent)", color: "#fff" }}>
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Search size={16} />}
            开始分析
          </button>
          {result && (
            <button
              type="button"
              onClick={() => void syncToProfile()}
              disabled={syncing}
              className="flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-medium border disabled:opacity-50"
              style={{ borderColor: "var(--border)", color: "var(--accent)", background: "var(--surface)" }}
            >
              {syncing ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
              同步伤病史到档案
            </button>
          )}
        </div>

        <div>
          {syncMsg && (
            <p className="text-sm rounded-xl p-4 mb-4" style={{ color: "var(--success)", background: "rgba(16,185,129,0.1)" }}>
              {syncMsg}
            </p>
          )}
          {error && (
            <p className="text-sm rounded-xl p-4" style={{ color: "var(--danger)", background: "rgba(239,68,68,0.1)" }}>{error}</p>
          )}
          {result && (
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-2 gap-3">
                <StatBox value={result.summary.forbidden_count} label="禁止动作" color="#f87171" />
                <StatBox value={result.summary.safe_count} label={`可用动作（共 ${result.summary.total_exercises}）`} color="#4ade80" />
              </div>
              {result.forbidden_exercises.length === 0 ? (
                <p className="text-sm rounded-xl p-4" style={{ color: "var(--success)", background: "rgba(16,185,129,0.1)" }}>
                  ✅ 无禁忌动作，所有动作均可安全训练
                </p>
              ) : (
                <div className="rounded-xl border overflow-hidden" style={{ borderColor: "var(--border)" }}>
                  <table className="w-full text-xs">
                    <thead>
                      <tr style={{ background: "var(--surface2)" }}>
                        {["动作", "风险", "涉及关节", "禁止原因", "替代"].map((h) => (
                          <th key={h} className="text-left px-3 py-2 font-medium" style={{ color: "var(--text-muted)" }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.forbidden_exercises.map((ex) => (
                        <tr key={ex.name} className="border-t" style={{ borderColor: "var(--border)" }}>
                          <td className="px-3 py-2 font-medium"><ExerciseName name={ex.name} /></td>
                          <td className="px-3 py-2">
                            <span className="px-1.5 py-0.5 rounded text-red-300" style={{ background: "rgba(239,68,68,0.15)" }}>
                              {ex.risk_level}/5
                            </span>
                          </td>
                          <td className="px-3 py-2" style={{ color: "var(--text-muted)" }}>
                            {ex.involved_joints.map((j) => JOINT_CN[j] ?? j).join("、")}
                          </td>
                          <td className="px-3 py-2 max-w-[180px]" style={{ color: "var(--text-muted)" }}>{ex.reason}</td>
                          <td className="px-3 py-2 text-emerald-400">{translateExerciseText(ex.substitution)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
          {!result && !error && !loading && (
            <p className="text-sm text-center py-16" style={{ color: "var(--text-muted)" }}>
              填写左侧伤病史后点击「开始分析」
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function StatBox({ value, label, color }: { value: number; label: string; color: string }) {
  return (
    <div className="rounded-xl p-4 border text-center" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
      <p className="text-3xl font-bold" style={{ color }}>{value}</p>
      <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{label}</p>
    </div>
  );
}
