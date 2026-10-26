"""Agent 3 —— 计划安全审查（会审）。

职责边界：
    输入：``PlanDraft`` + ``RiskProfile``（病历与基线）+ ``ExerciseCatalog``
    输出：``SafetyReport`` —— 结论、违规清单、审查模式

**判定权在谁手上（v3 起）：审查 Agent 自己。**

    v2  规则判定 ∧ 模型判定（合取）。模型只能加严、不能放宽；
        也就是说最终结论由规则层决定，模型是个附加的报警器。

    v3  模型裁决。基线谓词的命中项（``baseline_flags``）作为**证据**随计划
        一起交给它，它逐条确认或否决 —— 否决要写进 rationale。

为什么这样改
------------
合取验收的问题在于：规则判 fail 时模型说什么都没用，模型判 fail 时规则
还能兜住 —— 模型实际上没有任何决定权。真实的多 Agent 会审不是这样：
上游提出风险提示，审查方拿全量上下文（病历原文、用户需求、计划）做判断，
然后给出结论。规则在这里变成「提示」而不是「判决」。

失败语义（必须明确，否则一次网络抖动就会变成安全漏洞）：

    模型判 fail            → 打回，计划回炉重写
    模型判 pass            → 通过（哪怕基线有命中项，模型有权推翻）
    模型超时 / 坏 JSON     → 退回基线判定（review_mode=baseline_fallback），
                            不静默放行
    完全没有模型（没配 key）→ 基线判定（review_mode=baseline），响应里明示
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from agents.catalog import ExerciseCatalog
from agents.contracts import (
    PHASES,
    VIOLATION_CODES,
    PlanDraft,
    RiskProfile,
    SafetyReport,
    Violation,
)
from agents.prompts import SAFETY_EVAL_PROMPT_VERSION

JudgeFn = Callable[[Dict[str, Any]], Dict[str, Any]]


class SafetyEvalAgent:
    """计划安全审查 Agent。"""

    name = "safety_eval"

    def __init__(self, llm_judge_fn: Optional[JudgeFn] = None) -> None:
        self._llm_judge_fn = llm_judge_fn

    @property
    def can_review(self) -> bool:
        return self._llm_judge_fn is not None

    def evaluate(
        self,
        draft: PlanDraft,
        profile: RiskProfile,
        catalog: ExerciseCatalog,
    ) -> SafetyReport:
        flags = self._baseline_flags(draft, profile, catalog)
        checked = draft.slot_count()

        # ── 没有审查 Agent：基线谓词直接当判定 ────────────────────────────
        if self._llm_judge_fn is None:
            return SafetyReport(
                passed=not flags,
                violations=tuple(flags),
                baseline_flags=tuple(flags),
                checked_slots=checked,
                review_mode="baseline",
                llm_verdict="skipped",
                llm_rationale="未接入审查 Agent，结论由基线谓词给出",
                llm_prompt_version=SAFETY_EVAL_PROMPT_VERSION,
            )

        # ── 有审查 Agent：模型裁决 ────────────────────────────────────────
        verdict, extra, rationale = self._judge(draft, profile, catalog, flags)

        if verdict == "error":
            # 调用失败不静默放行，也不无脑打回：退回基线结论这个下界
            return SafetyReport(
                passed=not flags,
                violations=tuple(flags),
                baseline_flags=tuple(flags),
                checked_slots=checked,
                review_mode="baseline_fallback",
                llm_verdict="error",
                llm_disagreed=False,
                llm_rationale=rationale,
                llm_prompt_version=SAFETY_EVAL_PROMPT_VERSION,
            )

        passed = verdict == "pass"
        return SafetyReport(
            passed=passed,
            violations=() if passed else tuple(extra),
            baseline_flags=tuple(flags),
            checked_slots=checked,
            review_mode="agent",
            llm_verdict=verdict,
            # 分歧指标：模型通过了，但基线提示里有命中项（或反之）
            llm_disagreed=(passed == bool(flags)) and bool(flags or extra),
            llm_rationale=rationale,
            llm_prompt_version=SAFETY_EVAL_PROMPT_VERSION,
        )

    # ── 模型审查 ──────────────────────────────────────────────────────────
    def _judge(
        self,
        draft: PlanDraft,
        profile: RiskProfile,
        catalog: ExerciseCatalog,
        flags: List[Violation],
    ) -> Tuple[str, List[Violation], str]:
        payload = self.build_judge_payload(draft, profile, catalog, flags)
        try:
            raw = self._llm_judge_fn(payload)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            return "error", [], f"审查 Agent 调用失败，退回基线结论：{exc}"[:240]
        if not isinstance(raw, dict):
            return "error", [], "审查 Agent 返回非对象结构，退回基线结论"

        verdict = str(raw.get("verdict") or "").strip().lower()
        if verdict not in {"pass", "fail"}:
            return "error", [], "审查 Agent 未返回合法 verdict，退回基线结论"

        rationale = str(raw.get("rationale") or "")[:400]
        extra: List[Violation] = []
        for item in raw.get("violations") or []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip().upper()
            if code not in VIOLATION_CODES:
                # 违规通道只认枚举，避免自由文本渗进来
                continue
            try:
                eid = int(item.get("exercise_id") or 0)
            except (TypeError, ValueError):
                eid = 0
            phase = str(item.get("phase") or "")
            extra.append(
                Violation(code, eid, phase, str(item.get("reason") or "")[:160])
            )

        # verdict=fail 却给不出任何合法违规条目 → 不采信，退回基线。
        # 否则模型一句 fail 就能无限拦计划（DoS 而非安全）。
        if verdict == "fail" and not extra:
            return "error", [], f"审查报 fail 但未给出合法违规码，退回基线结论。{rationale}"[:400]
        return verdict, extra, rationale

    def build_judge_payload(
        self,
        draft: PlanDraft,
        profile: RiskProfile,
        catalog: ExerciseCatalog,
        flags: Optional[List[Violation]] = None,
    ) -> Dict[str, Any]:
        flags = flags if flags is not None else self._baseline_flags(draft, profile, catalog)

        phases: Dict[str, List[Dict[str, Any]]] = {}
        for phase in PHASES:
            rows: List[Dict[str, Any]] = []
            for slot in draft.phases.get(phase, []):
                meta = catalog.meta(slot.exercise_id)
                rows.append(
                    {
                        "exercise_id": slot.exercise_id,
                        "name": catalog.name(slot.exercise_id),
                        "sets": slot.sets,
                        "reps": slot.reps,
                        "rest_seconds": slot.rest_seconds,
                        "load_pct": slot.load_pct,
                        "impact": slot.impact,
                        "type": meta.get("type", ""),
                        "pattern": meta.get("motion_pattern", ""),
                        "involved_joints": [
                            str(j).lower() for j in meta.get("involved_joints", [])
                        ],
                        "note": slot.note,
                    }
                )
            phases[phase] = rows

        ctx = profile.user_context or {}
        return {
            "plan": {
                "plan_id": draft.plan_id,
                "workout_type": draft.workout_type,
                "generator": draft.generator,
                "phases": phases,
            },
            # 审查要看得到原始病历与本次需求，而不只是被编译过的约束
            "user_profile": {
                "fitness_level": profile.fitness_level or "unknown",
                "fitness_goal": ctx.get("fitness_goal"),
                "training_frequency": ctx.get("training_frequency"),
                "available_equipment": ctx.get("available_equipment") or [],
                "medical_history": ctx.get("medical_history") or [],
                "preferences": ctx.get("preferences") or {},
                "current_request": {
                    "workout_type": ctx.get("workout_type") or draft.workout_type,
                    "query": ctx.get("query") or "",
                },
            },
            "session_cap_minutes": profile.session_cap_minutes,
            "baseline_flags": [v.to_dict() for v in flags],
            "baseline_constraints": {
                "forbidden_exercises": [
                    {"exercise_id": eid, "reason": reason}
                    for eid, reason in sorted(profile.forbidden_reasons.items())
                    if not reason.startswith("EQUIPMENT")
                ],
                "unavailable_exercises": [
                    {"exercise_id": eid, "reason": reason}
                    for eid, reason in sorted(profile.forbidden_reasons.items())
                    if reason.startswith("EQUIPMENT")
                ],
                "avoid_patterns": list(profile.avoid_patterns),
                "joint_caps": dict(sorted(profile.joint_caps.items())),
                "impact_ceiling": profile.impact_ceiling,
                "load_pct_cap": profile.load_pct_cap,
            },
        }

    # ── 基线谓词：只产证据，不产判决 ──────────────────────────────────────
    @staticmethod
    def _baseline_flags(
        draft: PlanDraft,
        profile: RiskProfile,
        catalog: ExerciseCatalog,
    ) -> List[Violation]:
        """规则阈值表的命中项。

        这些是「可疑清单」，交给审查 Agent 逐条裁决；在没有审查 Agent 时
        它们才会直接决定 ``passed``。
        """
        flags: List[Violation] = []

        if draft.profile_hash and draft.profile_hash != profile.profile_hash:
            flags.append(
                Violation(
                    "STALE_PROFILE", 0, "-",
                    f"draft={draft.profile_hash} profile={profile.profile_hash}",
                )
            )

        for phase, slot in draft.iter_slots():
            if not catalog.has(slot.exercise_id):
                flags.append(
                    Violation("UNKNOWN_ID", slot.exercise_id, phase, "ID 不在知识库")
                )
                continue
            meta = catalog.meta(slot.exercise_id)

            reason = profile.forbidden_reasons.get(slot.exercise_id)
            if reason:
                # 器械不可达与医学禁忌是两件事：前者是「做不了」，后者是
                # 「不该做」。混在一个码里会让审查员把可执行性问题当安全问题。
                code = (
                    "EQUIPMENT_UNAVAILABLE"
                    if reason.startswith("EQUIPMENT")
                    else "FORBIDDEN_ID"
                )
                flags.append(Violation(code, slot.exercise_id, phase, reason))

            impact = int(meta.get("risk_level", 1))
            if impact > profile.impact_ceiling:
                flags.append(
                    Violation(
                        "IMPACT_CEILING", slot.exercise_id, phase,
                        f"impact={impact} > {profile.impact_ceiling}",
                    )
                )
            for joint in meta.get("involved_joints", []) or []:
                cap = profile.joint_caps.get(str(joint).lower())
                if cap is not None and impact > cap:
                    flags.append(
                        Violation(
                            "JOINT_CAP", slot.exercise_id, phase,
                            f"{joint} 上限 {cap}，动作 impact={impact}",
                        )
                    )
            if (
                slot.load_pct is not None
                and profile.load_pct_cap is not None
                and slot.load_pct > profile.load_pct_cap
            ):
                flags.append(
                    Violation(
                        "LOAD_PCT", slot.exercise_id, phase,
                        f"load_pct={slot.load_pct} > {profile.load_pct_cap}",
                    )
                )

        for phase, slots in draft.phases.items():
            seen: set = set()
            for slot in slots:
                if slot.exercise_id in seen:
                    flags.append(
                        Violation("DUPLICATE", slot.exercise_id, phase, "同阶段重复出现")
                    )
                seen.add(slot.exercise_id)

        return flags


__all__ = ["SafetyEvalAgent"]
