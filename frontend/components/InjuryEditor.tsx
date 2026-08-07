"use client";

import { Plus, Trash2 } from "lucide-react";
import {
  INJURY_LOCATIONS, JOINT_CN, SEVERITY_CN, CONDITION_HINTS,
} from "@/lib/constants";
import type { MedicalHistoryItem } from "@/lib/api";

export type InjuryDraft = MedicalHistoryItem & { id: string };

export function newInjury(): InjuryDraft {
  return {
    id: Math.random().toString(36).slice(2, 9),
    location: "knee",
    condition: "",
    severity: "medium",
  };
}

interface Props {
  injuries: InjuryDraft[];
  onChange: (injuries: InjuryDraft[]) => void;
}

export function InjuryEditor({ injuries, onChange }: Props) {
  const update = (id: string, patch: Partial<InjuryDraft>) => {
    onChange(injuries.map((i) => (i.id === id ? { ...i, ...patch } : i)));
  };

  const remove = (id: string) => onChange(injuries.filter((i) => i.id !== id));

  return (
    <div className="flex flex-col gap-3">
      {injuries.map((inj, idx) => (
        <div
          key={inj.id}
          className="rounded-xl p-4 border"
          style={{ background: "var(--surface2)", borderColor: "var(--border)" }}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-sm font-semibold" style={{ color: "var(--text)" }}>
              伤病 #{idx + 1}
              <span className="ml-2 font-normal text-xs" style={{ color: "var(--text-muted)" }}>
                {JOINT_CN[inj.location]} · {SEVERITY_CN[inj.severity]}
              </span>
            </span>
            <button onClick={() => remove(inj.id)} className="p-1 rounded hover:opacity-70">
              <Trash2 size={14} style={{ color: "var(--danger)" }} />
            </button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <label className="text-xs flex flex-col gap-1" style={{ color: "var(--text-muted)" }}>
              部位
              <select
                value={inj.location}
                onChange={(e) => update(inj.id, { location: e.target.value })}
                className="rounded-lg px-3 py-2 text-sm border"
                style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}
              >
                {INJURY_LOCATIONS.map((loc) => (
                  <option key={loc} value={loc}>{JOINT_CN[loc]}</option>
                ))}
              </select>
            </label>
            <label className="text-xs flex flex-col gap-1" style={{ color: "var(--text-muted)" }}>
              严重程度
              <select
                value={inj.severity}
                onChange={(e) => update(inj.id, { severity: e.target.value as InjuryDraft["severity"] })}
                className="rounded-lg px-3 py-2 text-sm border"
                style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}
              >
                {(["low", "medium", "high"] as const).map((s) => (
                  <option key={s} value={s}>{SEVERITY_CN[s]}</option>
                ))}
              </select>
            </label>
          </div>
          <label className="text-xs flex flex-col gap-1 mt-3" style={{ color: "var(--text-muted)" }}>
            诊断名称
            <input
              value={inj.condition}
              onChange={(e) => update(inj.id, { condition: e.target.value })}
              placeholder={CONDITION_HINTS[inj.location] ?? "如 meniscus_tear"}
              className="rounded-lg px-3 py-2 text-sm border"
              style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text)" }}
            />
          </label>
        </div>
      ))}
      <button
        onClick={() => onChange([...injuries, newInjury()])}
        className="flex items-center justify-center gap-2 py-2.5 rounded-xl border text-sm transition-colors hover:opacity-80"
        style={{ borderColor: "var(--border)", color: "var(--text-muted)" }}
      >
        <Plus size={14} /> 添加伤病
      </button>
    </div>
  );
}

export function injuriesToMedicalHistory(injuries: InjuryDraft[]): MedicalHistoryItem[] {
  return injuries
    .filter((inj) => inj.condition)
    .map(({ id: _id, location, severity, condition, ...rest }) => ({
      location,
      severity,
      condition: condition || `${location}_injury`,
      ...rest,
    }));
}

export function medicalHistoryToInjuries(mh: MedicalHistoryItem[]): InjuryDraft[] {
  return mh.map((item) => ({
    ...item,
    id: Math.random().toString(36).slice(2, 9),
  }));
}
