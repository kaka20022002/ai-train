"""把两份风险档案合成一份更严的 —— 修订计划时的安全底线。

为什么需要它：伤病信息往往只出现在**对话里**（用户第一次说「半月板撕裂」），
并不会写进 ``user_profile``。修订时如果只拿空档案重新跑一次状态分析，模型会
得到「无伤病记录 → 可正常训练」的结论，把上一轮好不容易收紧的约束全部冲掉。

实测踩过：生成时 risk_level=moderate、禁忌含深屈膝与弓步；用户说「平板支撑
换成别的」之后重算出的档案变成 low / 无伤病记录，``avoid_patterns`` 从
``["lunge"]`` 变成空 —— 等于一句话就让安全等级掉了两档。

合并原则只有一条：**只能更严，不能更松**。这与阶段一「报告的不对称约束」
是同一个立场（``clearance`` / ``risk_level`` 只允许向保守方向修正）。
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from agents.contracts import RiskProfile

_RISK_RANK = {"": 0, "low": 1, "moderate": 2, "medium": 2, "high": 3}
_CLEARANCE_RANK = {"": 0, "cleared": 1, "conditional": 2, "restricted": 3, "blocked": 4}


def _min_opt(a: Optional[int], b: Optional[int]) -> Optional[int]:
    """None 表示「没有上限」，因此有值的一侧恒更严。"""
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def stricter_of(base: Optional[RiskProfile], other: RiskProfile) -> RiskProfile:
    """返回 base 与 other 中更严的一份；base 为空时直接用 other。"""
    if base is None:
        return other

    base_rank = (
        _RISK_RANK.get(base.risk_level, 0),
        _CLEARANCE_RANK.get(base.clearance, 0),
    )
    other_rank = (
        _RISK_RANK.get(other.risk_level, 0),
        _CLEARANCE_RANK.get(other.clearance, 0),
    )
    # 报告（叙述部分）取更保守的那份；约束则逐项取严
    report_source = base if base_rank >= other_rank else other

    allowed: Tuple[int, ...] = tuple(
        sorted(set(base.allowed_ids) & set(other.allowed_ids))
        or set(base.allowed_ids) | set(other.allowed_ids)
    )

    forbidden: Dict[int, str] = dict(other.forbidden_reasons)
    for eid, reason in base.forbidden_reasons.items():
        forbidden.setdefault(eid, reason)

    joint_caps = dict(base.joint_caps)
    for joint, cap in other.joint_caps.items():
        joint_caps[joint] = min(joint_caps.get(joint, cap), cap)

    merged = RiskProfile(
        user_id=base.user_id or other.user_id,
        allowed_ids=allowed,
        forbidden_reasons=forbidden,
        joint_caps=joint_caps,
        impact_ceiling=min(base.impact_ceiling, other.impact_ceiling),
        load_pct_cap=_min_opt(base.load_pct_cap, other.load_pct_cap),
        rules=base.rules or other.rules,
        # hash 必须重算：合并后的约束既不是 base 也不是 other
        profile_hash="",
        llm_forbidden=tuple(sorted(set(base.llm_forbidden) | set(other.llm_forbidden))),
        llm_joint_caps={**other.llm_joint_caps, **base.llm_joint_caps},
        llm_rationale=report_source.llm_rationale,
        llm_status=report_source.llm_status,
        llm_prompt_version=report_source.llm_prompt_version,
        avoid_patterns=tuple(
            sorted(set(base.avoid_patterns) | set(other.avoid_patterns))
        ),
        session_cap_minutes=_min_opt(
            base.session_cap_minutes, other.session_cap_minutes
        ),
        progression_note=report_source.progression_note,
        capacity_note=report_source.capacity_note,
        fitness_level=other.fitness_level or base.fitness_level,
        user_context=other.user_context or base.user_context,
        risk_report=dict(report_source.risk_report or {}),
    )
    return merged


__all__ = ["stricter_of"]
