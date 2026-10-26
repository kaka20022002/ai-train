# -*- coding: utf-8 -*-
"""把三 Agent 管线的结构化产物渲染成对外的计划 JSON。

设计上这是一层**单向适配器**：Agent 之间只传 ``{exercise_id, sets, reps,
load_pct, impact}``，动作名称、休息时长、目标肌群这些「给人看」的字段
全部在这里补全。这样渲染逻辑集中一处，Agent 内部保持纯结构化。

产物结构与 ``PlanGeneratorMock.export_plan_as_json`` 完全对齐，
因此可以直接复用现有的响应模型、落库逻辑与前端类型。

v2 变更：
    - 补 ``name_zh``（后端权威中文名，前端映射表之外的第二层保障）
    - 休息时长按阶段与动作性质区分，不再一律 60 秒
    - 总时长按「计时动作算秒、次数动作算次数×3 秒」估算，不再统一按 45 秒
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agents.contracts import PHASES, PlanDraft, RiskProfile, SafetyReport
from agents.prescription import is_bodyweight, prescribe

RENDERER_VERSION = "agents_render/2.0.0"

# 阶段 → (是否为主项, 备注)
PHASE_LABELS: Dict[str, str] = {
    "warm_up": "热身",
    "activation": "激活",
    "main_lifts": "主项训练",
    "accessories": "辅助训练",
    "cool_down": "放松",
}

# 阶段 → 组间休息秒数（主项按水平再细分）
_STAGE_REST: Dict[str, int] = {
    "warm_up": 20,
    "activation": 30,
    "main_lifts": 90,
    "accessories": 60,
    "cool_down": 10,
}


def _rest_seconds(phase: str, fitness_level: str, meta: Dict[str, Any]) -> int:
    """休息时长按阶段区分；拉伸几乎不休息，主项新手多休息 30 秒。"""
    base = _STAGE_REST.get(phase, 60)
    if phase == "main_lifts" and fitness_level == "beginner":
        base += 30
    if meta.get("type") == "Stretch":
        return 10
    return base


def _slot_seconds(slot: Dict[str, Any], meta: Dict[str, Any]) -> int:
    """估算一个动作占用的秒数：计时动作按保持时长，计次动作按次数×3 秒。"""
    sets = max(1, int(slot["sets"]))
    reps = str(slot["reps"])
    if meta.get("is_timed") or ("秒" in reps or "second" in reps.lower()):
        hold = 30
        digits = "".join(ch for ch in reps.split("-")[0] if ch.isdigit())
        if digits:
            hold = int(digits)
        work = hold * sets
    else:
        num = "".join(ch for ch in reps.split("-")[0] if ch.isdigit())
        per_rep = 3
        work = int(num or 10) * per_rep * sets
    return work + int(slot["rest_seconds"]) * max(0, sets - 1)


def _estimate_duration(phases: Dict[str, List[Dict[str, Any]]]) -> int:
    """粗略估算总时长（分钟，向上取整）。"""
    total = 0
    for slots in phases.values():
        for slot in slots:
            total += int(slot.get("_seconds") or 0)
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

    for phase in PHASES:
        for slot in draft.phases.get(phase, []):
            meta = exercise_index.get(slot.exercise_id, {})
            # 模型给了休息时长就用模型的（它能按当日疲劳调整），没给才按阶段默认
            rest = (
                slot.rest_seconds
                if slot.rest_seconds is not None
                else _rest_seconds(phase, fitness_level, meta)
            )
            item = {
                "name": meta.get("name", f"Exercise #{slot.exercise_id}"),
                "name_zh": meta.get("name_zh") or None,
                "sets": slot.sets,
                "reps": slot.reps,
                "rest_seconds": rest,
                "notes": _slot_note(phase, slot, meta, profile),
                "target_muscle": meta.get("target_muscle") or "Multiple",
            }
            if slot.load_pct is not None:
                item["load_pct"] = slot.load_pct
            item["_seconds"] = _slot_seconds(item, meta)
            phases[phase].append(item)

    duration = _estimate_duration(phases)
    for slots in phases.values():
        for it in slots:
            it.pop("_seconds", None)

    return {
        "plan_id": draft.plan_id,
        "user_id": draft.user_id,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "workout_type": draft.workout_type or workout_type,
        "estimated_duration_minutes": duration,
        "phases": phases,
        "safety_notes": build_safety_notes(profile, report, draft),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator_version": f"{draft.generator}+{draft.grammar_version}",
    }


def _slot_note(phase: str, slot: Any, meta: Dict[str, Any], profile: RiskProfile) -> Optional[str]:
    """给单条动作补一句上下文：模型给的要领在前，规则补的参数说明在后。"""
    pres = prescribe(phase, meta, profile.load_pct_cap)
    parts: List[str] = []
    if getattr(slot, "note", ""):
        parts.append(slot.note)
    if slot.load_pct is not None:
        parts.append(f"强度 {slot.load_pct}%")
    elif is_bodyweight(meta) and phase in ("main_lifts", "accessories"):
        parts.append("自重动作，无需负重")
    if pres.note:
        parts.append(pres.note)
    if slot.impact >= 4:
        parts.append("高冲击动作，动作质量优先于负荷")
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

    if profile.avoid_patterns:
        notes.append(f"⛔ 已回避动作模式：{'、'.join(profile.avoid_patterns)}")

    if profile.session_cap_minutes:
        notes.append(f"⏱️ 单次训练时长上限：{profile.session_cap_minutes} 分钟")

    if draft is not None and draft.rejected_ids:
        notes.append(f"🔍 生成阶段另有 {len(draft.rejected_ids)} 个动作被白名单挡回")

    if draft is not None and draft.adjusted_slots:
        notes.append(
            f"🔧 另有 {draft.adjusted_slots} 个动作的组次负荷被夹进合法区间"
        )

    return notes
