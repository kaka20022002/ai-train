"""编排层 —— 三个 Agent 串行执行，只传结构化字段。

审计思路：每一次 Agent 调用都记录 ``输入摘要 → 输出结构``，全程无自然语言。
任何一份计划都能回溯到：当时用的是哪个风险档案（``profile_hash``）、
哪版文法（``grammar_version``）、生成器是谁、评估出几条违规在哪个槽位。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from agents.contracts import PHASES, PlanDraft, RiskProfile, SafetyReport, Slot
from agents.grammar import RiskGrammar, build_exercise_index, compile_risk_grammar
from agents.plan_agent import PHASE_PRESCRIPTION, PlanAgent
from agents.prescription import prescribe, phase_impact_limit, phase_quota
from agents.safety_agent import SafetyEvalAgent
from agents.state_agent import StateRiskAgent

PIPELINE_VERSION = "pipeline/1.1.0"


@dataclass
class PipelineAudit:
    """逐条结构化审计记录。"""

    entries: List[Dict[str, Any]] = field(default_factory=list)

    def record(self, stage: str, payload_in: Dict[str, Any], payload_out: Dict[str, Any]) -> None:
        self.entries.append(
            {
                "seq": len(self.entries) + 1,
                "stage": stage,
                "in": payload_in,
                "out": payload_out,
            }
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"pipeline_version": PIPELINE_VERSION, "entries": self.entries}


@dataclass
class GenerationResult:
    profile: RiskProfile
    draft: PlanDraft
    report: SafetyReport
    audit: PipelineAudit
    repaired: bool = False
    repair_rounds: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "draft": self.draft.to_dict(),
            "safety": self.report.to_dict(),
            "repaired": self.repaired,
            "repair_rounds": self.repair_rounds,
            "audit": self.audit.to_dict(),
        }


def run_pipeline(
    exercise_db: Sequence[Dict[str, Any]],
    user_profile: Dict[str, Any],
    feedback: Optional[Dict[str, Any]] = None,
    workout_type: str = "full_body",
    query: Optional[str] = None,
    plan_agent: Optional[PlanAgent] = None,
    state_agent: Optional[StateRiskAgent] = None,
    safety_agent: Optional[SafetyEvalAgent] = None,
    max_repair: int = 2,
    seed: Optional[int] = None,
) -> GenerationResult:
    """跑完整条链路：状态分析 → 计划生成 → 安全评估 →（必要时）修复。

    三个 Agent 都可以从外部注入 —— 这是「换掉任一 Agent 而不动编排」的接口。
    不注入时等价于全规则后端，行为与 v1 完全一致。

    注入 LLM 版本时，三个 Agent 共用同一个 client、各自一份 prompt，
    但彼此**看不到对方的自然语言产物**：通道里只有结构化字段。
    """
    audit = PipelineAudit()
    index = build_exercise_index(exercise_db)

    # ── Stage 1：状态与风险分析 ───────────────────────────────────────────
    state_agent = state_agent or StateRiskAgent(exercise_db)
    profile = state_agent.analyze(
        user_profile, feedback, workout_type=workout_type, query=query
    )
    SafetyEvalAgent.assert_grammar_invariant(profile)

    grammar = compile_risk_grammar(profile, index)
    audit.record(
        "state_risk",
        {
            "user_id": profile.user_id,
            "injury_joints": sorted(profile.joint_caps),
            "feedback_keys": sorted((feedback or {}).keys()),
            "workout_type": workout_type,
            "query": (query or "")[:200],
        },
        {
            "profile_hash": profile.profile_hash,
            "allowed": len(profile.allowed_ids),
            "forbidden": len(profile.forbidden_reasons),
            "joint_caps": profile.joint_caps,
            "impact_ceiling": profile.impact_ceiling,
            "load_pct_cap": profile.load_pct_cap,
            "rules": len(profile.rules),
            "equipment_blocked": sum(
                1 for r in profile.forbidden_reasons.values() if r.startswith("EQUIPMENT")
            ),
            "user_context": dict(profile.user_context or {}),
            "avoid_patterns": list(profile.avoid_patterns),
            "session_cap_minutes": profile.session_cap_minutes,
            "llm": {
                "status": profile.llm_status or "skipped",
                "prompt_version": profile.llm_prompt_version,
                "appended_forbidden": list(profile.llm_forbidden),
                "tightened_joint_caps": profile.llm_joint_caps,
                "avoid_patterns": list(profile.avoid_patterns),
                "session_cap_minutes": profile.session_cap_minutes,
                "progression_note": profile.progression_note,
                "capacity_note": profile.capacity_note,
                "rationale": profile.llm_rationale,
            },
        },
    )

    # ── Stage 2：计划生成（只在允许集内采样）──────────────────────────────
    agent = plan_agent or PlanAgent()
    draft = agent.generate(profile, grammar, workout_type, seed=seed)
    audit.record(
        "plan_gen",
        {
            "profile_hash": profile.profile_hash,
            "grammar_version": grammar.version,
            "candidate_ids": len(grammar.allowed_ids),
            "workout_type": workout_type,
        },
        {
            "plan_id": draft.plan_id,
            "generator": draft.generator,
            "prompt_version": draft.prompt_version,
            "slots": draft.slot_count(),
            "ids": draft.all_ids(),
            "rejected_ids": list(draft.rejected_ids),
            "adjusted_slots": draft.adjusted_slots,
        },
    )

    # ── Stage 3：安全评估 ─────────────────────────────────────────────────
    evaluator = safety_agent or SafetyEvalAgent()
    report = evaluator.evaluate(draft, profile, grammar)
    audit.record(
        "safety_eval",
        {"plan_id": draft.plan_id, "profile_hash": profile.profile_hash},
        report.to_dict(),
    )

    # ── Stage 4：修复回路（用文法重新补位，不靠模型重生成）────────────────
    repaired = False
    rounds = 0
    while not report.passed and rounds < max_repair:
        rounds += 1
        draft = _repair(draft, grammar, report)
        report = evaluator.evaluate(draft, profile, grammar)
        repaired = True
        audit.record(
            "repair",
            {"round": rounds, "plan_id": draft.plan_id},
            {"passed": report.passed, "violations": len(report.violations)},
        )

    return GenerationResult(
        profile=profile,
        draft=draft,
        report=report,
        audit=audit,
        repaired=repaired,
        repair_rounds=rounds,
    )


def _repair(draft: PlanDraft, grammar: RiskGrammar, report: SafetyReport) -> PlanDraft:
    """丢掉违规槽位，并从文法候选集补位 —— 补位过程天然不会引入禁忌动作。

    补位同样走阶段硬过滤与处方推导，否则修复回合会把「力量动作」塞回热身段。
    """
    bad = {(v.phase, v.exercise_id) for v in report.violations if v.phase in PHASES}
    phases: Dict[str, List[Slot]] = {}
    used = [s.exercise_id for p, s in draft.iter_slots() if (p, s.exercise_id) not in bad]

    for phase in PHASES:
        keep = [s for s in draft.phases.get(phase, []) if (phase, s.exercise_id) not in bad]
        target = max(len(keep), phase_quota(phase)) if phase != "warm_up" else len(keep)
        stage_cap = min(phase_impact_limit(phase), grammar.profile.impact_ceiling)
        if len(keep) < target:
            pool = grammar.candidates(phase, exclude=used, allow_fallback=True)
            for eid in pool:
                if len(keep) >= target:
                    break
                if grammar.impact_of(eid) > stage_cap:
                    continue
                pres = prescribe(phase, grammar.index.get(eid) or {}, grammar.profile.load_pct_cap)
                keep.append(
                    Slot(
                        exercise_id=eid,
                        sets=pres.sets,
                        reps=pres.reps,
                        load_pct=pres.load_pct,
                        impact=grammar.impact_of(eid),
                    )
                )
                used.append(eid)
        phases[phase] = keep

    return PlanDraft(
        plan_id=draft.plan_id,
        user_id=draft.user_id,
        workout_type=draft.workout_type,
        phases=phases,
        generator=draft.generator,
        grammar_version=draft.grammar_version,
        prompt_version=draft.prompt_version,
        profile_hash=draft.profile_hash,
        adjusted_slots=draft.adjusted_slots,
    )


__all__ = ["run_pipeline", "GenerationResult", "PipelineAudit", "PIPELINE_VERSION"]
