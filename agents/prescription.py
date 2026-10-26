# -*- coding: utf-8 -*-
"""处方推导：由「动作类型 × 阶段」决定组数、次数、强度。

为什么单独成模块
----------------
原实现是一张常量表 ``PHASE_PRESCRIPTION``，五个阶段各一套固定参数，与具体
动作无关。后果是：平板支撑被写成「2 组 15 次」、静态拉伸被写成「3 组 10-12 次」、
动态热身被标上「强度 40%」—— 参数本身就是错的。

本模块把参数改成**从动作属性推导**：

    拉伸（Stretch）      → 1 组 × 30 秒，无负荷，按时间计
    动态热身（Warmup）    → 1 组 × 10-12 次，自重，无负荷
    等长（Isometric）    → 2-3 组 × 30-45 秒，按时间计
    激活（Activation）   → 2 组 × 12-15 次，低强度
    复合（Compound）     → main_lifts 4×6-8 @75%；accessories 3×8-10 @60%
    孤立（Isolation）    → 3 组 × 10-12 次 @55%

自重动作（装备只有 bodyweight / band）不输出强度百分比 —— 硬拉 75% 是 1RM 的
百分比，俯卧撑没有 1RM 可言，标 40% 只会让人困惑。

接口
----
``prescribe(phase, meta, load_cap=None) -> Prescription``

纯函数，无副作用，不读取档案 —— 档案上限由调用方在构造时传入。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

# 每个阶段要几个动作（数量属于「编排」，不是「处方」，所以留在这里但单独命名）
PHASE_COUNT: Dict[str, int] = {
    "warm_up": 3,
    "activation": 3,
    "main_lifts": 3,
    "accessories": 4,
    "cool_down": 3,
}

# 每个阶段允许的最大冲击（在档案 impact_ceiling 之下再做一次阶段级收紧）
PHASE_MAX_IMPACT: Dict[str, int] = {
    "warm_up": 2,
    "activation": 2,
    "main_lifts": 4,
    "accessories": 3,
    "cool_down": 1,
}

# 只有自重/弹力带的动作不标注负荷百分比
_FREE_EQUIPMENT = {"bodyweight", "band", "none", ""}


@dataclass(frozen=True)
class Prescription:
    """一个槽位的处方参数。"""

    sets: int
    reps: str
    load_pct: Optional[int]
    max_impact: int
    timed: bool = False
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sets": self.sets,
            "reps": self.reps,
            "load_pct": self.load_pct,
            "max_impact": self.max_impact,
            "timed": self.timed,
        }


def is_bodyweight(meta: Dict[str, Any]) -> bool:
    """动作是否无需外部负重（自重 / 弹力带 / 无装备）。"""
    eq = meta.get("required_equipment") or []
    if not eq:
        return True
    return all(str(e).strip().lower() in _FREE_EQUIPMENT for e in eq)


def _cap_load(load: Optional[int], cap: Optional[int]) -> Optional[int]:
    if load is None:
        return None
    return load if cap is None else min(load, cap)


def prescribe(
    phase: str,
    meta: Dict[str, Any],
    load_cap: Optional[int] = None,
) -> Prescription:
    """由动作类型与阶段推导处方参数。

    Parameters
    ----------
    phase
        目标阶段，取值见 ``agents.contracts.PHASES``。
    meta
        动作库中的一条记录（需要 ``type``，可选 ``required_equipment``）。
    load_cap
        档案给出的强度上限（百分比）。来自训练反馈动态收紧时可能低于默认值。
    """
    etype = str(meta.get("type") or "Compound")
    free = is_bodyweight(meta)
    max_impact = PHASE_MAX_IMPACT.get(phase, 3)
    timed_hint = bool(meta.get("is_timed"))

    # ① 静态拉伸 / 放松：一律按时间计，无负荷
    if etype == "Stretch":
        return Prescription(1, "30 秒", None, max_impact, True, "静态拉伸，保持均匀呼吸不弹震")

    # ② 动态热身：自重、多次数、无负荷
    if etype == "Warmup":
        return Prescription(1, "10-12 次", None, max_impact, False, "动态活动，幅度渐进不追求极限")

    # ③ 等长：按秒计
    if etype == "Isometric":
        hold = "30-45 秒" if phase != "cool_down" else "30 秒"
        return Prescription(3 if phase != "cool_down" else 1, hold, None, max_impact, True,
                            "等长保持，腰背中立不塌腰")

    # ④ 激活 / 稳定：低强度、重控制
    if etype == "Activation":
        load = None if free else _cap_load(35, load_cap)
        return Prescription(2, "12-15 次", load, max_impact, timed_hint,
                            "慢速离心，感受目标肌群发力")

    # ⑤ 力量动作：按阶段区分强度区间
    # 自重动作（俯卧撑、引体向上）没有 1RM 可言，一律不标负荷百分比 —— 标 75%
    # 会让人误以为要加负重。
    if etype == "Compound":
        if phase == "main_lifts":
            # 自重主项（俯卧撑、引体向上）没有负荷可加，只能靠次数和动作难度
            # 调节强度，所以次数区间要高于杠铃主项。
            if free:
                return Prescription(4, "10-15 次", None, max_impact, False,
                                    "自重主项，控制离心，留 1-2 次余力")
            return Prescription(4, "6-8 次", _cap_load(75, load_cap), max_impact, False,
                                "主项，组间充分休息，动作质量优先")
        if phase == "accessories":
            load = None if free else _cap_load(60, load_cap)
            reps = "12-15 次" if free else "8-10 次"
            return Prescription(3, reps, load, max_impact, False, "")
        load = None if free else _cap_load(40, load_cap)
        return Prescription(2, "10 次", load, max_impact, False, "")

    # ⑥ 孤立动作
    if phase == "main_lifts":  # 理论上不会走到，防御性返回
        load = None if free else _cap_load(60, load_cap)
        return Prescription(3, "8-10 次", load, max_impact, False, "")
    if phase == "cool_down":
        return Prescription(1, "30 秒", None, max_impact, True, "低强度收尾，呼吸放松")
    load = None if free else _cap_load(55, load_cap)
    return Prescription(3, "10-12 次", load, max_impact, timed_hint, "控制离心，避免借力")


def phase_quota(phase: str) -> int:
    return PHASE_COUNT.get(phase, 3)


def phase_impact_limit(phase: str) -> int:
    return PHASE_MAX_IMPACT.get(phase, 3)


def prescribe_for_phase(
    phase: str,
    candidates: Tuple[int, ...],
    index: Dict[int, Dict[str, Any]],
    load_cap: Optional[int] = None,
) -> Dict[int, Prescription]:
    """批量推导：给该阶段每个候选算好处方，供编排时比较。"""
    return {
        eid: prescribe(phase, index.get(eid) or {}, load_cap)
        for eid in candidates
        if eid in index
    }


__all__ = [
    "PHASE_COUNT",
    "PHASE_MAX_IMPACT",
    "Prescription",
    "is_bodyweight",
    "prescribe",
    "prescribe_for_phase",
    "phase_quota",
    "phase_impact_limit",
]
