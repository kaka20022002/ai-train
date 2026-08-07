"use client";

import { useEffect, useState } from "react";
import { User, ShieldAlert, Target, Loader2, Save, Dumbbell } from "lucide-react";
import { usersApi } from "@/lib/api";
import type { UserProfile } from "@/lib/api";
import { useUser } from "@/contexts/UserContext";
import {
  FITNESS_CN, GOAL_CN, GENDER_CN, JOINT_CN, SEVERITY_CN, EQUIPMENT_CN,
} from "@/lib/constants";
import { formatSafetyRevalidation } from "@/lib/safety-revalidation";
import { InjuryEditor, injuriesToMedicalHistory, medicalHistoryToInjuries, newInjury, type InjuryDraft } from "@/components/InjuryEditor";
import { EquipmentSelector } from "@/components/EquipmentSelector";

const SEVERITY_COLOR: Record<string, string> = {
  low: "var(--success)",
  medium: "var(--warning)",
  high: "var(--danger)",
};

function formatCondition(condition: string): string {
  return condition.replace(/_/g, " ");
}

export default function ProfilePage() {
  const { userId, setUserId, profile, profileLoading, refreshProfile } = useUser();
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [successDetail, setSuccessDetail] = useState<string | null>(null);

  const [age, setAge] = useState(28);
  const [gender, setGender] = useState("male");
  const [height, setHeight] = useState(175);
  const [weight, setWeight] = useState(78);
  const [fitnessLevel, setFitnessLevel] = useState("intermediate");
  const [fitnessGoal, setFitnessGoal] = useState("strength");
  const [frequency, setFrequency] = useState(3);
  const [equipment, setEquipment] = useState<string[]>([]);
  const [injuries, setInjuries] = useState<InjuryDraft[]>([newInjury()]);

  useEffect(() => {
    if (!profile) return;
    const bi = profile.basic_info;
    setAge(bi.age);
    setGender(bi.gender);
    setHeight(bi.height_cm ?? 175);
    setWeight(bi.weight_kg ?? 78);
    setFitnessLevel(profile.fitness_level);
    setFitnessGoal(profile.fitness_goal ?? "strength");
    setFrequency(profile.training_frequency ?? 3);
    setEquipment(profile.available_equipment ?? []);
    setInjuries(
      profile.medical_history.length > 0
        ? medicalHistoryToInjuries(profile.medical_history)
        : [newInjury()]
    );
  }, [profile]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const updated = await usersApi.update(userId, {
        basic_info: { age, gender, height_cm: height, weight_kg: weight },
        fitness_level: fitnessLevel,
        fitness_goal: fitnessGoal,
        training_frequency: frequency,
        available_equipment: equipment,
        medical_history: injuriesToMedicalHistory(injuries),
      });
      await refreshProfile();
      setEditing(false);
      setSuccess(true);
      setSuccessDetail(formatSafetyRevalidation(updated.safety_revalidation));
      setTimeout(() => { setSuccess(false); setSuccessDetail(null); }, 6000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  if (profileLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={20} className="animate-spin" style={{ color: "var(--accent)" }} />
      </div>
    );
  }

  if (!profile && !editing) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center p-8">
        <User size={40} style={{ color: "var(--text-muted)" }} className="mb-4" />
        <p className="text-sm mb-4" style={{ color: "var(--text)" }}>未找到用户档案</p>
        <p className="text-xs mb-4" style={{ color: "var(--text-muted)" }}>
          请先在「生成计划」填写信息并生成，系统将自动创建档案
        </p>
      </div>
    );
  }

  const bmi = weight && height ? (weight / ((height / 100) ** 2)).toFixed(1) : "—";
  const mh = profile?.medical_history ?? [];

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>我的档案</h1>
        {!editing ? (
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="text-xs px-3 py-1.5 rounded-lg border"
            style={{ borderColor: "var(--border)", color: "var(--accent-light)" }}
          >
            编辑
          </button>
        ) : (
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg disabled:opacity-50"
            style={{ background: "var(--accent)", color: "#fff" }}
          >
            {saving ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            保存
          </button>
        )}
      </div>

      {success && (
        <div className="text-xs mb-4 px-3 py-2 rounded-lg space-y-1" style={{ background: "rgba(34,197,94,0.1)", color: "var(--success)" }}>
          <p>档案已更新</p>
          {successDetail && <p>{successDetail}</p>}
        </div>
      )}
      {error && (
        <p className="text-xs mb-4 px-3 py-2 rounded-lg" style={{ background: "rgba(239,68,68,0.1)", color: "var(--danger)" }}>
          {error}
        </p>
      )}

      <Section icon={<User size={16} />} title="基本信息">
        {editing ? (
          <div className="grid grid-cols-2 gap-3">
            <Field label="用户 ID">
              <input value={userId} onChange={(e) => setUserId(e.target.value)}
                className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
                style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }} />
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
            <Field label="身高 (cm)">
              <input type="number" value={height} onChange={(e) => setHeight(+e.target.value)}
                className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
                style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }} />
            </Field>
            <Field label="体重 (kg)">
              <input type="number" value={weight} onChange={(e) => setWeight(+e.target.value)}
                className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
                style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }} />
            </Field>
            <InfoItem label="BMI" value={bmi} />
          </div>
        ) : (
          <Grid>
            <InfoItem label="用户 ID" value={userId} mono />
            <InfoItem label="年龄" value={`${profile!.basic_info.age} 岁`} />
            <InfoItem label="性别" value={GENDER_CN[profile!.basic_info.gender] ?? profile!.basic_info.gender} />
            <InfoItem label="身高" value={profile!.basic_info.height_cm ? `${profile!.basic_info.height_cm} cm` : "—"} />
            <InfoItem label="体重" value={profile!.basic_info.weight_kg ? `${profile!.basic_info.weight_kg} kg` : "—"} />
            <InfoItem label="BMI" value={profile!.basic_info.bmi?.toFixed(1) ?? bmi} />
          </Grid>
        )}
      </Section>

      <Section icon={<Target size={16} />} title="训练目标">
        {editing ? (
          <div className="grid grid-cols-2 gap-3">
            <Field label="健身水平">
              <select value={fitnessLevel} onChange={(e) => setFitnessLevel(e.target.value)}
                className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
                style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }}>
                {Object.entries(FITNESS_CN).map(([k, v]) => (
                  <option key={k} value={k}>{v}</option>
                ))}
              </select>
            </Field>
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
              <input type="number" min={2} max={6} value={frequency} onChange={(e) => setFrequency(+e.target.value)}
                className="w-full rounded-lg px-3 py-2 text-sm border outline-none"
                style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }} />
            </Field>
          </div>
        ) : (
          <Grid>
            <InfoItem label="健身水平" value={FITNESS_CN[profile!.fitness_level] ?? profile!.fitness_level} />
            <InfoItem label="主要目标" value={GOAL_CN[profile!.fitness_goal ?? ""] ?? profile!.fitness_goal ?? "未设定"} />
            <InfoItem label="训练频率" value={profile!.training_frequency ? `${profile!.training_frequency} 次/周` : "—"} />
          </Grid>
        )}
      </Section>

      <Section icon={<Dumbbell size={16} />} title="可用器材">
        {editing ? (
          <EquipmentSelector selected={equipment} onChange={setEquipment} />
        ) : (profile?.available_equipment?.length ?? 0) === 0 ? (
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            未设置（默认全器材可用）
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {profile!.available_equipment!.map((e) => (
              <span
                key={e}
                className="text-xs px-2.5 py-1 rounded-full"
                style={{ background: "var(--surface2)", color: "var(--text)" }}
              >
                {EQUIPMENT_CN[e] ?? e}
              </span>
            ))}
          </div>
        )}
      </Section>

      <Section icon={<ShieldAlert size={16} />} title={`伤病记录（${editing ? injuries.filter((i) => i.location).length : mh.length} 项）`}>
        {editing ? (
          <InjuryEditor injuries={injuries} onChange={setInjuries} />
        ) : mh.length === 0 ? (
          <p className="text-sm" style={{ color: "var(--success)" }}>无伤病记录 ✓</p>
        ) : (
          <div className="flex flex-col gap-3">
            {mh.map((item, i) => (
              <div
                key={i}
                className="rounded-xl px-4 py-3 border"
                style={{ background: "var(--surface2)", borderColor: "var(--border)" }}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-semibold text-sm" style={{ color: "var(--text)" }}>
                    {JOINT_CN[item.location] ?? item.location} — {formatCondition(item.condition)}
                  </span>
                  <span
                    className="text-xs px-2 py-0.5 rounded-full font-medium"
                    style={{
                      background: `${SEVERITY_COLOR[item.severity]}22`,
                      color: SEVERITY_COLOR[item.severity],
                    }}
                  >
                    {SEVERITY_CN[item.severity] ?? item.severity}
                  </span>
                </div>
                {item.pain_trigger && (
                  <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                    触发动作：{item.pain_trigger}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
      </Section>

      {editing && (
        <button
          type="button"
          onClick={() => setEditing(false)}
          className="w-full mt-2 py-2 text-sm rounded-xl border"
          style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
        >
          取消编辑
        </button>
      )}
    </div>
  );
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border p-5 mb-4" style={{ background: "var(--surface)", borderColor: "var(--border)" }}>
      <div className="flex items-center gap-2 mb-4" style={{ color: "var(--accent-light)" }}>
        {icon}
        <h2 className="text-sm font-semibold" style={{ color: "var(--text)" }}>{title}</h2>
      </div>
      {children}
    </div>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 md:grid-cols-3 gap-3">{children}</div>;
}

function InfoItem({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <p className="text-xs mb-0.5" style={{ color: "var(--text-muted)" }}>{label}</p>
      <p className={`text-sm font-medium ${mono ? "font-mono" : ""}`} style={{ color: "var(--text)" }}>{value}</p>
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
