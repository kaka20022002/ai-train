"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, Rocket, ChevronDown, ChevronUp } from "lucide-react";
import { plansApi, usersApi } from "@/lib/api";
import type { GeneratePlanResponse } from "@/lib/api";
import {
  FITNESS_CN, WORKOUT_TYPE_CN, GOAL_CN, INJURY_LOCATIONS, JOINT_CN, RPE_HINT, formatRpe,
} from "@/lib/constants";
import { InjuryEditor, injuriesToMedicalHistory, medicalHistoryToInjuries, newInjury, type InjuryDraft } from "@/components/InjuryEditor";
import { EquipmentSelector } from "@/components/EquipmentSelector";
import { PlanResult } from "@/components/PlanResult";
import { useUser } from "@/contexts/UserContext";

export default function GeneratePage() {
  const { userId, setUserId, profile } = useUser();

  const [fitnessLevel, setFitnessLevel] = useState("intermediate");
  const [age, setAge] = useState(28);
  const [weight, setWeight] = useState(78);
  const [height, setHeight] = useState(175);
  const [gender, setGender] = useState("male");
  const [workoutType, setWorkoutType] = useState("full_body");
  const [fitnessGoal, setFitnessGoal] = useState("strength");
  const [frequency, setFrequency] = useState(3);
  const [equipment, setEquipment] = useState<string[]>([]);
  const [injuries, setInjuries] = useState<InjuryDraft[]>([newInjury()]);
  const [useHistory, setUseHistory] = useState(false);
  const [showFeedback, setShowFeedback] = useState(false);
  const [rpe, setRpe] = useState(7);
  const [hasPain, setHasPain] = useState(false);
  const [painLoc, setPainLoc] = useState("knee");
  const [painSev, setPainSev] = useState(5);
  const [fatigue, setFatigue] = useState(6);
  const [sleep, setSleep] = useState(7);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<GeneratePlanResponse | null>(null);
  const [elapsed, setElapsed] = useState<number | undefined>();

  // Prefill from profile when available
  useEffect(() => {
    if (!profile) return;
    const bi = profile.basic_info;
    if (bi.age) setAge(bi.age);
    if (bi.gender) setGender(bi.gender);
    if (bi.height_cm) setHeight(bi.height_cm);
    if (bi.weight_kg) setWeight(bi.weight_kg);
    if (profile.fitness_level) setFitnessLevel(profile.fitness_level);
    if (profile.fitness_goal) setFitnessGoal(profile.fitness_goal);
    if (profile.training_frequency) setFrequency(profile.training_frequency);
    if (profile.available_equipment) setEquipment(profile.available_equipment);
    if (profile.medical_history.length > 0) {
      setInjuries(medicalHistoryToInjuries(profile.medical_history));
    }
  }, [profile]);

  const handleGenerate = async () => {
    setLoading(true);
    setError(null);
    setPlan(null);
    const t0 = Date.now();
    try {
      // Ensure user exists before generating
      try {
        await usersApi.get(userId);
      } catch {
        await usersApi.create({
          user_id: userId,
          basic_info: { age, gender, height_cm: height, weight_kg: weight },
          fitness_level: fitnessLevel as "beginner" | "intermediate" | "advanced",
          fitness_goal: fitnessGoal,
          training_frequency: frequency,
          available_equipment: equipment,
          medical_history: injuriesToMedicalHistory(injuries),
        });
      }

      const body = {
        user_profile: {
          user_id: userId,
          basic_info: { age, gender, height_cm: height, weight_kg: weight },
          fitness_level: fitnessLevel as "beginner" | "intermediate" | "advanced",
          fitness_goal: fitnessGoal,
          training_frequency: frequency,
          available_equipment: equipment,
          medical_history: injuriesToMedicalHistory(injuries),
        },
        workout_type: workoutType,
        feedback: showFeedback ? {
          user_id: userId,
          rpe,
          pain_feedback: hasPain
            ? { has_pain: true, pain_location: painLoc, pain_severity: painSev }
            : { has_pain: false },
          fatigue_feedback: { overall_fatigue: fatigue, sleep_quality_last_night: sleep },
        } : null,
      };
      const result = await plansApi.generate(body, { save_to_db: true, use_history: useHistory });
      setPlan(result);
      setElapsed((Date.now() - t0) / 1000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold mb-1" style={{ color: "var(--text)" }}>
          生成训练计划
        </h1>
        <p className="text-sm" style={{ color: "var(--text-muted)" }}>
          根据伤病史与训练反馈，智能生成安全、个性化的五阶段训练计划
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ── 左：输入 ── */}
        <div className="flex flex-col gap-5">
          <Section title="用户基本信息">
            <div className="grid grid-cols-2 gap-3">
              <Field label="用户 ID">
                <input value={userId} onChange={(e) => setUserId(e.target.value)}
                  className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
                  style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }} />
              </Field>
              <Field label="训练水平">
                <select value={fitnessLevel} onChange={(e) => setFitnessLevel(e.target.value)}
                  className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
                  style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }}>
                  {Object.entries(FITNESS_CN).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </select>
              </Field>
              <Field label="年龄">
                <input type="number" value={age} onChange={(e) => setAge(+e.target.value)}
                  className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
                  style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }} />
              </Field>
              <Field label="性别">
                <select value={gender} onChange={(e) => setGender(e.target.value)}
                  className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
                  style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }}>
                  <option value="male">男</option>
                  <option value="female">女</option>
                </select>
              </Field>
              <Field label="体重 (kg)">
                <input type="number" value={weight} onChange={(e) => setWeight(+e.target.value)}
                  className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
                  style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }} />
              </Field>
              <Field label="身高 (cm)">
                <input type="number" value={height} onChange={(e) => setHeight(+e.target.value)}
                  className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
                  style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }} />
              </Field>
            </div>
          </Section>

          <Section title="训练设定">
            <div className="grid grid-cols-2 gap-3">
              <Field label="主要目标">
                <select value={fitnessGoal} onChange={(e) => setFitnessGoal(e.target.value)}
                  className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
                  style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }}>
                  {Object.entries(GOAL_CN).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </select>
              </Field>
              <Field label="每周训练次数">
                <input type="number" min={2} max={6} value={frequency}
                  onChange={(e) => setFrequency(+e.target.value)}
                  className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
                  style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }} />
              </Field>
              <Field label="本次训练类型">
                <select value={workoutType} onChange={(e) => setWorkoutType(e.target.value)}
                  className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
                  style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }}>
                  {Object.entries(WORKOUT_TYPE_CN).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </select>
              </Field>
              <label className="text-xs flex items-center gap-2 pt-4" style={{ color: "var(--text-muted)" }}>
                <input type="checkbox" checked={useHistory}
                  onChange={(e) => setUseHistory(e.target.checked)} />
                参考训练历史
                <span className="text-[10px] opacity-70">（有历史记录时更精准）</span>
              </label>
            </div>
          </Section>

          <Section title="可用器材" caption="系统只会安排你拥有器材可完成的动作">
            <EquipmentSelector selected={equipment} onChange={setEquipment} />
          </Section>

          <Section title="伤病史" caption="系统将据此筛除高风险动作">
            <InjuryEditor injuries={injuries} onChange={setInjuries} />
          </Section>

          <div>
            <button onClick={() => setShowFeedback(!showFeedback)}
              className="flex items-center gap-2 text-sm mb-3"
              style={{ color: "var(--text-muted)" }}>
              {showFeedback ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              上次训练反馈（可选）
            </button>
            {showFeedback && (
              <div className="rounded-xl p-4 border flex flex-col gap-3"
                style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
                <label className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {formatRpe(rpe)}
                  <p className="text-[10px] mt-0.5 mb-1 opacity-80">{RPE_HINT}</p>
                  <input type="range" min={1} max={10} value={rpe}
                    onChange={(e) => setRpe(+e.target.value)} className="w-full" />
                </label>
                <label className="flex items-center gap-2 text-sm" style={{ color: "var(--text)" }}>
                  <input type="checkbox" checked={hasPain}
                    onChange={(e) => setHasPain(e.target.checked)} />
                  存在疼痛
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
                      onChange={(e) => setPainSev(+e.target.value)}
                      className="rounded-lg px-3 py-2 text-sm border outline-none"
                      style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }}
                      placeholder="疼痛强度" />
                  </div>
                )}
                <label className="text-xs" style={{ color: "var(--text-muted)" }}>
                  疲劳度：{fatigue}
                  <input type="range" min={1} max={10} value={fatigue}
                    onChange={(e) => setFatigue(+e.target.value)} className="w-full mt-1" />
                </label>
                <label className="text-xs" style={{ color: "var(--text-muted)" }}>
                  睡眠质量：{sleep}
                  <input type="range" min={1} max={10} value={sleep}
                    onChange={(e) => setSleep(+e.target.value)} className="w-full mt-1" />
                </label>
              </div>
            )}
          </div>

          <button onClick={handleGenerate} disabled={loading}
            className="flex items-center justify-center gap-2 py-3 rounded-xl font-medium text-sm disabled:opacity-50"
            style={{ background: "var(--accent)", color: "#fff" }}>
            {loading ? <Loader2 size={16} className="animate-spin" /> : <Rocket size={16} />}
            {loading ? "正在生成计划（大模型约需 30–90 秒）…" : "生成训练计划"}
          </button>
        </div>

        {/* ── 右：结果 ── */}
        <div>
          {loading && (
            <div className="flex flex-col items-center justify-center h-64 gap-3">
              <Loader2 size={32} className="animate-spin" style={{ color: "var(--accent)" }} />
              <p className="text-sm" style={{ color: "var(--text-muted)" }}>分析伤病风险并生成计划…</p>
            </div>
          )}
          {error && (
            <div className="rounded-xl p-4 text-sm border"
              style={{ background: "rgba(239,68,68,0.1)", borderColor: "rgba(239,68,68,0.3)", color: "var(--danger)" }}>
              {error}
            </div>
          )}
          {plan && !loading && (
            <>
              {plan.program_id && (
                <div className="rounded-xl p-4 text-sm border mb-4"
                  style={{ background: "rgba(34,197,94,0.08)", borderColor: "rgba(34,197,94,0.3)", color: "var(--text)" }}>
                  <p className="font-medium mb-1">已同步到档案与周期计划</p>
                  <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>
                    基本信息已写入「我的档案」，本次计划已纳入「训练计划」第 1 周对应训练日。
                  </p>
                  <div className="flex flex-wrap gap-3 text-xs">
                    <Link href="/workout" className="underline" style={{ color: "var(--accent-light)" }}>
                      开始今日训练
                    </Link>
                    <Link href="/programs" className="underline" style={{ color: "var(--accent-light)" }}>
                      查看训练计划
                    </Link>
                    <Link href="/profile" className="underline" style={{ color: "var(--accent-light)" }}>
                      查看我的档案
                    </Link>
                  </div>
                </div>
              )}
              <PlanResult plan={plan} elapsed={elapsed} />
            </>
          )}
          {!plan && !loading && !error && (
            <div className="rounded-xl p-8 text-center border"
              style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
              <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>
                {profile ? "已从「我的档案」预填信息，可直接生成" : "填写左侧信息，点击「生成训练计划」"}
              </p>
              <div className="text-left text-xs space-y-1 max-w-xs mx-auto" style={{ color: "var(--text-muted)" }}>
                <p>· 五阶段：热身 → 激活 → 主项 → 辅助 → 放松</p>
                <p>· 自动过滤伤病相关高风险动作</p>
                <p>· 生成后自动同步到周期计划与档案</p>
                <p>· 勾选「参考训练历史」可获得自适应建议</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function Section({ title, caption, children }: { title: string; caption?: string; children: React.ReactNode }) {
  return (
    <div>
      <h2 className="text-sm font-semibold mb-1" style={{ color: "var(--text)" }}>{title}</h2>
      {caption && <p className="text-xs mb-3" style={{ color: "var(--text-muted)" }}>{caption}</p>}
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="text-xs flex flex-col gap-1" style={{ color: "var(--text-muted)" }}>
      {label}
      {children}
    </label>
  );
}
