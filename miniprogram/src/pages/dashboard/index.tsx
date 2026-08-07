import { useCallback, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import {
  api,
  ensureLoggedIn,
  type TrainingProgram,
  type TrainingSession,
} from "../../services/api";
import { GOAL_CN, WORKOUT_TYPE_CN } from "../../utils/labels";
import "./index.scss";

export default function DashboardPage() {
  const [loading, setLoading] = useState(true);
  const [sessions, setSessions] = useState<TrainingSession[]>([]);
  const [programs, setPrograms] = useState<TrainingProgram[]>([]);
  const [readiness, setReadiness] = useState<{
    label: string;
    recommendation: string;
    score: number | null;
  } | null>(null);
  const [progressCount, setProgressCount] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const uid = await ensureLoggedIn();
      const [s, p] = await Promise.all([
        api.listSessions(uid).catch(() => [] as TrainingSession[]),
        api.listPrograms(uid).catch(() => [] as TrainingProgram[]),
      ]);
      setSessions(s);
      setPrograms(p);
      try {
        const r = await api.readiness(uid);
        setReadiness({
          label: r.label,
          recommendation: r.recommendation,
          score: r.score,
        });
      } catch {
        setReadiness(null);
      }
      try {
        const prog = await api.progression(uid);
        setProgressCount(prog.tracked_exercises || 0);
      } catch {
        setProgressCount(0);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useDidShow(() => {
    load();
  });

  const recent = sessions.slice(0, 10);
  const avgRpe = recent.length
    ? (recent.reduce((n, s) => n + s.rpe, 0) / recent.length).toFixed(1)
    : "—";
  const painCount = recent.filter((s) => s.pain_feedback?.has_pain).length;
  const active = programs.find((p) => p.status === "active");
  const tip =
    painCount > 0
      ? "近期有疼痛反馈，建议减量或咨询 AI 教练。"
      : Number(avgRpe) >= 8
        ? "平均强度偏高，注意安排恢复。"
        : sessions.length === 0
          ? "还没有训练记录，去今日训练打卡吧。"
          : "训练状态良好，保持节奏。";

  return (
    <View className="page">
      <View className="card hero-card">
        <Text className="hero-kicker">DASHBOARD</Text>
        <Text className="title">训练仪表盘</Text>
        <Text className="subtitle">训练数据、准备度与计划进度一览</Text>
      </View>

      {loading ? (
        <View className="card">
          <Text className="muted">加载中…</Text>
        </View>
      ) : (
        <>
          <View className="card">
            <Text className="section-title">关键指标</Text>
            <View className="stat-grid">
              <View className="stat-card">
                <Text className="stat-label">近期次数</Text>
                <Text className="stat-value">{recent.length}</Text>
              </View>
              <View className="stat-card">
                <Text className="stat-label">平均强度</Text>
                <Text className="stat-value">{avgRpe}</Text>
              </View>
              <View className="stat-card">
                <Text className="stat-label">疼痛次数</Text>
                <Text className="stat-value">{painCount}</Text>
              </View>
              <View className="stat-card">
                <Text className="stat-label">追踪动作</Text>
                <Text className="stat-value">{progressCount}</Text>
              </View>
            </View>
          </View>

          <View className="card">
            <Text className="section-title">AI 建议</Text>
            <Text className="subtitle">{tip}</Text>
            {readiness && (
              <>
                <View className="divider" />
                <Text className="tag ok">{readiness.label}</Text>
                <Text className="muted">{readiness.recommendation}</Text>
              </>
            )}
          </View>

          <View className="card">
            <Text className="section-title">当前计划</Text>
            {active ? (
              <>
                <Text className="subtitle">
                  {GOAL_CN[active.goal] || active.goal || active.name || "训练计划"}
                </Text>
                <Text className="muted">
                  第 {active.current_week}/{active.total_weeks} 周 · {active.status}
                </Text>
                <View
                  className="btn-ghost stack-gap"
                  onClick={() => Taro.switchTab({ url: "/pages/workout/index" })}
                >
                  <Text>去今日训练</Text>
                </View>
              </>
            ) : (
              <View className="empty">
                <Text className="empty-desc">暂无进行中的周期计划</Text>
                <View
                  className="btn-primary"
                  onClick={() => Taro.navigateTo({ url: "/pages/generate/index" })}
                >
                  <Text>去生成计划</Text>
                </View>
              </View>
            )}
          </View>

          <View className="card">
            <Text className="section-title">最近训练</Text>
            {recent.length === 0 ? (
              <Text className="muted">暂无记录</Text>
            ) : (
              recent.slice(0, 8).map((s) => (
                <View className="session-row" key={s.session_id}>
                  <View>
                    <Text className="session-date">{s.date}</Text>
                    <Text className="muted">
                      {WORKOUT_TYPE_CN[s.workout_type || ""] || s.workout_type || "训练"}
                      {s.duration_minutes ? ` · ${s.duration_minutes} 分钟` : ""}
                    </Text>
                  </View>
                  <Text className="tag">强度 {s.rpe}</Text>
                </View>
              ))
            )}
          </View>
        </>
      )}
    </View>
  );
}
