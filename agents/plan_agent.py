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

v2 变更（处方质量）：
    1. 参数不再来自五张固定常量表，改由 ``prescription.prescribe`` 按
       「动作类型 × 阶段」推导 —— 拉伸给秒数、等长给秒数、复合给低次数高强度。
    2. 阶段内选动作时按 ``motion_pattern`` 配平，避免辅助段被同类动作（弯举 /
       下压）占满，也避免主项段三个动作全是同一个动作模式。
    3. 候选不足时逐级放宽：先放宽阶段内 impact，再放宽阶段归属，两次放宽都
       不越过档案上限。
"""
from __future__ import annotations

import random
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence

from agents.contracts import PHASES, PlanDraft, RiskProfile, Slot
from agents.grammar import RiskGrammar
from agents.prescription import (
    PHASE_COUNT,
    PHASE_MAX_IMPACT,
    prescribe,
    phase_impact_limit,
    phase_quota,
)
from agents.prompts import PLAN_GEN_PROMPT_VERSION

# 兼容旧引用：pipeline 等处仍按 ``PHASE_PRESCRIPTION[phase]["count"]`` 取数量
PHASE_PRESCRIPTION: Dict[str, Dict[str, Any]] = {
    phase: {"count": PHASE_COUNT[phase], "max_impact": PHASE_MAX_IMPACT[phase]}
    for phase in PHASES
}

LLMPlanFn = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


def _pattern_of(index: Dict[int, Dict[str, Any]], eid: int) -> str:
    meta = index.get(eid) or {}
    return str(meta.get("motion_pattern") or meta.get("type") or "other")


def pick_diverse(
    pool: Sequence[int],
    quota: int,
    index: Dict[int, Dict[str, Any]],
) -> List[int]:
    """从候选池里挑 ``quota`` 个动作，优先覆盖不同的动作模式。

    第一轮每种 ``motion_pattern`` 只取一个（池已打乱，所以具体取哪个是随机的），
    第二轮再补满。这样辅助段不会出现「三个弯举」，主项段也不会出现
    「深蹲 + 腿举 + 前蹲」这种同模式重复。
    """
    picked: List[int] = []
    seen: set = set()
    for eid in pool:
        if len(picked) >= quota:
            break
        pat = _pattern_of(index, eid)
        if pat in seen:
            continue
        seen.add(pat)
        picked.append(eid)
    if len(picked) < quota:
        for eid in pool:
            if len(picked) >= quota:
                break
            if eid not in picked:
                picked.append(eid)
    return picked


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

    # ── 候选池构建 ────────────────────────────────────────────────────────
    def _build_pool(
        self,
        profile: RiskProfile,
        grammar: RiskGrammar,
        phase: str,
        used: Sequence[int],
        rng: random.Random,
    ) -> List[int]:
        """按「严格 → 放宽 impact → 放宽阶段」三级构建候选池。"""
        ceiling = profile.impact_ceiling
        stage_cap = min(phase_impact_limit(phase), ceiling)

        strict = [
            eid
            for eid in grammar.candidates(phase, exclude=used, rng=rng)
            if grammar.impact_of(eid) <= stage_cap
        ]
        pool = list(strict)

        # 放宽 ①：阶段内 impact 上限放到档案上限（仍不越过档案）
        if len(pool) < phase_quota(phase):
            pool += [
                eid
                for eid in grammar.candidates(phase, exclude=used, rng=rng)
                if eid not in pool and grammar.impact_of(eid) <= ceiling
            ]

        # 放宽 ②：该阶段候选被档案掏空时，允许借用其它阶段的动作兜底。
        # 注意：仍然只在 allowed_ids 内，且仍受档案上限约束。
        if len(pool) < phase_quota(phase):
            loose = grammar.candidates(
                phase, exclude=used, rng=rng, allow_fallback=True
            )
            pool += [
                eid
                for eid in loose
                if eid not in pool and grammar.impact_of(eid) <= ceiling
            ]
        return pool

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
            pool = self._build_pool(profile, grammar, phase, used, rng)
            picked = pick_diverse(pool, phase_quota(phase), grammar.index)

            slots: List[Slot] = []
            for eid in picked:
                meta = grammar.index.get(eid) or {}
                pres = prescribe(phase, meta, profile.load_pct_cap)
                slots.append(
                    Slot(
                        exercise_id=eid,
                        sets=pres.sets,
                        reps=pres.reps,
                        load_pct=pres.load_pct,
                        impact=grammar.impact_of(eid),
                    )
                )
                used.append(eid)
            phases[phase] = slots

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
            "phase_candidates": {
                phase: list(grammar.phase_allowed_ids(phase)) for phase in PHASES
            },
            "joint_caps": dict(profile.joint_caps),
            "impact_ceiling": profile.impact_ceiling,
            "load_pct_cap": profile.load_pct_cap,
            "phase_targets": {
                phase: {
                    "count": phase_quota(phase),
                    "max_impact": phase_impact_limit(phase),
                }
                for phase in PHASES
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
        rejected: List[int] = []
        for phase in PHASES:
            slots: List[Slot] = []
            for item in raw.get(phase, []) or []:
                if not isinstance(item, dict) or "exercise_id" not in item:
                    continue
                try:
                    eid = int(item["exercise_id"])
                except (TypeError, ValueError):
                    continue
                # 第一层同样覆盖 LLM 输出：enum 被绕过（如返回提示词里的旧 ID）
                # 时在解析处直接挡回，绝不让禁忌 ID 进入 draft。
                if not grammar.is_allowed(eid):
                    rejected.append(eid)
                    continue
                # 阶段归属同样校验：把拉伸动作塞进主项段，即使 ID 合法也挡回。
                if not grammar.phase_matches(eid, phase):
                    rejected.append(eid)
                    continue
                # 参数不由模型决定，统一走处方推导 —— 模型只负责「选哪个、放哪段」。
                # 否则模型会把平板支撑写成「4 组 8 次」，与动作性质矛盾。
                pres = prescribe(phase, grammar.index.get(eid) or {}, profile.load_pct_cap)
                slots.append(
                    Slot(
                        exercise_id=eid,
                        sets=pres.sets,
                        reps=pres.reps,
                        load_pct=pres.load_pct,
                        impact=grammar.impact_of(eid),
                    )
                )
            phases[phase] = slots

        return PlanDraft(
            plan_id=f"draft_{uuid.uuid4().hex[:10]}",
            user_id=profile.user_id,
            workout_type=workout_type,
            phases=phases,
            generator="llm",
            grammar_version=grammar.version,
            prompt_version=PLAN_GEN_PROMPT_VERSION,
            profile_hash=profile.profile_hash,
            rejected_ids=tuple(rejected),
        )


def describe_phases(draft: PlanDraft) -> str:
    """把草稿渲染成人看的文本 —— 只在管线最外层调用，不参与 Agent 通信。"""
    lines = [f"plan_id={draft.plan_id} generator={draft.generator}"]
    for phase in PHASES:
        slots = draft.phases.get(phase, [])
        lines.append(f"  {phase}: " + ", ".join(str(s.exercise_id) for s in slots))
    return "\n".join(lines)


__all__ = ["PlanAgent", "PHASE_PRESCRIPTION", "describe_phases", "pick_diverse"]
