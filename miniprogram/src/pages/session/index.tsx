import { useEffect, useMemo, useRef, useState } from "react";
import { View, Text, Input } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import {
  api,
  clearActiveWorkout,
  loadActiveWorkout,
  parseDefaultReps,
  saveActiveWorkout,
  type ActiveWorkout,
  type ExercisePerformance,
  type ProgramExercise,
} from "../../services/api";
import { exerciseNameCn, muscleCn } from "../../utils/exercise-labels";
import ExerciseGuideModal from "../../components/ExerciseGuideModal";
import "./index.scss";

interface SetLog {
  weight: number;
  reps: number;
}

interface ExState {
  name: string;
  plannedSets: number;
  plannedReps: string;
  restSeconds: number;
  targetMuscle?: string;
  originalName?: string;
  sets: SetLog[];
  weightDraft: string;
  repsDraft: string;
}

function toExState(ex: ProgramExercise): ExState {
  return {
    name: ex.name,
    plannedSets: Math.max(1, ex.sets || 3),
    plannedReps: ex.reps || "10",
    restSeconds: Math.max(15, ex.rest_seconds || 60),
    targetMuscle: ex.target_muscle,
    sets: [],
    weightDraft: "",
    repsDraft: String(parseDefaultReps(ex.reps)),
  };
}

export default function SessionPage() {
  const [workout, setWorkout] = useState<ActiveWorkout | null>(null);
  const [exList, setExList] = useState<ExState[]>([]);
  const [exIndex, setExIndex] = useState(0);
  const [restLeft, setRestLeft] = useState(0);
  const [finishing, setFinishing] = useState(false);
  const [rpe, setRpe] = useState(7);
  const [hasPain, setHasPain] = useState(false);
  const [painLocation, setPainLocation] = useState("");
  const [subMap, setSubMap] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const clearTimer = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  };

  const startRest = (seconds: number) => {
    clearTimer();
    setRestLeft(seconds);
    timerRef.current = setInterval(() => {
      setRestLeft((prev) => {
        if (prev <= 1) {
          clearTimer();
          Taro.vibrateShort({ type: "medium" }).catch(() => undefined);
          Taro.showToast({ title: "休息结束，下一组", icon: "none" });
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  };

  useDidShow(() => {
    const w = loadActiveWorkout();
    if (!w || !w.exercises?.length) {
      Taro.showToast({ title: "没有进行中的训练", icon: "none" });
      setTimeout(() => Taro.navigateBack({ fail: () => Taro.switchTab({ url: "/pages/workout/index" }) }), 500);
      return;
    }
    setWorkout(w);
    setExList(w.exercises.map(toExState));
    setExIndex(0);
    setFinishing(false);
  });

  useEffect(() => {
    api
      .listExercises()
      .then((list) => {
        const map: Record<string, string> = {};
        list.forEach((e) => {
          if (e.substitution) {
            map[e.name.toLowerCase()] = e.substitution;
            // substitution 字段可能是 "A or B"，取第一个
          }
        });
        setSubMap(map);
      })
      .catch(() => undefined);
    return () => clearTimer();
  }, []);

  const current = exList[exIndex];
  const progressText = useMemo(() => {
    if (!exList.length) return "";
    const doneSets = exList.reduce((n, e) => n + e.sets.length, 0);
    const totalSets = exList.reduce((n, e) => n + e.plannedSets, 0);
    return `动作 ${exIndex + 1}/${exList.length} · 组 ${doneSets}/${totalSets}`;
  }, [exList, exIndex]);

  const updateCurrent = (patch: Partial<ExState>) => {
    setExList((prev) =>
      prev.map((e, i) => (i === exIndex ? { ...e, ...patch } : e))
    );
  };

  const completeSet = () => {
    if (!current || restLeft > 0) return;
    const weight = Number(current.weightDraft);
    const reps = Number(current.repsDraft);
    if (!reps || reps <= 0) {
      Taro.showToast({ title: "请填写次数", icon: "none" });
      return;
    }
    const nextSets = [
      ...current.sets,
      { weight: Number.isFinite(weight) ? weight : 0, reps },
    ];
    updateCurrent({ sets: nextSets });

    const finishedExercise = nextSets.length >= current.plannedSets;
    if (finishedExercise) {
      if (exIndex >= exList.length - 1) {
        Taro.showToast({ title: "全部动作完成", icon: "success" });
        setFinishing(true);
      } else {
        Taro.showToast({ title: "本动作完成，进入下一个", icon: "none" });
        setExIndex((i) => i + 1);
        startRest(current.restSeconds);
      }
    } else {
      startRest(current.restSeconds);
    }
  };

  const skipRest = () => {
    clearTimer();
    setRestLeft(0);
  };

  const findSubstitution = (name: string): string | null => {
    const raw = subMap[name.toLowerCase()];
    if (!raw) return null;
    // "Goblet Squat or Leg Press" → 取第一个
    const first = raw.split(/\s+or\s+|\/|、|,|，/i)[0]?.trim();
    return first || raw;
  };

  const replaceExercise = () => {
    if (!current) return;
    const alt = findSubstitution(current.originalName || current.name);
    if (!alt) {
      Taro.showModal({
        title: "暂无推荐替代",
        content: "动作库中没有该动作的替代建议。可手动在下方修改动作名称，或跳过该动作。",
        showCancel: false,
      });
      return;
    }
    Taro.showModal({
      title: "替换动作",
      content: `将「${exerciseNameCn(current.name)}」替换为「${exerciseNameCn(alt)}」？已完成的组会保留在原动作记录中。`,
      success: (res) => {
        if (!res.confirm) return;
        const replaced: ExState = {
          ...current,
          name: alt,
          originalName: current.originalName || current.name,
          sets: [],
          repsDraft: String(parseDefaultReps(current.plannedReps)),
        };
        setExList((prev) => prev.map((e, i) => (i === exIndex ? replaced : e)));
        // 同步到 storage，返回今日训练页时仍一致
        if (workout) {
          const exercises = workout.exercises.map((e, i) =>
            i === exIndex ? { ...e, name: alt } : e
          );
          const next = { ...workout, exercises };
          saveActiveWorkout(next);
          setWorkout(next);
        }
        Taro.showToast({ title: "已替换", icon: "success" });
      },
    });
  };

  const skipExercise = () => {
    if (exIndex >= exList.length - 1) {
      setFinishing(true);
    } else {
      setExIndex((i) => i + 1);
    }
  };

  const buildPerformance = (): ExercisePerformance[] =>
    exList
      .filter((e) => e.sets.length > 0)
      .map((e) => ({
        name: e.name,
        weight_kg: e.sets[e.sets.length - 1]?.weight || undefined,
        sets_completed: e.sets.length,
        reps_per_set: e.sets.map((s) => s.reps),
        notes: e.originalName ? `由 ${e.originalName} 替换` : undefined,
      }));

  const submitSession = async () => {
    if (!workout || submitting) return;
    setSubmitting(true);
    try {
      const duration = Math.max(
        1,
        Math.round((Date.now() - workout.startedAt) / 60000)
      );
      const performance = buildPerformance();
      const planned = exList.reduce((n, e) => n + e.plannedSets, 0);
      const done = performance.reduce((n, e) => n + (e.sets_completed || 0), 0);
      const today = new Date();
      const date = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

      await api.logSession(workout.userId, {
        program_id: workout.programId,
        program_week: workout.programWeek,
        date,
        workout_type: workout.workoutType,
        duration_minutes: duration,
        rpe,
        completion_rate: planned ? Math.min(1, done / planned) : 1,
        pain_feedback: {
          has_pain: hasPain,
          pain_location: hasPain ? painLocation || undefined : undefined,
          pain_severity: hasPain ? 5 : undefined,
        },
        exercise_performance: performance,
        notes: "小程序训练打卡",
      });

      clearActiveWorkout();
      Taro.showToast({ title: "已同步打卡", icon: "success" });
      setTimeout(() => {
        Taro.switchTab({ url: "/pages/workout/index" });
      }, 600);
    } catch (e: any) {
      Taro.showToast({
        title: e?.message?.slice(0, 40) || "打卡失败",
        icon: "none",
      });
    } finally {
      setSubmitting(false);
    }
  };

  const abandon = () => {
    Taro.showModal({
      title: "结束并退出？",
      content: "未打卡的数据不会上传。可先点「完成训练」提交。",
      success: (res) => {
        if (!res.confirm) return;
        clearTimer();
        clearActiveWorkout();
        Taro.switchTab({ url: "/pages/workout/index" });
      },
    });
  };

  if (!workout || !current) {
    return (
      <View className="page">
        <View className="card">
          <Text className="muted">加载训练中…</Text>
        </View>
      </View>
    );
  }

  if (finishing) {
    return (
      <View className="page">
        <View className="card hero-card">
          <Text className="hero-kicker">DONE</Text>
          <Text className="title">完成训练</Text>
          <Text className="subtitle">提交后会写入训练记录，并影响下次准备度与计划。</Text>
        </View>

        <View className="card">
          <Text className="label">整体自觉强度（1-10）：{rpe}</Text>
          <View className="rpe-row">
            {[5, 6, 7, 8, 9, 10].map((n) => (
              <View
                key={n}
                className={`rpe-chip ${rpe === n ? "on" : ""}`}
                onClick={() => setRpe(n)}
              >
                <Text>{n}</Text>
              </View>
            ))}
          </View>
          <Text className="hint">7=还能再做3次；9=只剩1次力气</Text>
        </View>

        <View className="card">
          <Text className="label">训练中是否疼痛？</Text>
          <View className="rpe-row">
            <View
              className={`rpe-chip ${!hasPain ? "on" : ""}`}
              onClick={() => setHasPain(false)}
            >
              <Text>无</Text>
            </View>
            <View
              className={`rpe-chip ${hasPain ? "on" : ""}`}
              onClick={() => setHasPain(true)}
            >
              <Text>有</Text>
            </View>
          </View>
          {hasPain && (
            <Input
              className="input"
              placeholder="疼痛部位，如膝盖 / 肩"
              value={painLocation}
              onInput={(e) => setPainLocation(e.detail.value)}
            />
          )}
        </View>

        <View className="card">
          <Text className="label">本组记录摘要</Text>
          {buildPerformance().length === 0 ? (
            <Text className="muted">还没有完成任何组</Text>
          ) : (
            buildPerformance().map((p) => (
              <Text className="summary-line" key={p.name}>
                {exerciseNameCn(p.name)}：{p.sets_completed} 组
                {p.weight_kg ? ` · ${p.weight_kg}kg` : ""}
                {p.reps_per_set?.length
                  ? ` · ${p.reps_per_set.join("/")}`
                  : ""}
              </Text>
            ))
          )}
        </View>

        <View className="btn-primary" onClick={submitSession}>
          <Text>{submitting ? "提交中…" : "提交打卡"}</Text>
        </View>
        <View className="btn-ghost" style={{ marginTop: "16px" }} onClick={() => setFinishing(false)}>
          <Text>返回继续训练</Text>
        </View>
      </View>
    );
  }

  return (
    <View className="page session-page">
      <View className="card hero-card">
        <Text className="hero-kicker">IN WORKOUT</Text>
        <Text className="title">{workout.label}</Text>
        <Text className="subtitle">{progressText}</Text>
      </View>

      {restLeft > 0 && (
        <View className="card rest-card">
          <Text className="rest-num">{restLeft}</Text>
          <Text className="rest-label">秒休息中</Text>
          <View className="btn-ghost" onClick={skipRest}>
            <Text>跳过休息</Text>
          </View>
        </View>
      )}

      <View className="card">
        <View className="ex-title-row" onClick={() => setGuideOpen(true)}>
          <View className="ex-title-main">
            <Text className="ex-title">{exerciseNameCn(current.name)}</Text>
            {exerciseNameCn(current.name) !== current.name && (
              <Text className="muted">{current.name}</Text>
            )}
          </View>
          <Text className="ex-guide-btn">播放教程</Text>
        </View>
        {current.originalName && (
          <Text className="muted">
            原动作：{exerciseNameCn(current.originalName)}
          </Text>
        )}
        <Text className="ex-plan">
          计划 {current.plannedSets} 组 × {current.plannedReps}
          {current.targetMuscle ? ` · ${muscleCn(current.targetMuscle)}` : ""}
        </Text>
        <Text className="ex-plan">
          已完成 {current.sets.length}/{current.plannedSets} 组 · 组间休息{" "}
          {current.restSeconds}s
        </Text>

        {current.sets.map((s, i) => (
          <Text className="set-done" key={`${i}-${s.reps}`}>
            第 {i + 1} 组：{s.weight > 0 ? `${s.weight} kg × ` : ""}
            {s.reps} 次
          </Text>
        ))}

        {current.sets.length < current.plannedSets && restLeft === 0 && (
          <View className="inputs">
            <View className="field">
              <Text className="field-label">重量 kg</Text>
              <Input
                className="input"
                type="digit"
                placeholder="可选"
                value={current.weightDraft}
                onInput={(e) => updateCurrent({ weightDraft: e.detail.value })}
              />
            </View>
            <View className="field">
              <Text className="field-label">次数</Text>
              <Input
                className="input"
                type="number"
                value={current.repsDraft}
                onInput={(e) => updateCurrent({ repsDraft: e.detail.value })}
              />
            </View>
          </View>
        )}
      </View>

      {restLeft === 0 && current.sets.length < current.plannedSets && (
        <View className="btn-primary" onClick={completeSet}>
          <Text>完成本组</Text>
        </View>
      )}

      <View className="actions">
        <View className="btn-ghost half" onClick={replaceExercise}>
          <Text>替换动作</Text>
        </View>
        <View className="btn-ghost half" onClick={skipExercise}>
          <Text>跳过动作</Text>
        </View>
      </View>

      <View className="btn-primary finish" onClick={() => setFinishing(true)}>
        <Text>完成训练 / 打卡</Text>
      </View>
      <View className="btn-ghost" style={{ marginTop: "12px" }} onClick={abandon}>
        <Text>放弃并退出</Text>
      </View>

      <ExerciseGuideModal
        exerciseName={guideOpen ? current.name : null}
        targetMuscle={current.targetMuscle}
        onClose={() => setGuideOpen(false)}
      />
    </View>
  );
}
