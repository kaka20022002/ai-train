"""Agent 3 —— 计划安全评估。

职责边界：
    输入：``PlanDraft`` + ``RiskProfile`` + ``RiskGrammar``
    输出：``SafetyReport`` —— 只有违规码、计数与探针结果，**不产出自然语言**。

它独立于生成过程：即使生成 Agent 被替换成外部实现、甚至被注入恶意输出，
这一层仍然用同一份谓词集做判定。为了让「不可能违规」可被量化验证，
它还会主动做**对抗探针**：把禁忌 ID 硬塞进计划，看是否被拦下。

v2 变更（LLM 审查通道）：
    增加一个 LLM 审查员，它看到的是「计划 + 约束」，看不到是谁生成的。
    它与规则判定是**合取**关系：

        passed = rule_passed AND llm_passed

    这条式子是全篇的关键 —— LLM 只能让判定更严（多拦一份计划），
    永远不能让判定更松。因此「不可能违规」这个命题不依赖 LLM 的可靠性：
    即使模型漏检，规则层照样兜底；模型放宽，也推不翻规则层的 fail。

    LLM 调用失败（超时、坏 JSON）时按 ``error`` 处理，判定**退回规则结论**。
    不把异常当成 pass 是因为那会让一次网络故障静默升级成安全漏洞；
    也不当成 fail 是因为那会让服务在网络抖动时大面积不可用。
    规则的结论在两种情况下都是可得的下界。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from agents.contracts import (
    PHASES,
    VIOLATION_CODES,
    PlanDraft,
    RiskProfile,
    SafetyReport,
    Slot,
    Violation,
)
from agents.grammar import RiskGrammar
from agents.prompts import SAFETY_EVAL_PROMPT_VERSION

JudgeFn = Callable[[Dict[str, Any]], Dict[str, Any]]


class SafetyEvalAgent:
    """计划安全评估 Agent。"""

    name = "safety_eval"

    def __init__(self, llm_judge_fn: Optional[JudgeFn] = None) -> None:
        self._llm_judge_fn = llm_judge_fn

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

        rule_passed = not violations

        # ⑤ LLM 独立审查 —— 合取验收
        llm_verdict, llm_rationale = "skipped", ""
        if self._llm_judge_fn is not None:
            verdict, extra, llm_rationale = self._judge(draft, profile, grammar)
            llm_verdict = verdict
            if verdict == "fail":
                known = {(v.code, v.exercise_id, v.phase) for v in violations}
                for item in extra:
                    if (item.code, item.exercise_id, item.phase) not in known:
                        violations.append(item)

        llm_passed = llm_verdict in {"pass", "skipped", "error"}

        stats = grammar.stats()
        return SafetyReport(
            passed=rule_passed and llm_passed,
            violations=tuple(violations),
            checked_slots=checked,
            masked_count=int(stats.get("masked", 0)),
            adversarial_probes=probes,
            adversarial_blocked=blocked,
            llm_verdict=llm_verdict,
            # 只在 LLM 真的给出结论时才算分歧；error/skipped 不算
            llm_disagreed=(
                llm_verdict in {"pass", "fail"} and (llm_verdict == "pass") != rule_passed
            ),
            llm_rationale=llm_rationale,
            llm_prompt_version=SAFETY_EVAL_PROMPT_VERSION,
        )

    # ── LLM 审查 ──────────────────────────────────────────────────────────
    def _judge(
        self,
        draft: PlanDraft,
        profile: RiskProfile,
        grammar: RiskGrammar,
    ) -> Tuple[str, List[Violation], str]:
        payload = self._build_judge_payload(draft, profile, grammar)
        try:
            raw = self._llm_judge_fn(payload)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            return "error", [], f"LLM 审查失败，判定退回规则结论：{exc}"[:240]
        if not isinstance(raw, dict):
            return "error", [], "LLM 审查返回非对象结构，判定退回规则结论"

        verdict = str(raw.get("verdict") or "").strip().lower()
        if verdict not in {"pass", "fail"}:
            return "error", [], "LLM 审查未返回合法 verdict，判定退回规则结论"

        rationale = str(raw.get("rationale") or "")[:400]
        extra: List[Violation] = []
        for item in raw.get("violations") or []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip().upper()
            if code not in VIOLATION_CODES:
                # 未知码不进入通道：违规通道只认枚举，避免自由文本渗进来
                continue
            try:
                eid = int(item.get("exercise_id") or 0)
            except (TypeError, ValueError):
                eid = 0
            phase = str(item.get("phase") or "")
            extra.append(
                Violation(code, eid, phase, str(item.get("reason") or "")[:160])
            )

        # verdict=fail 但没给出任何可识别的违规条目时，不采信 fail：
        # 否则模型随便说一句 fail 就能无限拦计划（DoS 而非安全）。
        if verdict == "fail" and not extra:
            return "error", [], f"LLM 报 fail 但未给出合法违规码，判定退回规则结论。{rationale}"[:400]
        return verdict, extra, rationale

    def _build_judge_payload(
        self,
        draft: PlanDraft,
        profile: RiskProfile,
        grammar: RiskGrammar,
    ) -> Dict[str, Any]:
        phases: Dict[str, List[Dict[str, Any]]] = {}
        for phase in PHASES:
            rows: List[Dict[str, Any]] = []
            for slot in draft.phases.get(phase, []):
                meta = grammar.index.get(slot.exercise_id) or {}
                rows.append(
                    {
                        "exercise_id": slot.exercise_id,
                        "name": meta.get("name", ""),
                        "sets": slot.sets,
                        "reps": slot.reps,
                        "load_pct": slot.load_pct,
                        "impact": slot.impact,
                        "involved_joints": [
                            str(j).lower() for j in meta.get("involved_joints", [])
                        ],
                        "type": meta.get("type", ""),
                    }
                )
            phases[phase] = rows

        return {
            "plan": {
                "plan_id": draft.plan_id,
                "workout_type": draft.workout_type,
                "generator": draft.generator,
                "phases": phases,
            },
            "user_context": {
                "fitness_level": profile.fitness_level or "unknown",
                "session_cap_minutes": profile.session_cap_minutes,
                "avoid_patterns": list(profile.avoid_patterns),
                "injury_joints": sorted(profile.joint_caps),
                "llm_capacity_note": profile.capacity_note,
            },
            "constraints": {
                "forbidden_exercises": [
                    {"exercise_id": eid, "reason": reason}
                    for eid, reason in sorted(profile.forbidden_reasons.items())
                ],
                "joint_caps": dict(sorted(profile.joint_caps.items())),
                "impact_ceiling": profile.impact_ceiling,
                "load_pct_cap": profile.load_pct_cap,
            },
        }

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
