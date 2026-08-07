import type { SafetyRevalidation } from "@/lib/api";

/** Format backend safety revalidation report for UI toasts. */
export function formatSafetyRevalidation(r?: SafetyRevalidation | null): string {
  if (!r) {
    return "伤病史已同步到档案，后续生成计划将自动屏蔽禁止动作。";
  }
  if (r.exercises_replaced === 0) {
    return `伤病史已同步。已检查 ${r.programs_scanned} 个周期计划、${r.plans_scanned} 份训练计划，无需替换动作。`;
  }
  return (
    `伤病史已同步，已替换 ${r.exercises_replaced} 个禁止动作` +
    `（${r.programs_updated} 个周期计划、${r.plans_updated} 份训练计划已更新）。`
  );
}
