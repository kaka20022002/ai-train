export const DEMO_USER_ID = "usr_001";

export const INJURY_LOCATIONS = [
  "knee", "shoulder", "spine", "hip", "ankle", "elbow", "wrist", "neck",
] as const;

export const JOINT_CN: Record<string, string> = {
  knee: "膝关节", shoulder: "肩关节", spine: "脊柱", hip: "髋关节",
  ankle: "踝关节", elbow: "肘关节", wrist: "腕关节", neck: "颈椎",
};

export const SEVERITY_CN: Record<string, string> = {
  low: "轻度", medium: "中度", high: "重度",
};

export const FITNESS_CN: Record<string, string> = {
  beginner: "初级", intermediate: "中级", advanced: "高级",
};

export const WORKOUT_TYPE_CN: Record<string, string> = {
  full_body: "全身训练", upper_body: "上肢训练", lower_body: "下肢训练",
  push: "推日", pull: "拉日", recovery: "恢复训练",
};

export const WEEK_TYPE_CN: Record<string, string> = {
  base: "适应期", progression: "进阶期", peak: "峰值期", deload: "减量恢复",
};

export const GENDER_CN: Record<string, string> = {
  male: "男", female: "女", other: "其他",
};

export const GOAL_CN: Record<string, string> = {
  strength: "力量", hypertrophy: "增肌", general_fitness: "综合体能",
};

export const SPLIT_CN: Record<string, string> = {
  full_body: "全身", upper_lower: "上下肢分化", push_pull_legs: "推拉腿", auto: "智能分化",
};

export const PHASE_META: Record<string, { cn: string; color: string }> = {
  warm_up:    { cn: "🔥 热身", color: "#f59e0b" },
  activation: { cn: "⚡ 激活", color: "#06b6d4" },
  main_lifts: { cn: "💪 主项", color: "#6c63ff" },
  accessories:{ cn: "🎯 辅助", color: "#22c55e" },
  cool_down:  { cn: "🧘 放松", color: "#a78bfa" },
};

export const TYPE_CN: Record<string, string> = {
  Compound: "复合动作", Isolation: "孤立动作", Isometric: "等长动作",
};

// ── 器材感知（Sprint 3）──────────────────────────────────────────────────────
// 可选器材清单（与后端 exercise_db.json required_equipment 标签一致）。
// 「自重」永远隐式可用，因此不在可勾选列表中。
export const EQUIPMENT_LIST = [
  "barbell", "dumbbell", "machine", "cable", "kettlebell",
  "resistance_band", "bench", "pull_up_bar", "squat_rack",
] as const;

export const EQUIPMENT_CN: Record<string, string> = {
  bodyweight: "自重",
  barbell: "杠铃",
  dumbbell: "哑铃",
  machine: "固定器械",
  cable: "龙门/绳索",
  kettlebell: "壶铃",
  resistance_band: "弹力带",
  bench: "卧推凳",
  pull_up_bar: "单杠/引体架",
  squat_rack: "深蹲架",
};

/** 常见训练场景的器材预设，便于一键填充。 */
export const EQUIPMENT_PRESETS: { id: string; label: string; equipment: string[] }[] = [
  { id: "bodyweight", label: "纯自重", equipment: ["bodyweight"] },
  { id: "home_dumbbell", label: "家庭哑铃", equipment: ["dumbbell", "bench", "resistance_band"] },
  { id: "home_full", label: "家庭全套", equipment: ["barbell", "dumbbell", "bench", "squat_rack", "pull_up_bar", "resistance_band"] },
  { id: "commercial_gym", label: "商业健身房", equipment: [...EQUIPMENT_LIST] },
];

export const CONDITION_HINTS: Record<string, string> = {
  knee: "半月板损伤 / 前交叉韧带损伤 / 髌腱炎",
  shoulder: "肩袖撕裂 / 肩峰撞击",
  spine: "腰椎间盘突出 / 椎间盘突出",
  hip: "髋盂唇撕裂 / 髋关节撞击",
  ankle: "踝关节扭伤 / 跟腱炎",
  elbow: "网球肘 / 高尔夫肘",
  wrist: "腕管综合征 / 腕关节扭伤",
  neck: "颈椎间盘突出",
};

/** 自觉强度（原 RPE）说明文案 */
export { RPE_HINT, formatRpe, translateIntensityNote, translateCoachText } from "./term-labels";
