"use client";

import { useState, useEffect, useCallback } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import {
  TrendingUp, Flame, Target, Activity,
  AlertTriangle, CheckCircle, ChevronRight,
  Dumbbell, MessageCircle, PlayCircle, ClipboardList,
  Calendar, Loader2, Sparkles,
} from "lucide-react";
import { usersApi } from "@/lib/api";
import type { TrainingSession, TrainingProgram } from "@/lib/api";
import { rpeColor, formatDate } from "@/lib/utils";
import { formatRpe } from "@/lib/term-labels";
import { GOAL_CN } from "@/lib/constants";
import Link from "next/link";
import { useUser } from "@/contexts/UserContext";

export default function DashboardPage() {
  const { userId } = useUser();
  const [sessions, setSessions] = useState<TrainingSession[]>([]);
  const [programs, setPrograms] = useState<TrainingProgram[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, p] = await Promise.all([
        usersApi.sessions(userId).catch(() => [] as TrainingSession[]),
        usersApi.programs(userId).catch(() => [] as TrainingProgram[]),
      ]);
      setSessions(s.slice().reverse());
      setPrograms(p);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  const activeProgram = programs.find((p) => p.status === "active");
  const recent = sessions.slice(-10);
  const avgRpe = recent.length
    ? (recent.reduce((s, x) => s + x.rpe, 0) / recent.length).toFixed(1)
    : "—";
  const painCount = recent.filter((s) => s.pain_feedback?.has_pain).length;
  const completionAvg = recent.filter((s) => s.completion_rate != null).length
    ? (recent.filter((s) => s.completion_rate != null)
        .reduce((sum, s) => sum + (s.completion_rate ?? 0), 0) /
        recent.filter((s) => s.completion_rate != null).length * 100).toFixed(0)
    : null;

  const chartData = recent.map((s) => ({
    date: s.date.slice(5),
    rpe: s.rpe,
    completion: s.completion_rate != null ? Math.round(s.completion_rate * 100) : null,
  }));

  const aiTip = painCount > 0
    ? "近期有疼痛反馈，建议降低训练强度或咨询 AI 教练调整计划。"
    : Number(avgRpe) >= 8
      ? "平均强度偏高，注意安排恢复日，避免过度训练。"
      : sessions.length === 0
        ? "还没有训练记录，从「今日训练」开始你的第一次打卡吧。"
        : "训练状态良好，保持当前节奏，记得充分热身与拉伸。";

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
            Dashboard
          </p>
          <h1 className="text-2xl md:text-3xl font-bold mb-1.5" style={{ color: "var(--text)" }}>
            训练仪表盘
          </h1>
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            智能分析训练数据，优化你的训练效果
          </p>
        </div>
        <div
          className="inline-flex items-center gap-2 text-xs px-3 py-2 rounded-xl border shrink-0"
          style={{ background: "var(--surface)", borderColor: "var(--border)", color: "var(--text-muted)" }}
        >
          <span>用户</span>
          <span className="font-mono font-medium" style={{ color: "var(--accent)" }}>{userId}</span>
          <span>·</span>
          <span>最近 {recent.length} 次</span>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={<Flame size={18} />}
          label="平均自觉强度"
          value={avgRpe}
          accent="var(--warning)"
          tint="rgba(245, 158, 11, 0.12)"
        />
        <StatCard
          icon={<Activity size={18} />}
          label="训练次数"
          value={sessions.length}
          accent="var(--accent)"
          tint="rgba(108, 99, 255, 0.12)"
        />
        <StatCard
          icon={<Target size={18} />}
          label="平均完成率"
          value={completionAvg ? `${completionAvg}%` : "—"}
          accent="var(--success)"
          tint="rgba(16, 185, 129, 0.12)"
        />
        <StatCard
          icon={<AlertTriangle size={18} />}
          label="疼痛次数"
          value={painCount}
          accent={painCount > 0 ? "var(--danger)" : "var(--success)"}
          tint={painCount > 0 ? "rgba(239, 68, 68, 0.12)" : "rgba(16, 185, 129, 0.12)"}
        />
      </div>

      {/* Active program banner */}
      {activeProgram && (
        <div
          className="dashboard-card p-5 relative overflow-hidden"
        >
          <div
            className="absolute inset-0 opacity-[0.06] pointer-events-none"
            style={{ background: "linear-gradient(135deg, var(--accent) 0%, transparent 60%)" }}
          />
          <div className="relative flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-2 mb-2">
                <CheckCircle size={15} style={{ color: "var(--success)" }} />
                <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                  当前训练计划
                </span>
              </div>
              <p className="font-bold text-lg mb-2 truncate" style={{ color: "var(--text)" }}>
                {activeProgram.name}
              </p>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs" style={{ color: "var(--text-muted)" }}>
                <span>目标：{GOAL_CN[activeProgram.goal] ?? activeProgram.goal}</span>
                <span>第 {activeProgram.current_week}/{activeProgram.total_weeks} 周</span>
                <span>进行中</span>
              </div>
              <div className="mt-3 h-2 rounded-full overflow-hidden max-w-md" style={{ background: "var(--surface2)" }}>
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${(activeProgram.current_week / activeProgram.total_weeks) * 100}%`,
                    background: "linear-gradient(90deg, var(--accent), #8b83ff)",
                  }}
                />
              </div>
            </div>
            <Link
              href="/programs"
              className="inline-flex items-center gap-1 text-sm font-medium px-4 py-2 rounded-xl shrink-0 transition-opacity hover:opacity-90"
              style={{ background: "var(--accent)", color: "#fff" }}
            >
              查看详情 <ChevronRight size={16} />
            </Link>
          </div>
        </div>
      )}

      {/* Chart + sidebar */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* RPE Chart */}
        <div className="lg:col-span-2 dashboard-card p-5">
          <div className="flex items-center gap-2 mb-1">
            <TrendingUp size={18} style={{ color: "var(--accent)" }} />
            <h2 className="text-base font-semibold" style={{ color: "var(--text)" }}>
              自觉强度趋势
            </h2>
          </div>
          <p className="text-xs mb-5" style={{ color: "var(--text-muted)" }}>
            {chartData.length > 0
              ? `最近 ${chartData.length} 次训练的 RPE 变化`
              : "暂无足够数据绘制趋势图"}
          </p>
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: "var(--text-muted)" }} axisLine={false} tickLine={false} />
                <YAxis domain={[0, 10]} tick={{ fontSize: 11, fill: "var(--text-muted)" }} axisLine={false} tickLine={false} />
                <Tooltip
                  contentStyle={{
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: 10,
                    boxShadow: "var(--shadow-md)",
                  }}
                  labelStyle={{ color: "var(--text-muted)", fontSize: 11 }}
                  itemStyle={{ color: "var(--text)", fontSize: 12 }}
                />
                <Line
                  type="monotone"
                  dataKey="rpe"
                  stroke="var(--accent)"
                  strokeWidth={2.5}
                  dot={{ r: 4, fill: "var(--accent)", strokeWidth: 0 }}
                  activeDot={{ r: 6, fill: "var(--accent)" }}
                  name="自觉强度"
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div
              className="flex items-center justify-center h-48 rounded-xl text-sm"
              style={{ background: "var(--surface2)", color: "var(--text-muted)" }}
            >
              完成训练后将在此显示趋势
            </div>
          )}
        </div>

        {/* Quick actions */}
        <div className="dashboard-card p-5 flex flex-col">
          <h2 className="text-base font-semibold mb-1" style={{ color: "var(--text)" }}>快速操作</h2>
          <p className="text-xs mb-4" style={{ color: "var(--text-muted)" }}>常用功能快捷入口</p>
          <div className="space-y-2 flex-1">
            {[
              { href: "/workout", label: "今日训练", icon: PlayCircle, primary: true },
              { href: "/generate", label: "生成训练计划", icon: ClipboardList, primary: false },
              { href: "/chat", label: "问 AI 教练", icon: MessageCircle, primary: false },
              { href: "/programs", label: "周期计划", icon: Calendar, primary: false },
            ].map(({ href, label, icon: Icon, primary }) => (
              <Link
                key={href}
                href={href}
                className="flex items-center gap-2.5 w-full px-4 py-2.5 rounded-xl text-sm font-medium transition-all hover:opacity-90"
                style={
                  primary
                    ? { background: "var(--accent)", color: "#fff", boxShadow: "0 4px 14px -4px rgba(108,99,255,0.5)" }
                    : { background: "var(--surface2)", color: "var(--text)", border: "1px solid var(--border)" }
                }
              >
                <Icon size={16} />
                {label}
              </Link>
            ))}
          </div>
          <div
            className="mt-4 p-4 rounded-xl border"
            style={{ background: "rgba(108,99,255,0.06)", borderColor: "rgba(108,99,255,0.15)" }}
          >
            <div className="flex items-start gap-3">
              <div
                className="p-2 rounded-lg shrink-0"
                style={{ background: "rgba(108,99,255,0.12)" }}
              >
                <Sparkles size={14} style={{ color: "var(--accent)" }} />
              </div>
              <div>
                <h4 className="text-xs font-semibold mb-1" style={{ color: "var(--text)" }}>AI 建议</h4>
                <p className="text-xs leading-relaxed" style={{ color: "var(--text-muted)" }}>{aiTip}</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Recent sessions */}
      <div className="dashboard-card overflow-hidden">
        <div className="px-5 py-4 border-b flex items-center justify-between" style={{ borderColor: "var(--border)" }}>
          <div>
            <h2 className="text-base font-semibold" style={{ color: "var(--text)" }}>训练记录</h2>
            <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>最近完成的训练课程</p>
          </div>
          {sessions.length > 0 && (
            <Link href="/workout" className="text-xs font-medium hover:underline" style={{ color: "var(--accent)" }}>
              去训练
            </Link>
          )}
        </div>
        {sessions.length === 0 ? (
          <div className="text-center py-14 px-6">
            <div
              className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto mb-4"
              style={{ background: "rgba(108,99,255,0.1)" }}
            >
              <Dumbbell size={24} style={{ color: "var(--accent)" }} />
            </div>
            <p className="text-sm mb-4" style={{ color: "var(--text-muted)" }}>暂无训练记录</p>
            <Link
              href="/workout"
              className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-xl font-medium transition-opacity hover:opacity-90"
              style={{ background: "var(--accent)", color: "#fff" }}
            >
              <PlayCircle size={16} />
              记录第一次训练
            </Link>
          </div>
        ) : (
          <div className="p-4 space-y-2">
            {[...sessions].reverse().slice(0, 10).map((s) => (
              <SessionRow key={s.session_id} session={s} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({
  icon, label, value, accent, tint,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  accent: string;
  tint: string;
}) {
  return (
    <div className="dashboard-card p-4 transition-shadow hover:shadow-md">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>{label}</span>
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: tint, color: accent }}
        >
          {icon}
        </div>
      </div>
      <p className="text-2xl font-bold tracking-tight" style={{ color: "var(--text)" }}>{value}</p>
    </div>
  );
}

function SessionRow({ session: s }: { session: TrainingSession }) {
  return (
    <div
      className="flex items-center gap-4 px-4 py-3 rounded-xl border transition-shadow hover:shadow-sm"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
      <div
        className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
        style={{ background: "rgba(108,99,255,0.08)" }}
      >
        <Dumbbell size={16} style={{ color: "var(--accent)" }} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate" style={{ color: "var(--text)" }}>
          {s.workout_type ?? "训练"}
        </p>
        <p className="text-xs flex items-center gap-1 mt-0.5" style={{ color: "var(--text-muted)" }}>
          <Calendar size={11} />
          {formatDate(s.date)}
        </p>
      </div>
      <div className="text-right shrink-0">
        <p className="text-[10px] uppercase tracking-wide mb-0.5" style={{ color: "var(--text-muted)" }}>RPE</p>
        <p className={`text-lg font-bold ${rpeColor(s.rpe)}`}>{formatRpe(s.rpe)}</p>
      </div>
      {s.completion_rate != null && (
        <span
          className="text-xs px-2 py-1 rounded-md shrink-0 hidden sm:inline"
          style={{ background: "var(--surface2)", color: "var(--text-muted)" }}
        >
          {Math.round(s.completion_rate * 100)}%
        </span>
      )}
      {s.pain_feedback?.has_pain && (
        <AlertTriangle size={16} className="shrink-0" style={{ color: "var(--danger)" }} />
      )}
    </div>
  );
}
