"""Agent 2 —— 计划生成。

职责边界：
    输入：``RiskProfile``（只读）+ ``RiskGrammar``（只读）+ 训练类型
    输出：``PlanDraft`` —— 严格只有 ``{exercise_id, sets, reps, load_pct, impact}``

它**看不到**伤病原文，也**拿不到**禁忌动作的自然语言描述；它能看到的只有
一份被裁剪过的候选 ID 集合。这是「合规不可能被违反」的第一道保证。

两种后端：
    deterministic —— 从文法候选集中采样，禁忌动作不在采样空间内
    llm           —— 下发以允许 ID 为 enum 的 JSON Schema（结构化输出），
                     解码阶段即 mask；若模型仍越界，由 SafetyEvalAgent 拦下
"""
from __future__ import annotations

import random
import uuid
from typing import Any, Callable, Dict, List, Optional

from agents.contracts import PHASES, PlanDraft, RiskProfile, Slot
from agents.grammar import RiskGrammar

# 各阶段的处方模板：(sets, reps, load_pct 基准)
PHASE_PRESCRIPTION: Dict[str, Dict[str, Any]] = {
    "warm_up": {"count": 3, "sets": 2, "reps": "15", "load_pct": 40, "max_impact": 2},
    "activation": {"count": 3, "sets": 2, "reps": "15", "load_pct": 35, "max_impact": 2},
    "main_lifts": {"count": 3, "sets": 4, "reps": "6-8", "load_pct": 75, "max_impact": 4},
    "accessories": {"count": 4, "sets": 3, "reps": "10-12", "load_pct": 55, "max_impact": 3},
    "cool_down": {"count": 3, "sets": 1, "reps": "30 seconds", "load_pct": None, "max_impact": 1},
}

LLMPlanFn = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


class PlanAgent:
    """计划生成 Agent。"""

    name = "plan_gen"

    def __init__(self, llm_plan_fn: Optional[LLMPlanFn] = None) -> None:
        self._llm_plan_fn = llm_plan_fn

    def generate(
        self,
        profile: RiskProfile,
        grammar: RiskGrammar,
        workout_type: str = "full_body",
        seed: Optional[int] = None,
    ) -> PlanDraft:
        if self._llm_plan_fn is not None:
            draft = self._generate_with_llm(profile, grammar, workout_type)
            if draft is not None:
                return draft
        return self._generate_deterministic(profile, grammar, workout_type, seed)

    # ── 确定性后端 ────────────────────────────────────────────────────────
    def _generate_deterministic(
        self,
        profile: RiskProfile,
        grammar: RiskGrammar,
        workout_type: str,
        seed: Optional[int] = None,
    ) -> PlanDraft:
        rng = random.Random(seed if seed is not None else hash(profile.profile_hash + workout_type))
        phases: Dict[str, List[Slot]] = {}
        used: List[int] = []

        for phase in PHASES:
            spec = PHASE_PRESCRIPTION[phase]
            picked: List[Slot] = []
            # 只在文法候选集里取，且受 impact 上限二次裁剪
            pool = [
                eid
                for eid in grammar.candidates(phase, exclude=used, rng=rng)
                if grammar.impact_of(eid) <= min(spec["max_impact"], profile.impact_ceiling)
            ]
            for eid in pool[: spec["count"]]:
                picked.append(
                    Slot(
                        exercise_id=eid,
                        sets=int(spec["sets"]),
                        reps=str(spec["reps"]),
                        load_pct=_clamp_load(spec["load_pct"], profile.load_pct_cap),
                        impact=grammar.impact_of(eid),
                    )
                )
                used.append(eid)
            phases[phase] = picked

        return PlanDraft(
            plan_id=f"draft_{uuid.uuid4().hex[:10]}",
            user_id=profile.user_id,
            workout_type=workout_type,
            phases=phases,
            generator="deterministic",
            grammar_version=grammar.version,
            profile_hash=profile.profile_hash,
        )

    # ── LLM 后端（结构化输出）──────────────────────────────────────────────
    def build_request_payload(
        self,
        profile: RiskProfile,
        grammar: RiskGrammar,
        workout_type: str,
    ) -> Dict[str, Any]:
        """发给模型的请求体 —— 全结构化，不含任何伤病原文或自然语言描述。"""
        return {
            "workout_type": workout_type,
            "candidate_exercise_ids": list(grammar.allowed_ids),
            "joint_caps": dict(profile.joint_caps),
            "impact_ceiling": profile.impact_ceiling,
            "load_pct_cap": profile.load_pct_cap,
            "phase_prescription": {
                p: {
                    "count": PHASE_PRESCRIPTION[p]["count"],
                    "sets": PHASE_PRESCRIPTION[p]["sets"],
                    "reps": PHASE_PRESCRIPTION[p]["reps"],
                }
                for p in PHASES
            },
            "grammar_version": grammar.version,
            "profile_hash": profile.profile_hash,
        }

    def _generate_with_llm(
        self,
        profile: RiskProfile,
        grammar: RiskGrammar,
        workout_type: str,
    ) -> Optional[PlanDraft]:
        payload = self.build_request_payload(profile, grammar, workout_type)
        schema = grammar.plan_schema()
        try:
            raw = self._llm_plan_fn(payload, schema)  # type: ignore[misc]
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None

        phases: Dict[str, List[Slot]] = {}
        for phase in PHASES:
            slots: List[Slot] = []
            for item in raw.get(phase, []) or []:
                if not isinstance(item, dict) or "exercise_id" not in item:
                    continue
                try:
                    slots.append(Slot.from_dict(item))
                except (TypeError, ValueError):
                    continue
            phases[phase] = slots

        return PlanDraft(
            plan_id=f"draft_{uuid.uuid4().hex[:10]}",
            user_id=profile.user_id,
            workout_type=workout_type,
            phases=phases,
            generator="llm",
            grammar_version=grammar.version,
            profile_hash=profile.profile_hash,
        )


def _clamp_load(load_pct: Optional[int], cap: Optional[int]) -> Optional[int]:
    if load_pct is None:
        return None
    if cap is None:
        return load_pct
    return min(load_pct, cap)


def describe_phases(draft: PlanDraft) -> str:
    """把草稿渲染成人看的文本 —— 只在管线最外层调用，不参与 Agent 通信。"""
    lines = [f"plan_id={draft.plan_id} generator={draft.generator}"]
    for phase in PHASES:
        slots = draft.phases.get(phase, [])
        lines.append(f"  {phase}: " + ", ".join(str(s.exercise_id) for s in slots))
    return "\n".join(lines)


__all__ = ["PlanAgent", "PHASE_PRESCRIPTION", "describe_phases"]
