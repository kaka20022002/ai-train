# -*- coding: utf-8 -*-
"""把三 Agent 管线的结构化产物渲染成对外的计划 JSON。

设计上这是一层**单向适配器**：Agent 之间只传 ``{exercise_id, sets, reps,
load_pct, impact}``，动作名称、休息时长、目标肌群这些「给人看」的字段
全部在这里补全。这样渲染逻辑集中一处，Agent 内部保持纯结构化。

产物结构与 ``PlanGeneratorMock.export_plan_as_json`` 完全对齐，
因此可以直接复用现有的响应模型、落库逻辑与前端类型。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agents.contracts import PHASES, PlanDraft, RiskProfile, SafetyReport

RENDERER_VERSION = "agents_render/1.0.0"

# 阶段 → (是否为主项, 备注)
PHASE_LABELS: Dict[str, str] = {
    "warm_up": "热身",
    "activation": "激活",
    "main_lifts": "主项训练",
    "accessories": "辅助训练",
    "cool_down": "放松",
}


def _rest_seconds(phase: str, fitness_level: str) -> int:
    """休息时长沿用旧生成器的口径，避免前端表现突变。"""
    if phase == "main_lifts":
        return 90 if fitness_level != "beginner" else 120
    return 60


def _estimate_duration(phases: Dict[str, List[Dict[str, Any]]], rest_of: Dict[int, int]) -> int:
    """粗略估算总时长：每组 45 秒动作 + 组间休息，按分钟向上取整。"""
    total = 0
    for slots in phases.values():
        for slot in slots:
            rest = rest_of.get(id(slot), 60)
            total += int(slot["sets"]) * (45 + rest)
    return max(1, round(total / 60))


def render_plan_draft(
    draft: PlanDraft,
    exercise_index: Dict[int, Dict[str, Any]],
    profile: RiskProfile,
    report: SafetyReport,
    *,
    fitness_level: str = "beginner",
    workout_type: str = "full_body",
) -> Dict[str, Any]:
    """渲染为与旧生成器一致的导出结构。"""
    phases: Dict[str, List[Dict[str, Any]]] = {p: [] for p in PHASES}
    rest_of: Dict[int, int] = {}

    for phase in PHASES:
        for slot in draft.phases.get(phase, []):
            meta = exercise_index.get(slot.exercise_id, {})
            item = {
                "name": meta.get("name", f"Exercise #{slot.exercise_id}"),
                "sets": slot.sets,
                "reps": slot.reps,
                "rest_seconds": _rest_seconds(phase, fitness_level),
                "notes": _slot_note(phase, slot, meta),
                "target_muscle": meta.get("target_muscle") or "Multiple",
            }
            phases[phase].append(item)
            rest_of[id(item)] = item["rest_seconds"]

    return {
        "plan_id": draft.plan_id,
        "user_id": draft.user_id,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "workout_type": draft.workout_type or workout_type,
        "estimated_duration_minutes": _estimate_duration(phases, rest_of),
        "phases": phases,
        "safety_notes": build_safety_notes(profile, report, draft),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator_version": f"{draft.generator}+{draft.grammar_version}",
    }


def _slot_note(phase: str, slot: Any, meta: Dict[str, Any]) -> Optional[str]:
    """给单条动作补一句上下文，只在确有信息时输出。"""
    parts: List[str] = []
    if slot.load_pct is not None:
        parts.append(f"强度 {slot.load_pct}%")
    if phase in ("warm_up", "cool_down") and meta.get("type") == "Isometric":
        parts.append("等长保持，按时间计而非次数")
    if slot.impact >= 4:
        parts.append("高冲击动作，注意动作质量优先于负荷")
    return "；".join(parts) if parts else None


def build_safety_notes(
    profile: RiskProfile,
    report: SafetyReport,
    draft: Optional[PlanDraft] = None,
) -> List[str]:
    """安全说明：结论先行，再给可核查的数字。"""
    notes: List[str] = []

    if report.passed:
        notes.append(
            f"✅ 计划已通过安全校验：{report.checked_slots} 个动作全部合规"
            f"（约束文法 {profile.profile_hash}）"
        )
    else:
        codes = sorted({v.code for v in report.violations})
        notes.append(f"⚠️ 安全校验未通过：{'、'.join(codes)}")

    if report.masked_count:
        notes.append(f"🚫 候选池已屏蔽 {report.masked_count} 个禁忌动作，生成阶段无法选中")

    if report.adversarial_probes:
        notes.append(
            f"🛡️ 对抗探针：主动注入 {report.adversarial_probes} 个禁忌动作，"
            f"拦截 {report.adversarial_blocked}/{report.adversarial_probes}"
        )

    if profile.joint_caps:
        caps = "、".join(f"{k}≤{v}" for k, v in sorted(profile.joint_caps.items()))
        notes.append(f"📐 关节冲击上限：{caps}")

    if profile.load_pct_cap is not None:
        notes.append(f"📉 训练强度上限：{profile.load_pct_cap}%（由历史反馈动态收紧）")

    if draft is not None and draft.rejected_ids:
        notes.append(f"🔍 生成阶段另有 {len(draft.rejected_ids)} 个动作被白名单挡回")

    return notes
