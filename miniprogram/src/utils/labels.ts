export const JOINT_CN: Record<string, string> = {
  knee: "膝关节",
  shoulder: "肩关节",
  spine: "脊柱",
  hip: "髋关节",
  ankle: "踝关节",
  elbow: "肘关节",
  wrist: "腕关节",
  neck: "颈椎",
};

export const INJURY_LOCATIONS = Object.keys(JOINT_CN);

export const SEVERITY_CN: Record<string, string> = {
  low: "轻度",
  medium: "中度",
  high: "重度",
};

export const FITNESS_CN: Record<string, string> = {
  beginner: "初级",
  intermediate: "中级",
  advanced: "高级",
};

export const WORKOUT_TYPE_CN: Record<string, string> = {
  full_body: "全身训练",
  upper_body: "上肢训练",
  lower_body: "下肢训练",
  push: "推日",
  pull: "拉日",
  recovery: "恢复训练",
};

export const GOAL_CN: Record<string, string> = {
  strength: "力量",
  hypertrophy: "增肌",
  general_fitness: "综合体能",
};

export const SPLIT_CN: Record<string, string> = {
  full_body: "全身",
  upper_lower: "上下肢分化",
  push_pull_legs: "推拉腿",
  auto: "智能分化",
};

export const EQUIPMENT_LIST = [
  "barbell",
  "dumbbell",
  "machine",
  "cable",
  "kettlebell",
  "resistance_band",
  "bench",
  "pull_up_bar",
  "squat_rack",
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

export const GENDER_CN: Record<string, string> = {
  male: "男",
  female: "女",
  other: "其他",
  unknown: "未设置",
};

export function chipClass(active: boolean) {
  return active ? "chip on" : "chip";
}
