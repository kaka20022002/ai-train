"use client";

import { useEffect, useState } from "react";
import {
  Loader2, Search, BookOpen, Filter, ChevronDown, ChevronUp,
  Layers, AlertTriangle,
} from "lucide-react";
import { exercisesApi } from "@/lib/api";
import type { ExerciseRecord } from "@/lib/api";
import { JOINT_CN, TYPE_CN } from "@/lib/constants";
import { muscleCn, translateExerciseText, exerciseNameCn } from "@/lib/exercise-labels";
import { ExerciseName } from "@/components/ExerciseName";
import { ExerciseGuide, ExerciseGuideThumb } from "@/components/ExerciseGuide";
import { getExerciseGuides } from "@/lib/exercise-guide-cache";

const TYPE_BADGE: Record<string, { bg: string; color: string }> = {
  Compound: { bg: "rgba(108,99,255,0.12)", color: "var(--accent)" },
  Isolation: { bg: "rgba(16,185,129,0.12)", color: "var(--success)" },
  Isometric: { bg: "rgba(245,158,11,0.12)", color: "var(--warning)" },
};

export default function ExercisesPage() {
  const [all, setAll] = useState<ExerciseRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterType, setFilterType] = useState("全部");
  const [maxRisk, setMaxRisk] = useState(5);
  const [filterJoint, setFilterJoint] = useState("全部");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([exercisesApi.list(), getExerciseGuides()])
      .then(([r]) => setAll(r.exercises))
      .catch(() => setAll([]))
      .finally(() => setLoading(false));
  }, []);

  const filtered = all.filter((ex) => {
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      const cn = exerciseNameCn(ex.name).toLowerCase();
      if (!ex.name.toLowerCase().includes(q) && !cn.includes(q)) return false;
    }
    if (filterType !== "全部" && ex.type !== filterType) return false;
    if (ex.risk_level > maxRisk) return false;
    if (filterJoint !== "全部" && !ex.involved_joints.includes(filterJoint)) return false;
    return true;
  });

  const guideCount = all.filter((ex) => ex.has_guide !== false).length;
  const hasActiveFilters = filterType !== "全部" || maxRisk < 5 || filterJoint !== "全部" || search.trim() !== "";

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[50vh]">
        <Loader2 size={28} className="animate-spin" style={{ color: "var(--accent)" }} />
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--accent)" }}>
            Exercise Library
          </p>
          <h1 className="text-2xl md:text-3xl font-bold mb-1.5" style={{ color: "var(--text)" }}>
            动作知识库
          </h1>
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            浏览动作要领、风险等级与替代方案，支持中英文搜索
          </p>
        </div>
        <div className="flex flex-wrap gap-2 shrink-0">
          <StatPill icon={<Layers size={13} />} label="收录动作" value={all.length} />
          <StatPill icon={<BookOpen size={13} />} label="动图教程" value={guideCount} accent />
        </div>
      </div>

      {/* Filters */}
      <div className="dashboard-card p-4 md:p-5">
        <div className="flex items-center gap-2 mb-4">
          <Filter size={15} style={{ color: "var(--accent)" }} />
          <span className="text-sm font-semibold" style={{ color: "var(--text)" }}>筛选条件</span>
          {hasActiveFilters && (
            <button
              type="button"
              onClick={() => {
                setFilterType("全部");
                setMaxRisk(5);
                setFilterJoint("全部");
                setSearch("");
              }}
              className="ml-auto text-xs px-2.5 py-1 rounded-lg transition-opacity hover:opacity-80"
              style={{ background: "var(--surface2)", color: "var(--text-muted)" }}
            >
              重置筛选
            </button>
          )}
        </div>

        <div className="relative mb-4">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
            style={{ color: "var(--text-muted)" }}
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索动作，如：深蹲、卧推、腿举…"
            className="w-full rounded-xl pl-9 pr-4 py-2.5 text-sm border outline-none focus:border-[rgba(108,99,255,0.4)] transition-colors"
            style={{
              background: "var(--surface2)",
              borderColor: "var(--border)",
              color: "var(--text)",
            }}
          />
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <FilterField label="动作类型">
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              className="w-full rounded-xl px-3 py-2.5 text-sm border outline-none"
              style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }}
            >
              <option value="全部">全部</option>
              {["Compound", "Isolation", "Isometric"].map((t) => (
                <option key={t} value={t}>{TYPE_CN[t] ?? t}</option>
              ))}
            </select>
          </FilterField>

          <FilterField label={`最大风险等级 · ${maxRisk}/5`}>
            <input
              type="range"
              min={1}
              max={5}
              value={maxRisk}
              onChange={(e) => setMaxRisk(+e.target.value)}
              className="w-full mt-2 accent-[#6c63ff]"
            />
            <div className="flex justify-between text-[10px] mt-1" style={{ color: "var(--text-muted)" }}>
              <span>低风险</span>
              <span>高风险</span>
            </div>
          </FilterField>

          <FilterField label="涉及关节">
            <select
              value={filterJoint}
              onChange={(e) => setFilterJoint(e.target.value)}
              className="w-full rounded-xl px-3 py-2.5 text-sm border outline-none"
              style={{ background: "var(--surface2)", borderColor: "var(--border)", color: "var(--text)" }}
            >
              <option value="全部">全部</option>
              {Object.entries(JOINT_CN).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </FilterField>
        </div>
      </div>

      {/* Selected exercise guide */}
      {selected && (
        <div className="dashboard-card p-5 relative overflow-hidden">
          <div
            className="absolute inset-0 opacity-[0.05] pointer-events-none"
            style={{ background: "linear-gradient(135deg, var(--accent) 0%, transparent 55%)" }}
          />
          <div className="relative">
            <p className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: "var(--text-muted)" }}>
              动作教程
            </p>
            <p className="text-lg font-bold mb-3" style={{ color: "var(--text)" }}>
              <ExerciseName name={selected} />
            </p>
            <ExerciseGuide name={selected} defaultOpen featured />
          </div>
        </div>
      )}

      {/* Table */}
      <div className="dashboard-card overflow-hidden">
        <div
          className="px-5 py-4 border-b flex items-center justify-between"
          style={{ borderColor: "var(--border)" }}
        >
          <div>
            <h2 className="text-base font-semibold" style={{ color: "var(--text)" }}>动作列表</h2>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
              显示 {filtered.length} / {all.length} 个 · 点击行查看教程
            </p>
          </div>
        </div>

        {filtered.length === 0 ? (
          <div className="text-center py-16 px-6">
            <div
              className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-4"
              style={{ background: "rgba(108,99,255,0.1)" }}
            >
              <Search size={22} style={{ color: "var(--accent)" }} />
            </div>
            <p className="text-sm font-medium mb-1" style={{ color: "var(--text)" }}>没有符合筛选条件的动作</p>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>试试放宽筛选或更换搜索词</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs min-w-[720px]">
              <thead>
                <tr style={{ background: "var(--surface2)" }}>
                  {["演示", "动作名称", "类型", "目标肌群", "涉及关节", "风险", "替代"].map((h) => (
                    <th
                      key={h}
                      className="text-left px-4 py-3 font-semibold uppercase tracking-wide text-[10px]"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((ex) => {
                  const isSelected = selected === ex.name;
                  const badge = TYPE_BADGE[ex.type] ?? { bg: "var(--surface2)", color: "var(--text-muted)" };
                  return (
                    <tr
                      key={ex.id}
                      onClick={() => setSelected((s) => (s === ex.name ? null : ex.name))}
                      className="border-t cursor-pointer transition-colors"
                      style={{
                        borderColor: "var(--border)",
                        background: isSelected ? "rgba(108,99,255,0.06)" : undefined,
                      }}
                    >
                      <td className="px-4 py-3">
                        <ExerciseGuideThumb name={ex.name} size={64} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-sm" style={{ color: "var(--text)" }}>
                            <ExerciseName name={ex.name} />
                          </span>
                          {isSelected ? (
                            <ChevronUp size={14} style={{ color: "var(--accent)" }} />
                          ) : (
                            <ChevronDown size={14} style={{ color: "var(--text-muted)" }} />
                          )}
                        </div>
                        <span className="text-[10px] mt-0.5 block" style={{ color: "var(--text-muted)" }}>
                          #{ex.id}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className="inline-block px-2 py-0.5 rounded-md text-[10px] font-medium"
                          style={{ background: badge.bg, color: badge.color }}
                        >
                          {TYPE_CN[ex.type] ?? ex.type}
                        </span>
                      </td>
                      <td className="px-4 py-3" style={{ color: "var(--text-muted)" }}>
                        {muscleCn(ex.target_muscle)}
                      </td>
                      <td className="px-4 py-3 max-w-[120px]" style={{ color: "var(--text-muted)" }}>
                        {ex.involved_joints.map((j) => JOINT_CN[j] ?? j).join("、")}
                      </td>
                      <td className="px-4 py-3">
                        <RiskBar level={ex.risk_level} />
                      </td>
                      <td className="px-4 py-3 max-w-[140px] truncate" style={{ color: "var(--text-muted)" }}>
                        {translateExerciseText(ex.substitution ?? "") || "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Tip */}
      <div
        className="flex items-start gap-3 p-4 rounded-xl border text-xs"
        style={{ background: "rgba(108,99,255,0.05)", borderColor: "rgba(108,99,255,0.12)", color: "var(--text-muted)" }}
      >
        <AlertTriangle size={14} className="shrink-0 mt-0.5" style={{ color: "var(--accent)" }} />
        <span>
          风险等级仅供参考，请结合自身伤病史与教练建议选择动作。带
          <span className="font-medium" style={{ color: "var(--accent)" }}> 动图教程 </span>
          的动作可查看标准要领。
        </span>
      </div>
    </div>
  );
}

function StatPill({
  icon, label, value, accent = false,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  accent?: boolean;
}) {
  return (
    <div
      className="inline-flex items-center gap-2 px-3 py-2 rounded-xl border text-xs"
      style={{
        background: accent ? "rgba(108,99,255,0.08)" : "var(--surface)",
        borderColor: accent ? "rgba(108,99,255,0.2)" : "var(--border)",
      }}
    >
      <span style={{ color: accent ? "var(--accent)" : "var(--text-muted)" }}>{icon}</span>
      <span style={{ color: "var(--text-muted)" }}>{label}</span>
      <span className="font-bold" style={{ color: accent ? "var(--accent)" : "var(--text)" }}>{value}</span>
    </div>
  );
}

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-xs font-medium" style={{ color: "var(--text-muted)" }}>
      {label}
      {children}
    </label>
  );
}

function RiskBar({ level }: { level: number }) {
  const colors = ["", "#4ade80", "#a3e635", "#facc15", "#fb923c", "#f87171"];
  const color = colors[level] ?? "#f87171";
  return (
    <div className="flex items-center gap-2">
      <div
        className="w-20 h-2 rounded-full overflow-hidden"
        style={{ background: "var(--surface2)" }}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${(level / 5) * 100}%`, background: color }}
        />
      </div>
      <span className="font-semibold tabular-nums" style={{ color }}>{level}/5</span>
    </div>
  );
}
