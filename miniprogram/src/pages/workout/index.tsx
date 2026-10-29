import { useCallback, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import {
  api,
  ensureLoggedIn,
  getStoredUserId,
  saveActiveWorkout,
  type NextSessionResponse,
  type ProgramExercise,
} from "../../services/api";
import { exerciseNameCn, muscleCn } from "../../utils/exercise-labels";
import { WORKOUT_TYPE_CN } from "../../utils/labels";
import { pingBackend } from "../../utils/request";
import { API_BASE } from "../../utils/config";
import ExerciseGuideModal from "../../components/ExerciseGuideModal";
import VrEntry from "../../features/vr/VrEntry";
import "./index.scss";

const DEMO_EXERCISES: ProgramExercise[] = [
  {
    name: "Goblet Squat",
    sets: 3,
    reps: "10",
    rest_seconds: 60,
    target_muscle: "quads",
  },
  {
    name: "Push-Up",
    sets: 3,
    reps: "8-12",
    rest_seconds: 45,
    target_muscle: "chest",
  },
  {
    name: "Dumbbell Row",
    sets: 3,
    reps: "10",
    rest_seconds: 60,
    target_muscle: "back",
  },
];

export default function WorkoutPage() {
  const [userId, setUserId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [readiness, setReadiness] = useState<{
    label: string;
    recommendation: string;
    band: string;
  } | null>(null);
  const [next, setNext] = useState<NextSessionResponse | null>(null);
  const [guideName, setGuideName] = useState<string | null>(null);
  const [guideMuscle, setGuideMuscle] = useState<string | undefined>();
  const [netHint, setNetHint] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const ping = await pingBackend();
      if (!ping.ok) {
        setNetHint(ping.message);
        setError(ping.message);
        return;
      }
      setNetHint(`后端：${API_BASE}`);

      const uid = await ensureLoggedIn();
      setUserId(uid);

      try {
        const r = await api.readiness(uid);
        setReadiness({
          label: r.label,
          recommendation: r.recommendation,
          band: r.band,
        });
      } catch {
        setReadiness(null);
      }

      const programs = await api.listPrograms(uid);
      const active =
        programs.find((p) => p.status === "active") || programs[0];
      if (!active) {
        setNext(null);
        return;
      }
      const session = await api.nextSession(active.program_id);
      setNext(session);
    } catch (e: any) {
      setError(e?.message || "加载失败，请确认后端已启动");
    } finally {
      setLoading(false);
    }
  }, []);

  useDidShow(() => {
    load();
  });

  const exercises: ProgramExercise[] =
    next?.next_session?.key_exercises ?? [];

  const startWorkout = (
    list: ProgramExercise[],
    meta?: {
      programId?: string;
      programWeek?: number;
      workoutType?: string;
      label?: string;
    }
  ) => {
    if (!list.length) {
      Taro.showToast({ title: "没有可执行动作", icon: "none" });
      return;
    }
    const uid = userId || getStoredUserId();
    if (!uid) {
      Taro.showToast({ title: "请先到「我的」登录", icon: "none" });
      return;
    }
    saveActiveWorkout({
      userId: uid,
      programId: meta?.programId,
      programWeek: meta?.programWeek,
      workoutType: meta?.workoutType || "full_body",
      label: meta?.label || "今日训练",
      startedAt: Date.now(),
      exercises: list,
    });
    Taro.navigateTo({ url: "/pages/session/index" });
  };

  const bandTag =
    readiness?.band === "prime" || readiness?.band === "ready"
      ? "ok"
      : readiness?.band === "caution" || readiness?.band === "rest"
        ? "warn"
        : "neutral";

  return (
    <View className="page">
      <View className="card hero-card">
        <Text className="hero-kicker">TODAY · SESSION</Text>
        <Text className="title">今日训练</Text>
        <Text className="subtitle">
          {userId ? `已同步 · ${userId}` : "正在准备登录…"}
        </Text>
        {!!netHint && <Text className="meta-pill net-pill">{netHint}</Text>}
        <View className="hero-stats">
          <View className="hero-stat">
            <Text className="hero-stat-label">准备度</Text>
            <Text className="hero-stat-value">
              {readiness?.label || (loading ? "…" : "—")}
            </Text>
          </View>
          <View className="hero-stat">
            <Text className="hero-stat-label">课表</Text>
            <Text className="hero-stat-value">
              {next?.next_session
                ? `${exercises.length} 动作`
                : loading
                  ? "…"
                  : "待生成"}
            </Text>
          </View>
        </View>
      </View>

      {readiness && (
        <View className="card readiness-card">
          <View className="row-between">
            <Text className="section-title">今日建议</Text>
            <Text className={`tag ${bandTag}`}>{readiness.band}</Text>
          </View>
          <Text className="subtitle readiness-text">
            {readiness.recommendation}
          </Text>
        </View>
      )}

      {loading && (
        <View className="card">
          <View className="empty">
            <Text className="empty-icon">…</Text>
            <Text className="empty-desc">正在加载今日课表</Text>
          </View>
        </View>
      )}

      {!loading && !!error && (
        <View className="card">
          <View className="empty">
            <Text className="empty-icon">!</Text>
            <Text className="empty-title">暂时连不上服务</Text>
            <Text className="empty-desc">{error}</Text>
            <View className="btn-primary" onClick={load}>
              <Text>重新加载</Text>
            </View>
          </View>
        </View>
      )}

      {!loading && !error && !next?.next_session && (
        <View className="card">
          <View className="empty">
            <Text className="empty-icon">◆</Text>
            <Text className="empty-title">还没有今日课表</Text>
            <Text className="empty-desc">
              可以先体验演示训练；或在网页端生成周期计划后，回到这里刷新。
            </Text>
            <View
              className="btn-primary"
              onClick={() =>
                startWorkout(DEMO_EXERCISES, {
                  workoutType: "full_body",
                  label: "演示训练（全身）",
                })
              }
            >
              <Text>开始演示训练</Text>
            </View>
            <View
              className="btn-ghost stack-gap"
              onClick={() => Taro.switchTab({ url: "/pages/plans/index" })}
            >
              <Text>去看看计划</Text>
            </View>
          </View>
        </View>
      )}

      {!loading && !!next?.next_session && (
        <View className="card">
          <View className="row-between">
            <Text className="section-title">{next.next_session.label}</Text>
            <Text className="tag">
              第 {next.current_week}/{next.total_weeks} 周
            </Text>
          </View>
          <View className="session-summary">
            <Text className="tag">
              {WORKOUT_TYPE_CN[next.next_session.workout_type] ||
                next.next_session.workout_type}
            </Text>
            <Text className="tag neutral">
              约 {next.next_session.estimated_duration_minutes} 分钟
            </Text>
            <Text className="tag neutral">{exercises.length} 个动作</Text>
          </View>

          <View className="divider" />

          <Text className="muted tap-hint">点击动作可查看并播放教程</Text>

          {exercises.map((ex, idx) => (
            <View
              className="ex-row"
              key={`${ex.name}-${idx}`}
              onClick={() => {
                setGuideName(ex.name);
                setGuideMuscle(ex.target_muscle);
              }}
            >
              <View className="ex-accent" />
              <View className="ex-index">
                <Text>{String(idx + 1).padStart(2, "0")}</Text>
              </View>
              <View className="ex-body">
                <Text className="ex-name">{exerciseNameCn(ex.name)}</Text>
                <Text className="ex-meta">
                  {ex.sets} 组 × {ex.reps} · 休息 {ex.rest_seconds}s
                  {ex.target_muscle ? ` · ${muscleCn(ex.target_muscle)}` : ""}
                </Text>
              </View>
              <Text className="ex-guide-link">教程</Text>
            </View>
          ))}

          {next.next_session.notes && (
            <Text className="muted notes">{next.next_session.notes}</Text>
          )}

          <View
            className="btn-primary stack-gap"
            onClick={() =>
              startWorkout(exercises, {
                programId: next.program_id,
                programWeek: next.current_week,
                workoutType: next.next_session!.workout_type,
                label: next.next_session!.label,
              })
            }
          >
            <Text>开始训练</Text>
          </View>
        </View>
      )}

      <VrEntry />

      <ExerciseGuideModal
        exerciseName={guideName}
        targetMuscle={guideMuscle}
        onClose={() => {
          setGuideName(null);
          setGuideMuscle(undefined);
        }}
      />
    </View>
  );
}
