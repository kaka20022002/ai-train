"""Agent 1 —— 状态与风险分析。

职责边界（刻意收窄）：
    输入：用户档案（dict）、可选训练反馈（dict）
    输出：``RiskProfile`` —— 只有 ID 集合、关节上限、阈值和规则清单
           **不产出任何自然语言**，也不产出计划。

它把「状态」和「禁忌」两件事收敛成一份可执行约束，后续两个 Agent 不再
重新解释伤病，只消费这份结构化结果。

v2 变更（LLM 增强通道）：
    规则引擎仍是**唯一的下限来源**，LLM 只在规则之外做**单向追加**：

        allowed_new  = allowed_rule − LLM 追加的禁忌
        joint_cap_new = min(joint_cap_rule, LLM 建议值)
        ceiling_new   = min(ceiling_rule, LLM 建议值)

    也就是说 LLM 的每一类输出都只能让约束**更严**。它提议移除禁忌、
    或把上限调高，都会被静默丢弃并计入 ``llm_status``。这样做的原因是
    上游一旦可以被放宽，下游两个 Agent 的合规性就不再可证明 ——
    ``SafetyEvalAgent.assert_grammar_invariant`` 那类不变量必须永远成立。

    LLM 的真实收益是规则表结构性看不到的东西：病历自由文本
    （"右膝 ACL 术后两年，深蹲到不了底"）、多条伤情叠加后的整体保守需求。
    因此只把「涉及受伤关节的动作」发给它，而不是整库 70 条。
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from agents.contracts import RuleSpec, RiskProfile
from agents.grammar import joint_cap_for_severity
from agents.prompts import STATE_RISK_PROMPT_VERSION

# 与 RiskAssessmentEngine 保持一致的阻断阈值
HIGH_THRESHOLD = 3
MEDIUM_THRESHOLD = 4
LOW_THRESHOLD = 5

SEVERITY_THRESHOLD: Dict[str, int] = {
    "high": HIGH_THRESHOLD,
    "medium": MEDIUM_THRESHOLD,
    "low": LOW_THRESHOLD,
}

EnhanceFn = Callable[[Dict[str, Any]], Dict[str, Any]]


class StateRiskAgent:
    """状态与风险分析 Agent。"""

    name = "state_risk"

    def __init__(
        self,
        exercise_db: Sequence[Dict[str, Any]],
        llm_enhance_fn: Optional[EnhanceFn] = None,
    ) -> None:
        self.exercise_db = [ex for ex in exercise_db if "id" in ex]
        self._llm_enhance_fn = llm_enhance_fn

    # ── 主入口 ────────────────────────────────────────────────────────────
    def analyze(
        self,
        user_profile: Dict[str, Any],
        feedback: Optional[Dict[str, Any]] = None,
    ) -> RiskProfile:
        profile = self._analyze_rules(user_profile, feedback)
        if self._llm_enhance_fn is None:
            return replace(profile, llm_status="skipped")
        return self._enhance(profile, user_profile, feedback)

    # ── 规则后端（唯一的下限来源）─────────────────────────────────────────
    def _analyze_rules(
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

    # ── LLM 单向增强 ──────────────────────────────────────────────────────
    def _enhance(
        self,
        base: RiskProfile,
        user_profile: Dict[str, Any],
        feedback: Optional[Dict[str, Any]],
    ) -> RiskProfile:
        if not base.joint_caps and not feedback:
            # 无伤病、无异常反馈 —— 规则已是最宽松，没有可追加的余地
            return replace(base, llm_status="empty")

        payload = self._build_enhance_payload(base, user_profile, feedback)
        try:
            raw = self._llm_enhance_fn(payload)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001 - 任何失败都必须退回规则结果
            return replace(
                base,
                llm_status="error",
                llm_rationale=f"LLM 调用失败，已退回规则结果：{exc}"[:240],
                llm_prompt_version=STATE_RISK_PROMPT_VERSION,
            )
        if not isinstance(raw, dict):
            return replace(
                base,
                llm_status="error",
                llm_rationale="LLM 返回非对象结构，已退回规则结果",
                llm_prompt_version=STATE_RISK_PROMPT_VERSION,
            )
        return self._merge_enhancement(base, raw)

    def _build_enhance_payload(
        self,
        base: RiskProfile,
        user_profile: Dict[str, Any],
        feedback: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        injured = set(base.joint_caps)
        allowed_set = set(base.allowed_ids)
        # 只发「涉及受伤关节」的允许动作：既压低 token，也避免模型在
        # 与自己无关的动作上乱开枪。
        scoped = [
            {
                "exercise_id": int(ex["id"]),
                "name": ex.get("name", ""),
                "type": ex.get("type", ""),
                "involved_joints": [str(j).lower() for j in ex.get("involved_joints", [])],
                "risk_level": int(ex.get("risk_level", 1)),
            }
            for ex in self.exercise_db
            if int(ex["id"]) in allowed_set
            and injured & {str(j).lower() for j in ex.get("involved_joints", [])}
        ]
        return {
            "user_profile": {
                "user_id": user_profile.get("user_id"),
                "age": user_profile.get("age"),
                "fitness_level": user_profile.get("fitness_level"),
                "medical_history": user_profile.get("medical_history") or [],
            },
            "recent_feedback": feedback or {},
            "rule_engine_output": {
                "joint_caps": dict(base.joint_caps),
                "impact_ceiling": base.impact_ceiling,
                "load_pct_cap": base.load_pct_cap,
                "forbidden": [
                    {"exercise_id": eid, "reason": reason}
                    for eid, reason in sorted(base.forbidden_reasons.items())
                ],
            },
            "allowed_exercises": scoped,
        }

    def _merge_enhancement(
        self, base: RiskProfile, raw: Dict[str, Any]
    ) -> RiskProfile:
        """把 LLM 建议并入规则结果 —— 每一类都只取更严的一方。"""
        index = {int(ex["id"]): ex for ex in self.exercise_db}
        allowed_set = set(base.allowed_ids)

        added: Dict[int, str] = {}
        for item in raw.get("additional_forbidden") or []:
            if not isinstance(item, dict):
                continue
            try:
                eid = int(item.get("exercise_id"))
            except (TypeError, ValueError):
                continue
            # 只接受「当前允许且存在于知识库」的 ID。
            # 已在禁忌集里的不能再被"追加"，更不可能被移除。
            if eid not in allowed_set or eid not in index:
                continue
            reason = str(item.get("reason") or "LLM 追加禁忌")
            added[eid] = f"LLM_APPENDED:{reason}"[:160]

        joint_caps = dict(base.joint_caps)
        for joint, cap in (raw.get("additional_joint_caps") or {}).items():
            key = str(joint).lower()
            try:
                value = int(cap)
            except (TypeError, ValueError):
                continue
            # 只允许收窄已知关节的上限；不新建关节、不放宽
            if key in joint_caps and value < joint_caps[key]:
                joint_caps[key] = value

        ceiling = base.impact_ceiling
        override = raw.get("impact_ceiling_override")
        if isinstance(override, (int, float)) and not isinstance(override, bool):
            candidate = int(override)
            if 1 <= candidate < ceiling:
                ceiling = candidate

        load_cap = base.load_pct_cap
        load_override = raw.get("load_pct_cap_override")
        if isinstance(load_override, (int, float)) and not isinstance(load_override, bool):
            candidate = int(load_override)
            if 0 <= candidate <= 100 and (load_cap is None or candidate < load_cap):
                load_cap = candidate

        rationale = str(raw.get("rationale") or "")[:400]

        if not added and joint_caps == base.joint_caps and ceiling == base.impact_ceiling \
                and load_cap == base.load_pct_cap:
            return replace(
                base,
                llm_status="empty",
                llm_rationale=rationale,
                llm_prompt_version=STATE_RISK_PROMPT_VERSION,
            )

        forbidden_reasons = dict(base.forbidden_reasons)
        forbidden_reasons.update(added)
        allowed_ids = tuple(i for i in base.allowed_ids if i not in added)

        rules: List[RuleSpec] = list(base.rules)
        for eid in sorted(added):
            rules.append(RuleSpec(f"llm_forbidden:{eid}", "forbidden_id", str(eid), 0, "llm:medical_text"))
        for joint in sorted(joint_caps):
            if joint in base.joint_caps and joint_caps[joint] != base.joint_caps[joint]:
                rules.append(
                    RuleSpec(f"llm_joint_cap:{joint}", "joint_cap", joint, joint_caps[joint], "llm:medical_text")
                )
        if ceiling != base.impact_ceiling:
            rules.append(RuleSpec("llm_impact_ceiling", "impact_ceiling", "*", ceiling, "llm:feedback"))
        if load_cap != base.load_pct_cap:
            rules.append(RuleSpec("llm_load_pct", "load_pct", "*", load_cap or 0, "llm:feedback"))

        # profile_hash 必须重算：约束集变了，旧 hash 会让下游的
        # STALE_PROFILE 检查失去意义。
        return RiskProfile(
            user_id=base.user_id,
            allowed_ids=allowed_ids,
            forbidden_reasons=forbidden_reasons,
            joint_caps=joint_caps,
            impact_ceiling=ceiling,
            load_pct_cap=load_cap,
            rules=tuple(rules),
            llm_forbidden=tuple(added),
            llm_joint_caps={j: v for j, v in joint_caps.items() if base.joint_caps.get(j) != v},
            llm_rationale=rationale,
            llm_status="applied",
            llm_prompt_version=STATE_RISK_PROMPT_VERSION,
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
