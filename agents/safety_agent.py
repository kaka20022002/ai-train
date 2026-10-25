"""Agent 3 —— 计划安全评估。

职责边界：
    输入：``PlanDraft`` + ``RiskProfile`` + ``RiskGrammar``
    输出：``SafetyReport`` —— 只有违规码、计数与探针结果，**不产出自然语言**。

它独立于生成过程：即使生成 Agent 被替换成外部实现、甚至被注入恶意输出，
这一层仍然用同一份谓词集做判定。为了让「不可能违规」可被量化验证，
它还会主动做**对抗探针**：把禁忌 ID 硬塞进计划，看是否被拦下。
"""
from __future__ import annotations

from typing import List, Tuple

from agents.contracts import PlanDraft, RiskProfile, SafetyReport, Slot, Violation
from agents.grammar import RiskGrammar


class SafetyEvalAgent:
    """计划安全评估 Agent。"""

    name = "safety_eval"

    def evaluate(
        self,
        draft: PlanDraft,
        profile: RiskProfile,
        grammar: RiskGrammar,
        probe_limit: int = 5,
    ) -> SafetyReport:
        violations: List[Violation] = []

        # ① 档案指纹核对：防止用旧档案生成的新计划混过去
        if draft.profile_hash and draft.profile_hash != profile.profile_hash:
            violations.append(
                Violation(
                    "STALE_PROFILE", 0, "-",
                    f"draft={draft.profile_hash} profile={profile.profile_hash}",
                )
            )

        # ② 逐槽位谓词校验
        checked = 0
        for phase, slot in draft.iter_slots():
            checked += 1
            v = grammar.validate(slot, phase)
            if v is not None:
                violations.append(v)

        # ③ 阶段内重复
        for phase, slots in draft.phases.items():
            seen: set = set()
            for slot in slots:
                if slot.exercise_id in seen:
                    violations.append(
                        Violation("DUPLICATE", slot.exercise_id, phase, "同阶段重复出现")
                    )
                seen.add(slot.exercise_id)

        # ④ 对抗探针：主动注入禁忌动作，验证拦截是否真的有效
        probes, blocked = self._adversarial_probe(profile, grammar, probe_limit)

        stats = grammar.stats()
        return SafetyReport(
            passed=not violations,
            violations=tuple(violations),
            checked_slots=checked,
            masked_count=int(stats.get("masked", 0)),
            adversarial_probes=probes,
            adversarial_blocked=blocked,
        )

    # ── 对抗探针 ──────────────────────────────────────────────────────────
    @staticmethod
    def _adversarial_probe(
        profile: RiskProfile,
        grammar: RiskGrammar,
        limit: int,
    ) -> Tuple[int, int]:
        probes = 0
        blocked = 0
        for eid in sorted(profile.forbidden_reasons)[:limit]:
            probes += 1
            probe_slot = Slot(
                exercise_id=eid,
                sets=3,
                reps="10",
                load_pct=50,
                impact=grammar.impact_of(eid),
            )
            v = grammar.validate(probe_slot, "probe")
            if v is not None:
                blocked += 1
        return probes, blocked

    # ── 静态不变量 ────────────────────────────────────────────────────────
    @staticmethod
    def assert_grammar_invariant(profile: RiskProfile) -> None:
        """允许集与禁忌集必须互斥；不成立说明编译出错，应立即失败。"""
        overlap = set(profile.allowed_ids) & set(profile.forbidden_reasons)
        if overlap:
            raise AssertionError(f"允许集与禁忌集重叠: {sorted(overlap)[:5]}")


__all__ = ["SafetyEvalAgent"]
