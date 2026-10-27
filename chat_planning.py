"""对话内生成 / 修改计划 —— 让 /chat 直接复用三 Agent 管线。

背景：教练对话此前只跑 state_risk，动作建议完全靠 prompt 自觉。实测发现
「一共 16 组」「负荷六成」这类明确超出风险报告口径的数字没有任何人拦。

现在按意图分派（见 ``agents.intent``）：

    generate_plan   状态分析 → 计划生成 → 安全会审（含打回重写）
    revise_plan     状态分析 → 在上一版上改 → 安全会审（改不出来就退回原稿）
    ask             只做状态分析，交给教练自由回答

本模块只负责「把管线跑起来 + 把结构化产物拼成交付给前端的形状」，
不做任何安全判断 —— 判断权仍然属于三个 Agent。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agents import render_plan_draft
from agents.contracts import PlanDraft, RiskProfile
from agents.grammar import build_exercise_index
from agents.plan_agent import PlanAgent
from agents.pipeline import run_pipeline, revise_plan
from agents.profile_merge import stricter_of
from agents.safety_agent import SafetyEvalAgent
from agents.state_agent import StateRiskAgent

_PHASE_ZH = {
    "warm_up": "热身",
    "activation": "激活",
    "main_lifts": "主项",
    "accessories": "辅助",
    "cool_down": "放松",
}

_LEVEL_ZH = {"low": "低", "moderate": "中", "medium": "中", "high": "高", "unknown": "未知"}
_CLEARANCE_ZH = {
    "cleared": "可以正常训练",
    "conditional": "有条件训练",
    "restricted": "仅限受限训练",
    "blocked": "暂不建议训练",
}


@dataclass
class PlanTurn:
    """一轮对话里生成或修改出来的计划（已含审查结论）。"""

    plan: Dict[str, Any]
    safety: Dict[str, Any]
    text: str
    agents_run: List[str] = field(default_factory=list)
    review_rounds: int = 0
    revision_applied: bool = False
    elapsed_ms: int = 0
    #: 供审计：每阶段耗时，便于判断慢在哪
    stage_ms: Dict[str, int] = field(default_factory=dict)
    #: 原始草稿（带 exercise_id），落库供下一轮修订使用；不发给前端
    draft: Optional[PlanDraft] = None
    #: 这一轮采用的风险档案，落库后作为下一轮修订的安全地板
    profile: Optional[RiskProfile] = None


def _build_agents(exercise_db: Any, bridges: Any) -> Dict[str, Any]:
    """按后端能力组装三个 Agent；没有 bridges 时各自退回基线后端。"""
    if bridges is None:
        return {}
    return {
        "state_agent": StateRiskAgent(exercise_db, llm_enhance_fn=bridges.state_fn),
        "plan_agent": PlanAgent(llm_plan_fn=bridges.plan_fn),
        "safety_agent": SafetyEvalAgent(llm_judge_fn=bridges.safety_fn),
    }


def _compose_generation_text(
    profile: RiskProfile,
    plan: Dict[str, Any],
    report: Any,
    rounds: int,
) -> str:
    """生成一句话交代：给了什么、依据是什么、审查结果如何。"""
    n = sum(len(v) for v in (plan.get("phases") or {}).values())
    minutes = plan.get("estimated_duration_minutes") or "?"
    lines = [f"按风险报告出了一版计划：{n} 个动作，约 {minutes} 分钟。"]

    overall = (profile.risk_report or {}).get("overall") or {}
    summary = str(overall.get("summary") or "").strip()
    level = _LEVEL_ZH.get(profile.risk_level, profile.risk_level or "")
    clearance = _CLEARANCE_ZH.get(profile.clearance, profile.clearance or "")
    if summary:
        lines.append(f"判断依据：{summary}")
    elif level or clearance:
        lines.append(f"风险等级：{level or '?'}｜{clearance or '?'}")

    verdict = "通过" if report.passed else "未通过"
    mode = {
        "agent": "审查 Agent 判定",
        "baseline": "基线规则判定（未接模型）",
        "baseline_fallback": "基线规则判定（审查 Agent 调用失败）",
    }.get(report.review_mode, report.review_mode)
    tail = f"安全审查：{verdict}（{mode}"
    tail += f"，重写 {rounds} 轮）" if rounds else "）"
    lines.append(tail)

    if not report.passed and report.violations:
        issues = "；".join(f"{v.code}" for v in report.violations[:3])
        lines.append(f"仍有未解决的项：{issues} —— 建议告诉我怎么取舍，我再调一版。")
    elif report.llm_rationale:
        lines.append(f"审查意见：{report.llm_rationale[:120]}")

    return "\n".join(lines)


def _compose_revision_text(
    profile: RiskProfile,
    plan: Dict[str, Any],
    report: Any,
    applied: bool,
    note: str,
) -> str:
    n = sum(len(v) for v in (plan.get("phases") or {}).values())
    minutes = plan.get("estimated_duration_minutes") or "?"
    if not applied:
        return f"{note}：现在仍是 {n} 个动作、约 {minutes} 分钟的那一版。"

    lines = [f"改好了：{n} 个动作，约 {minutes} 分钟。"]
    if note:
        lines.append(note)
    verdict = "通过" if report.passed else "仍未通过"
    lines.append(f"安全审查：{verdict}")
    if report.llm_rationale:
        lines.append(f"审查意见：{report.llm_rationale[:120]}")
    return "\n".join(lines)


def _safety_payload(profile: RiskProfile, report: Any) -> Dict[str, Any]:
    overall = (profile.risk_report or {}).get("overall") or {}
    return {
        "passed": report.passed,
        "review_mode": report.review_mode,
        "llm_verdict": report.llm_verdict,
        "reviewer_note": report.llm_rationale,
        "checked_slots": report.checked_slots,
        "violations": [v.to_dict() for v in report.violations],
        "baseline_flags": [v.to_dict() for v in report.baseline_flags],
        "risk_level": profile.risk_level,
        "clearance": profile.clearance,
        "risk_summary": str(overall.get("summary") or ""),
        "profile_hash": profile.profile_hash,
    }


def run_generation_turn(
    *,
    exercise_db: Any,
    user_profile: Dict[str, Any],
    feedback: Optional[Dict[str, Any]],
    workout_type: str,
    query: str,
    bridges: Any = None,
) -> PlanTurn:
    """完整三 Agent：状态分析 → 计划生成 → 安全会审（+ 打回重写）。"""
    started = time.time()
    agents = _build_agents(exercise_db, bridges)

    t0 = time.time()
    result = run_pipeline(
        exercise_db=exercise_db,
        user_profile=user_profile,
        feedback=feedback,
        workout_type=workout_type,
        query=query,
        **agents,
    )
    pipeline_ms = int((time.time() - t0) * 1000)

    plan = render_plan_draft(
        result.draft,
        build_exercise_index(exercise_db),
        result.profile,
        result.report,
        fitness_level=str(user_profile.get("fitness_level") or "beginner"),
        workout_type=workout_type,
    )

    return PlanTurn(
        plan=plan,
        safety=_safety_payload(result.profile, result.report),
        text=_compose_generation_text(
            result.profile, plan, result.report, result.review_rounds
        ),
        agents_run=["state_risk", "plan_gen", "safety_eval"],
        review_rounds=result.review_rounds,
        elapsed_ms=int((time.time() - started) * 1000),
        stage_ms={"pipeline": pipeline_ms},
        draft=result.draft,
        profile=result.profile,
    )


def run_revision_turn(
    *,
    exercise_db: Any,
    user_profile: Dict[str, Any],
    feedback: Optional[Dict[str, Any]],
    instruction: str,
    draft: PlanDraft,
    prev_profile: Optional[RiskProfile] = None,
    history_text: str = "",
    bridges: Any = None,
) -> PlanTurn:
    """在上一版计划上按用户要求改，改完必须过审。

    状态分析会重跑 —— 用户说「膝盖更疼了，减一点」时约束本身已经变了。
    但**新档案只允许比上一轮更严**：伤病往往只存在于对话里，重新读一遍空
    档案会得出「无伤病记录」，把上一轮收紧的约束冲掉（实测发生过）。

    ``history_text`` 是最近的用户原话，拼进 query 让状态分析能重新看到
    「半月板撕裂」这类只在对话里出现过的信息。
    """
    started = time.time()
    agents = _build_agents(exercise_db, bridges)

    query = instruction
    if history_text.strip():
        query = f"{history_text.strip()[-400:]}\n\n用户刚才说：{instruction}"

    t0 = time.time()
    state_agent = agents.get("state_agent") or StateRiskAgent(exercise_db)
    fresh = state_agent.analyze(
        user_profile,
        feedback,
        workout_type=draft.workout_type,
        query=query,
    )
    profile = stricter_of(prev_profile, fresh)
    state_ms = int((time.time() - t0) * 1000)

    t1 = time.time()
    result = revise_plan(
        exercise_db=exercise_db,
        profile=profile,
        draft=draft,
        instruction=instruction,
        plan_agent=agents.get("plan_agent"),
        safety_agent=agents.get("safety_agent"),
        max_review=1,
    )
    revise_ms = int((time.time() - t1) * 1000)

    plan = render_plan_draft(
        result.draft,
        build_exercise_index(exercise_db),
        result.profile,
        result.report,
        fitness_level=str(user_profile.get("fitness_level") or "beginner"),
        workout_type=result.draft.workout_type,
    )

    return PlanTurn(
        plan=plan,
        safety=_safety_payload(result.profile, result.report),
        text=_compose_revision_text(
            result.profile,
            plan,
            result.report,
            result.revision_applied,
            result.revision_note,
        ),
        agents_run=["state_risk", "safety_eval"],
        review_rounds=result.review_rounds,
        revision_applied=result.revision_applied,
        elapsed_ms=int((time.time() - started) * 1000),
        stage_ms={"state_risk": state_ms, "revise+review": revise_ms},
        draft=result.draft,
        profile=result.profile,
    )


def draft_from_record(record: Any) -> Optional[PlanDraft]:
    """从数据库里的计划记录还原草稿；老数据没有 draft_data 时返回 None。"""
    if record is None:
        return None
    data = getattr(record, "draft_data", None)
    if not isinstance(data, dict) or not data.get("phases"):
        return None
    try:
        return PlanDraft.from_dict(data)
    except Exception:  # noqa: BLE001 - 旧格式或缺字段都当作不可修订
        return None


def profile_from_record(record: Any) -> Optional[RiskProfile]:
    """还原生成这份计划时用的风险档案 —— 修订时的安全地板。"""
    if record is None:
        return None
    data = getattr(record, "profile_data", None)
    if not isinstance(data, dict) or not data:
        return None
    try:
        return RiskProfile.from_dict(data)
    except Exception:  # noqa: BLE001
        return None


__all__ = [
    "PlanTurn",
    "run_generation_turn",
    "run_revision_turn",
    "draft_from_record",
    "profile_from_record",
]
