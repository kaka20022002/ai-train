"""Agent 1 —— 状态与风险分析。

职责边界（刻意收窄）：
    输入：用户档案（dict）、可选训练反馈（dict）
    输出：``RiskProfile`` —— 只有 ID 集合、关节上限、阈值和规则清单
           **不产出任何自然语言**，也不产出计划。

它把「状态」和「禁忌」两件事收敛成一份可执行约束，后续两个 Agent 不再
重新解释伤病，只消费这份结构化结果。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from agents.contracts import RuleSpec, RiskProfile
from agents.grammar import joint_cap_for_severity

# 与 RiskAssessmentEngine 保持一致的阻断阈值
HIGH_THRESHOLD = 3
MEDIUM_THRESHOLD = 4
LOW_THRESHOLD = 5

SEVERITY_THRESHOLD: Dict[str, int] = {
    "high": HIGH_THRESHOLD,
    "medium": MEDIUM_THRESHOLD,
    "low": LOW_THRESHOLD,
}


class StateRiskAgent:
    """状态与风险分析 Agent。"""

    name = "state_risk"

    def __init__(self, exercise_db: Sequence[Dict[str, Any]]) -> None:
        self.exercise_db = [ex for ex in exercise_db if "id" in ex]

    # ── 主入口 ────────────────────────────────────────────────────────────
    def analyze(
        self,
        user_profile: Dict[str, Any],
        feedback: Optional[Dict[str, Any]] = None,
    ) -> RiskProfile:
        user_id = str(user_profile.get("user_id", "unknown"))
        joint_severity = self._injury_map(user_profile)

        forbidden: Dict[int, str] = {}
        for ex in self.exercise_db:
            eid = int(ex["id"])
            risk_level = int(ex.get("risk_level", 1))
            for joint, severity in joint_severity.items():
                if joint not in [str(j).lower() for j in ex.get("involved_joints", [])]:
                    continue
                threshold = SEVERITY_THRESHOLD.get(severity, 5)
                if risk_level >= threshold:
                    forbidden[eid] = f"SEVERITY_{severity.upper()}:{joint}"
                    break

        joint_caps = {
            joint: joint_cap_for_severity(severity)
            for joint, severity in joint_severity.items()
        }
        allowed_ids = tuple(
            int(ex["id"]) for ex in self.exercise_db if int(ex["id"]) not in forbidden
        )

        impact_ceiling, load_pct_cap, dynamic_rules = self._dynamic_limits(feedback)

        rules: List[RuleSpec] = []
        for joint, severity in sorted(joint_severity.items()):
            rules.append(
                RuleSpec(
                    rule_id=f"joint_cap:{joint}",
                    kind="joint_cap",
                    subject=joint,
                    threshold=joint_caps[joint],
                    source=f"severity={severity}",
                )
            )
        for eid in sorted(forbidden):
            rules.append(
                RuleSpec(
                    rule_id=f"forbidden:{eid}",
                    kind="forbidden_id",
                    subject=str(eid),
                    threshold=0,
                    source=forbidden[eid],
                )
            )
        rules.append(
            RuleSpec("impact_ceiling", "impact_ceiling", "*", impact_ceiling, "static")
        )
        rules.extend(dynamic_rules)

        return RiskProfile(
            user_id=user_id,
            allowed_ids=allowed_ids,
            forbidden_reasons=forbidden,
            joint_caps=joint_caps,
            impact_ceiling=impact_ceiling,
            load_pct_cap=load_pct_cap,
            rules=tuple(rules),
        )

    # ── 内部 ──────────────────────────────────────────────────────────────
    @staticmethod
    def _injury_map(user_profile: Dict[str, Any]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for item in user_profile.get("medical_history") or []:
            joint = str(item.get("location", "")).strip().lower()
            severity = str(item.get("severity", "")).strip().lower()
            if not joint or not severity:
                continue
            # 同一关节多次受伤时取更严重的一档
            prev = out.get(joint)
            if prev is None or _rank(severity) > _rank(prev):
                out[joint] = severity
        return out

    @staticmethod
    def _dynamic_limits(
        feedback: Optional[Dict[str, Any]]
    ) -> Tuple[int, Optional[int], List[RuleSpec]]:
        """把训练反馈翻译成强度约束。无反馈时给最宽松值。"""
        if not feedback:
            return 5, None, []

        rules: List[RuleSpec] = []
        ceiling = 5
        load_cap: Optional[int] = None

        pain = feedback.get("pain_feedback") or {}
        if pain.get("has_pain"):
            ceiling = 3
            load_cap = 60
            rules.append(RuleSpec("pain_ceiling", "impact_ceiling", "*", ceiling, "feedback:pain"))
            rules.append(RuleSpec("pain_load", "load_pct", "*", load_cap, "feedback:pain"))

        rpe = feedback.get("rpe")
        if isinstance(rpe, (int, float)) and rpe >= 8:
            if load_cap is None or load_cap > 70:
                load_cap = 70
            rules.append(RuleSpec("rpe_load", "load_pct", "*", 70, f"feedback:rpe={rpe}"))

        completion = feedback.get("completion_rate")
        if isinstance(completion, (int, float)) and completion < 0.6:
            if load_cap is None or load_cap > 70:
                load_cap = 70
            rules.append(
                RuleSpec("low_completion_load", "load_pct", "*", 70, f"feedback:completion={completion}")
            )

        return ceiling, load_cap, rules


def _rank(severity: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(severity, 0)
