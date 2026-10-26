"""编排层 —— 三个 Agent 串行执行，只传结构化字段。

v4 编排（三阶段语义）：

    阶段一  state_risk   身体情况（病历 + 反馈 + 需求）→ 风险报告 risk_report
                         （判断：整体风险等级 / 能否开练 / 每条伤情的禁忌 /
                           剂量口径 / 要盯的信号）+ 机器可执行投影（约束集）
    阶段二  plan_gen     风险报告 + 用户需求 + 全量动作库 → PlanDraft
                         （模型自己决定选动作、顺序、组次、负荷、休息）
    阶段三  safety_eval  计划 + 风险报告 → SafetyReport
                         （判两件事：符合通用安全标准吗？适合这位用户吗？）
    ↓ fail 则把违规清单回灌给 plan_gen 重写，最多 max_review 轮

与 v2 的差别只有一句话：**中间不再有任何一层规则替 Agent 做决定**。
不再有候选裁剪、不再有 enum 掩码、不再有区间夹紧、不再有「规则补位修复」。
唯一保留的是「生成端必须能用 ID 对上知识库」这类渲染前提。

审计思路不变：每一次 Agent 调用都记录 ``输入摘要 → 输出结构``，全程无
自然语言。任何一份计划都能回溯到：用的是哪份风险档案（``profile_hash``）、
哪版目录（``catalog_version``）、谁生成的、审查了几轮、每轮因为什么被打回。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from agents.catalog import ExerciseCatalog
from agents.contracts import PlanDraft, RiskProfile, SafetyReport
from agents.plan_agent import PlanAgent
from agents.prompts import PLAN_GEN_PROMPT_VERSION
from agents.safety_agent import SafetyEvalAgent
from agents.state_agent import StateRiskAgent

PIPELINE_VERSION = "pipeline/3.0.0"


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
    review_rounds: int = 0

    @property
    def reviewed_by_agent(self) -> bool:
        """本次结论是否由审查 Agent 给出（否则是降级的基线判定）。"""
        return self.report.review_mode == "agent"

    # 兼容旧字段名：外部脚本若引用 repaired / repair_rounds 仍能取到值
    @property
    def repaired(self) -> bool:
        return self.review_rounds > 0

    @property
    def repair_rounds(self) -> int:
        return self.review_rounds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "draft": self.draft.to_dict(),
            "safety": self.report.to_dict(),
            "review_rounds": self.review_rounds,
            "reviewed_by_agent": self.reviewed_by_agent,
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
    max_review: int = 2,
    seed: Optional[int] = None,
) -> GenerationResult:
    """跑完整条链路：状态分析 → 计划生成 → 安全会审 →（必要时）重写。

    三个 Agent 都可以从外部注入 —— 这是「换掉任一 Agent 而不动编排」的接口。
    不注入时按各自的后端能力运行：注入的 Agent 没接模型，就走降级后端，
    并在 ``report.review_mode`` 里如实标注。
    """
    audit = PipelineAudit()
    catalog = ExerciseCatalog(exercise_db)

    # ── Stage 1：状态与风险分析 ───────────────────────────────────────────
    state_agent = state_agent or StateRiskAgent(exercise_db)
    profile = state_agent.analyze(
        user_profile, feedback, workout_type=workout_type, query=query
    )
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
            "baseline_forbidden": len(profile.forbidden_reasons),
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
            "risk_report": {
                "source": (profile.risk_report or {}).get("source"),
                "risk_level": profile.risk_level,
                "clearance": profile.clearance,
                "injuries": len((profile.risk_report or {}).get("injuries") or []),
                "watch_items": len((profile.risk_report or {}).get("watch_items") or []),
                "dose_guidance_keys": sorted(
                    ((profile.risk_report or {}).get("dose_guidance") or {}).keys()
                ),
            },
            "llm": {
                "status": profile.llm_status or "skipped",
                "prompt_version": profile.llm_prompt_version,
                "appended_forbidden": list(profile.llm_forbidden),
                "tightened_joint_caps": profile.llm_joint_caps,
                "progression_note": profile.progression_note,
                "capacity_note": profile.capacity_note,
                "rationale": profile.llm_rationale,
            },
        },
    )

    # ── Stage 2：计划生成（全库自由生成）──────────────────────────────────
    agent = plan_agent or PlanAgent()
    draft = agent.generate(profile, catalog, workout_type, seed=seed)
    audit.record(
        "plan_gen",
        {
            "profile_hash": profile.profile_hash,
            "catalog_version": catalog.version,
            "catalog_size": len(catalog),
            "workout_type": workout_type,
            "backend": "llm" if agent.can_revise else "deterministic",
            "risk_report_source": (profile.risk_report or {}).get("source"),
        },
        {
            "plan_id": draft.plan_id,
            "generator": draft.generator,
            "prompt_version": draft.prompt_version or PLAN_GEN_PROMPT_VERSION,
            "slots": draft.slot_count(),
            "ids": draft.all_ids(),
            "unknown_ids": list(draft.rejected_ids),
            "defaulted_slots": draft.adjusted_slots,
        },
    )

    # ── Stage 3：安全会审 ─────────────────────────────────────────────────
    evaluator = safety_agent or SafetyEvalAgent()
    report = evaluator.evaluate(draft, profile, catalog)
    audit.record(
        "safety_eval",
        {
            "plan_id": draft.plan_id,
            "profile_hash": profile.profile_hash,
            "review_mode": report.review_mode,
            "baseline_flags": len(report.baseline_flags),
            "risk_report_source": (profile.risk_report or {}).get("source"),
        },
        report.to_dict(),
    )

    # ── Stage 4：打回重写（由生成 Agent 自己改，不由规则补位）──────────────
    rounds = 0
    while not report.passed and rounds < max_review and agent.can_revise:
        handed_back = [v.to_dict() for v in report.violations]
        rationale = report.llm_rationale
        rounds += 1
        revised = agent.revise(profile, catalog, draft, report.violations, rationale)
        if revised is None:
            rounds -= 1
            break
        draft = revised
        report = evaluator.evaluate(draft, profile, catalog)
        audit.record(
            "review_round",
            {
                "round": rounds,
                "feedback": handed_back,
                "rationale": rationale[:200],
            },
            {
                "plan_id": draft.plan_id,
                "ids": draft.all_ids(),
                "passed": report.passed,
                "verdict": report.llm_verdict,
                "violations": [v.to_dict() for v in report.violations],
            },
        )

    return GenerationResult(
        profile=profile,
        draft=draft,
        report=report,
        audit=audit,
        review_rounds=rounds,
    )


__all__ = ["run_pipeline", "GenerationResult", "PipelineAudit", "PIPELINE_VERSION"]
