import { View, Text } from "@tarojs/components";
import type { ChatPlan, ChatPlanExercise, ChatSafety, ChatAgentTrace } from "../services/api";
import "./PlanCard.scss";

const PHASE_LABEL: Array<{ key: string; label: string }> = [
  { key: "warm_up", label: "热身" },
  { key: "activation", label: "激活" },
  { key: "main_lifts", label: "主项" },
  { key: "accessories", label: "辅助" },
  { key: "cool_down", label: "放松" },
];

const WORKOUT_LABEL: Record<string, string> = {
  lower_body: "下肢",
  upper_body: "上肢",
  full_body: "全身",
  core: "核心",
};

const LEVEL_LABEL: Record<string, string> = {
  low: "低",
  moderate: "中",
  medium: "中",
  high: "高",
};

const CLEARANCE_LABEL: Record<string, string> = {
  cleared: "正常训练",
  conditional: "有条件训练",
  restricted: "受限训练",
  blocked: "暂不建议训练",
};

function doseOf(ex: ChatPlanExercise): string {
  const parts: string[] = [];
  if (ex.sets) parts.push(`${ex.sets} 组`);
  if (ex.reps) parts.push(String(ex.reps));
  return parts.join(" × ");
}

interface Props {
  plan: ChatPlan;
  safety?: ChatSafety | null;
  trace?: ChatAgentTrace | null;
}

export default function PlanCard({ plan, safety, trace }: Props) {
  const totalSets = Object.values(plan.phases || {}).reduce(
    (sum, list) => sum + (list || []).reduce((s, ex) => s + (Number(ex.sets) || 0), 0),
    0
  );
  const passed = safety?.passed !== false;
  const level = safety?.risk_level ? LEVEL_LABEL[safety.risk_level] || safety.risk_level : "";
  const clearance = safety?.clearance
    ? CLEARANCE_LABEL[safety.clearance] || safety.clearance
    : "";

  return (
    <View className="pc">
      <View className="pc-head">
        <View className="pc-head-left">
          <Text className="pc-kicker">PLAN</Text>
          <Text className="pc-title">
            {WORKOUT_LABEL[plan.workout_type] || plan.workout_type}训练
          </Text>
        </View>
        <Text className="pc-duration">{plan.estimated_duration_minutes} 分钟</Text>
      </View>

      <View className="pc-meta">
        <Text className={`pc-tag ${passed ? "ok" : "warn"}`}>
          {passed ? "审查通过" : "审查未通过"}
        </Text>
        {level ? <Text className="pc-tag soft">风险 {level}</Text> : null}
        {clearance ? <Text className="pc-tag soft">{clearance}</Text> : null}
        {totalSets ? <Text className="pc-tag soft">{totalSets} 组</Text> : null}
      </View>

      {PHASE_LABEL.map(({ key, label }) => {
        const list = plan.phases?.[key] || [];
        if (!list.length) return null;
        return (
          <View className="pc-phase" key={key}>
            <View className="pc-phase-head">
              <View className="pc-bar" />
              <Text className="pc-phase-name">{label}</Text>
              <Text className="pc-phase-count">{list.length}</Text>
            </View>
            {list.map((ex, idx) => (
              <View className="pc-item" key={`${key}-${idx}`}>
                <View className="pc-item-row">
                  <Text className="pc-item-name">{ex.name_zh || ex.name}</Text>
                  <View className="pc-dose-wrap">
                    <Text className="pc-dose">{doseOf(ex)}</Text>
                    {ex.load_pct ? (
                      <Text className="pc-load">{ex.load_pct}%</Text>
                    ) : null}
                  </View>
                </View>
                {ex.notes ? <Text className="pc-item-note">{ex.notes}</Text> : null}
              </View>
            ))}
          </View>
        );
      })}

      {(plan.safety_notes || []).length ? (
        <View className="pc-notes">
          {(plan.safety_notes || []).slice(0, 4).map((n, i) => (
            <Text className="pc-note" key={i}>
              · {n}
            </Text>
          ))}
        </View>
      ) : null}

      {trace ? (
        <Text className="pc-trace">
          {trace.agents.join(" → ")}
          {trace.review_rounds ? ` · 重写 ${trace.review_rounds} 轮` : ""}
          {trace.elapsed_ms ? ` · ${(trace.elapsed_ms / 1000).toFixed(0)} 秒` : ""}
        </Text>
      ) : null}
    </View>
  );
}
