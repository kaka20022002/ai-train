import { useEffect, useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import {
  api,
  ensureLoggedIn,
  type GeneratePlanResponse,
  type PlanExercise,
  type UserProfile,
} from "../../services/api";
import {
  EQUIPMENT_CN,
  EQUIPMENT_LIST,
  FITNESS_CN,
  GOAL_CN,
  SPLIT_CN,
  WORKOUT_TYPE_CN,
} from "../../utils/labels";
import "./index.scss";

type Mode = "single" | "program";

const PHASE_CN: Record<string, string> = {
  warm_up: "热身",
  activation: "激活",
  main_lifts: "主项",
  accessories: "辅助",
  cool_down: "放松",
};

export default function GeneratePage() {
  const [mode, setMode] = useState<Mode>("single");
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [workoutType, setWorkoutType] = useState("full_body");
  const [goal, setGoal] = useState("strength");
  const [level, setLevel] = useState("intermediate");
  const [weeks, setWeeks] = useState(4);
  const [freq, setFreq] = useState(3);
  const [split, setSplit] = useState("auto");
  const [equipment, setEquipment] = useState<string[]>([]);
  const [useHistory, setUseHistory] = useState(true);
  const [loading, setLoading] = useState(false);
  const [plan, setPlan] = useState<GeneratePlanResponse | null>(null);
  const [programMsg, setProgramMsg] = useState("");

  const loadProfile = async () => {
    const uid = await ensureLoggedIn();
    try {
      const p = await api.getUser(uid);
      setProfile(p);
      if (p.fitness_level) setLevel(p.fitness_level);
      if (p.fitness_goal) setGoal(p.fitness_goal);
      if (p.training_frequency) setFreq(p.training_frequency);
      if (p.available_equipment?.length) setEquipment(p.available_equipment);
    } catch {
      setProfile(null);
    }
  };

  useDidShow(() => {
    loadProfile();
  });

  useEffect(() => {
    setPlan(null);
    setProgramMsg("");
  }, [mode]);

  const buildProfilePayload = (uid: string) => ({
    user_id: uid,
    basic_info: profile?.basic_info || { age: 28, gender: "male" },
    fitness_level: level,
    fitness_goal: goal,
    training_frequency: freq,
    available_equipment: equipment,
    medical_history: profile?.medical_history || [],
  });

  const ensureUser = async (uid: string) => {
    try {
      await api.getUser(uid);
      await api.updateUser(uid, {
        fitness_level: level,
        fitness_goal: goal,
        training_frequency: freq,
        available_equipment: equipment,
      });
    } catch {
      await api.createUser({
        user_id: uid,
        basic_info: profile?.basic_info || { age: 28, gender: "male" },
        fitness_level: level,
        fitness_goal: goal,
        training_frequency: freq,
        available_equipment: equipment,
        medical_history: profile?.medical_history || [],
      });
    }
  };

  const toggleEquipment = (key: string) => {
    setEquipment((prev) =>
      prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]
    );
  };

  const onGenerate = async () => {
    setLoading(true);
    setPlan(null);
    setProgramMsg("");
    try {
      const uid = await ensureLoggedIn();
      await ensureUser(uid);
      const user_profile = buildProfilePayload(uid);

      if (mode === "single") {
        const res = await api.generatePlan(
          { user_profile, workout_type: workoutType, feedback: null },
          { save_to_db: true, use_history: useHistory }
        );
        setPlan(res);
        Taro.showToast({ title: "单次计划已生成", icon: "success" });
      } else {
        const res = await api.generateProgram({
          user_profile,
          goal,
          total_weeks: weeks,
          sessions_per_week: freq,
          split_type: split,
          use_history: useHistory,
        });
        setProgramMsg(
          `已创建周期计划 ${res.program_id}（${weeks} 周 × 每周 ${freq} 练）`
        );
        Taro.showToast({ title: "周期计划已生成", icon: "success" });
      }
    } catch (e: any) {
      Taro.showToast({ title: e?.message?.slice(0, 40) || "生成失败", icon: "none" });
    } finally {
      setLoading(false);
    }
  };

  const renderPhase = (key: string, list: PlanExercise[]) => {
    if (!list?.length) return null;
    return (
      <View className="phase-block" key={key}>
        <Text className="phase-title">{PHASE_CN[key] || key}</Text>
        {list.map((ex, i) => (
          <Text className="phase-line" key={`${ex.name}-${i}`}>
            {ex.name} · {ex.sets}×{ex.reps} · 休息{ex.rest_seconds}s
          </Text>
        ))}
      </View>
    );
  };

  return (
    <View className="page">
      <View className="card hero-card">
        <Text className="hero-kicker">GENERATE</Text>
        <Text className="title">生成计划</Text>
        <Text className="subtitle">基于伤病与器材约束，生成安全训练安排</Text>
      </View>

      <View className="card">
        <View className="chip-row">
          <View className={mode === "single" ? "chip on" : "chip"} onClick={() => setMode("single")}>
            <Text>单次训练</Text>
          </View>
          <View className={mode === "program" ? "chip on" : "chip"} onClick={() => setMode("program")}>
            <Text>周期计划</Text>
          </View>
        </View>
      </View>

      <View className="card">
        <Text className="section-title">训练目标</Text>
        <Text className="field-label">健身水平</Text>
        <View className="chip-row">
          {Object.entries(FITNESS_CN).map(([k, v]) => (
            <View key={k} className={level === k ? "chip on" : "chip"} onClick={() => setLevel(k)}>
              <Text>{v}</Text>
            </View>
          ))}
        </View>

        <Text className="field-label">目标</Text>
        <View className="chip-row">
          {Object.entries(GOAL_CN).map(([k, v]) => (
            <View key={k} className={goal === k ? "chip on" : "chip"} onClick={() => setGoal(k)}>
              <Text>{v}</Text>
            </View>
          ))}
        </View>

        {mode === "single" ? (
          <>
            <Text className="field-label">训练类型</Text>
            <View className="chip-row">
              {Object.entries(WORKOUT_TYPE_CN).map(([k, v]) => (
                <View
                  key={k}
                  className={workoutType === k ? "chip on" : "chip"}
                  onClick={() => setWorkoutType(k)}
                >
                  <Text>{v}</Text>
                </View>
              ))}
            </View>
          </>
        ) : (
          <>
            <Text className="field-label">周数：{weeks}</Text>
            <View className="chip-row">
              {[4, 6, 8, 12].map((n) => (
                <View key={n} className={weeks === n ? "chip on" : "chip"} onClick={() => setWeeks(n)}>
                  <Text>{n} 周</Text>
                </View>
              ))}
            </View>
            <Text className="field-label">每周次数：{freq}</Text>
            <View className="chip-row">
              {[2, 3, 4, 5].map((n) => (
                <View key={n} className={freq === n ? "chip on" : "chip"} onClick={() => setFreq(n)}>
                  <Text>{n} 次</Text>
                </View>
              ))}
            </View>
            <Text className="field-label">分化方式</Text>
            <View className="chip-row">
              {Object.entries(SPLIT_CN).map(([k, v]) => (
                <View key={k} className={split === k ? "chip on" : "chip"} onClick={() => setSplit(k)}>
                  <Text>{v}</Text>
                </View>
              ))}
            </View>
          </>
        )}

        <Text className="field-label">可用器材（可多选，空=不限制）</Text>
        <View className="chip-row">
          {EQUIPMENT_LIST.map((k) => (
            <View
              key={k}
              className={equipment.includes(k) ? "chip on" : "chip"}
              onClick={() => toggleEquipment(k)}
            >
              <Text>{EQUIPMENT_CN[k]}</Text>
            </View>
          ))}
        </View>

        <View className="chip-row" style={{ marginTop: "24rpx" }}>
          <View
            className={useHistory ? "chip on" : "chip"}
            onClick={() => setUseHistory((v) => !v)}
          >
            <Text>{useHistory ? "✓ 参考历史" : "不参考历史"}</Text>
          </View>
        </View>

        <View className="btn-primary stack-gap" onClick={onGenerate}>
          <Text>{loading ? "生成中…" : mode === "single" ? "生成单次计划" : "生成周期计划"}</Text>
        </View>
      </View>

      {programMsg && (
        <View className="card">
          <Text className="subtitle">{programMsg}</Text>
          <View
            className="btn-ghost"
            onClick={() => Taro.switchTab({ url: "/pages/plans/index" })}
          >
            <Text>查看周期计划</Text>
          </View>
        </View>
      )}

      {plan && (
        <View className="card">
          <Text className="section-title">
            {WORKOUT_TYPE_CN[plan.workout_type] || plan.workout_type}
          </Text>
          <Text className="muted">
            {plan.plan_id} · 约 {plan.estimated_duration_minutes} 分钟
          </Text>
          {plan.safety_notes?.slice(0, 3).map((n, i) => (
            <Text className="muted" key={i}>
              · {n}
            </Text>
          ))}
          <View className="divider" />
          {Object.entries(plan.phases || {}).map(([k, list]) =>
            renderPhase(k, list as PlanExercise[])
          )}
        </View>
      )}
    </View>
  );
}
