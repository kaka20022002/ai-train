/**
 * 训练术语中文化工具函数
 * 将英文/数字 RPE 等术语转换为对用户友好的中文描述
 */

/** 自觉强度（RPE）简短说明，用于滑块旁提示 */
export const RPE_HINT =
  "1=极轻松  4=轻松  6=有点累  7=还能再做3次  9=几乎尽力  10=完全力竭";

/** 将 RPE 数值格式化为中文标签 */
export function formatRpe(rpe: number): string {
  const map: Record<number, string> = {
    1: "1 — 极度轻松",
    2: "2 — 非常轻松",
    3: "3 — 轻松",
    4: "4 — 略有感觉",
    5: "5 — 适中",
    6: "6 — 有些疲劳",
    7: "7 — 较难（还能再做 3 次）",
    8: "8 — 很难（还能再做 1-2 次）",
    9: "9 — 极难（几乎到极限）",
    10: "10 — 完全力竭",
  };
  return map[rpe] ?? `自觉强度 ${rpe}`;
}

/** 将英文强度备注翻译为中文 */
export function translateIntensityNote(note?: string | null): string {
  if (!note) return "";
  return note
    .replace(/RPE\s*(\d+)/gi, "自觉强度 $1")
    .replace(/\b(sets?)\b/gi, "组")
    .replace(/\b(reps?)\b/gi, "次")
    .replace(/\b(rest)\b/gi, "休息")
    .replace(/\b(moderate)\b/gi, "中等强度")
    .replace(/\b(heavy)\b/gi, "大重量")
    .replace(/\b(light)\b/gi, "轻重量")
    .replace(/\b(warm.?up)\b/gi, "热身")
    .replace(/\b(cool.?down)\b/gi, "放松")
    .replace(/\b(failure)\b/gi, "力竭");
}

/** 翻译 AI 教练回复中的常见英文词汇 */
export function translateCoachText(text: string): string {
  return text
    .replace(/\bRPE\b/g, "自觉强度")
    .replace(/\b1RM\b/g, "最大重量")
    .replace(/\bdeload\b/gi, "减量")
    .replace(/\bmesocycle\b/gi, "中周期")
    .replace(/\bmacrocycle\b/gi, "大周期")
    .replace(/\bconcentric\b/gi, "向心")
    .replace(/\beccentric\b/gi, "离心");
}
