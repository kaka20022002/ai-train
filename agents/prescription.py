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
from typing import Any, Dict, List, Optional, Tuple

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

# 只有自重/弹力带的动作不标注负荷百分比。
# ``pull_up_bar`` 也算自重：引体向上、悬垂举腿靠身体重量，没有 1RM 可标 ——
# 少了这一项，这两个动作会被标成「60% 强度」，与常识矛盾。
_FREE_EQUIPMENT = {"bodyweight", "band", "none", "", "pull_up_bar"}


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


# ══════════════════════════════════════════════════════════════════════
# 处方区间 —— 让模型在合法范围内真正决定「做多少」
# ══════════════════════════════════════════════════════════════════════
#
# ``prescribe`` 给的是「推荐值」，所有人一样；``prescription_bounds`` 给的是
# **允许区间**，模型在区间内自行取值。两者不冲突：
#
#   - 模型可用 → 区间（模型决定 sets / reps / load，体现个体化与当日状态）
#   - 模型不可用 → ``prescribe`` 的推荐值（确定性兜底，行为与旧版一致）
#
# 越界的取值不会被静默丢弃，而是由 ``clamp`` 夹到边界，并把「是否夹过」
# 记进审计 —— 夹紧量本身就是「模型是否守规矩」的指标。

# 动作类型 × 阶段 → (sets_min, sets_max, reps_min, reps_max, load_min, load_max)
# reps 的单位由 ``timed`` 决定：True 为秒，False 为次。
_BOUNDS: Dict[str, Dict[str, Tuple[int, int, int, int, Optional[int], Optional[int]]]] = {
    "Stretch": {
        "*": (1, 2, 20, 45, None, None),
    },
    "Warmup": {
        "*": (1, 2, 8, 15, None, None),
    },
    "Isometric": {
        "cool_down": (1, 2, 20, 45, None, None),
        "*": (2, 4, 25, 60, None, None),
    },
    "Activation": {
        "*": (2, 4, 10, 20, 20, 40),
    },
    "Compound": {
        "main_lifts": (3, 5, 5, 10, 65, 85),
        "accessories": (2, 4, 8, 15, 50, 70),
        "*": (2, 3, 8, 15, 30, 50),
    },
    "Isolation": {
        "cool_down": (1, 2, 20, 45, None, None),
        "main_lifts": (2, 4, 8, 12, 50, 70),
        "*": (2, 4, 8, 15, 40, 65),
    },
}

# 自重主项的次数区间要更高：没有负重可用，只能靠次数与动作难度调强度
_BODYWEIGHT_REPS_OVERRIDE: Dict[str, Tuple[int, int]] = {
    "main_lifts": (8, 20),
    "accessories": (10, 20),
}


@dataclass(frozen=True)
class PrescriptionBounds:
    """一个槽位的合法取值区间。"""

    sets_min: int
    sets_max: int
    reps_min: int
    reps_max: int
    load_min: Optional[int]
    load_max: Optional[int]
    timed: bool
    max_impact: int

    @property
    def unit(self) -> str:
        return "秒" if self.timed else "次"

    def clamp(
        self, sets: Any, reps: str, load_pct: Any
    ) -> Tuple[int, str, Optional[int], bool]:
        """把模型给的取值夹进区间。

        返回 ``(sets, reps, load_pct, clamped)``；``clamped=True`` 表示至少
        有一项越界被夹紧，用于统计「模型自由度用到哪去了」。
        """
        clamped = False

        try:
            s = int(sets)
        except (TypeError, ValueError):
            s = self.sets_min
            clamped = True
        if s < self.sets_min or s > self.sets_max:
            s = min(max(s, self.sets_min), self.sets_max)
            clamped = True

        low, high, unit = parse_reps(reps, default_unit=self.unit)
        if unit != self.unit:
            # 单位不符（把秒写成了次）时以区间为准重建
            low = high = self.reps_min
            clamped = True
        new_low = min(max(low, self.reps_min), self.reps_max)
        new_high = min(max(high, self.reps_min), self.reps_max)
        if new_high < new_low:
            new_high = new_low
        if (new_low, new_high) != (low, high):
            clamped = True

        load: Optional[int] = None
        if self.load_max is None:
            # 该类动作不允许标注负荷，模型给了也丢掉
            if load_pct is not None:
                clamped = True
        else:
            try:
                value = int(load_pct) if load_pct is not None else self.load_min
            except (TypeError, ValueError):
                value = self.load_min or 0
                clamped = True
            assert self.load_min is not None
            if value < self.load_min or value > (self.load_max or value):
                value = min(max(value, self.load_min), self.load_max)
                clamped = True
            load = value

        return s, format_reps(new_low, new_high, self.unit), load, clamped

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sets": [self.sets_min, self.sets_max],
            "reps": [self.reps_min, self.reps_max],
            "reps_unit": self.unit,
            "load_pct": (
                None
                if self.load_max is None
                else [self.load_min, self.load_max]
            ),
            "timed": self.timed,
            "max_impact": self.max_impact,
        }


def prescription_bounds(
    phase: str,
    meta: Dict[str, Any],
    load_cap: Optional[int] = None,
) -> PrescriptionBounds:
    """由动作类型与阶段推导允许区间。

    与 ``prescribe`` 的差别：这里是**边界**，不是取值。确定性后端取推荐值，
    LLM 后端在边界内自行取值。
    """
    etype = str(meta.get("type") or "Compound")
    free = is_bodyweight(meta)
    timed = etype in {"Stretch", "Isometric"} or bool(meta.get("is_timed"))
    max_impact = PHASE_MAX_IMPACT.get(phase, 3)

    table = _BOUNDS.get(etype) or _BOUNDS["Compound"]
    raw = table.get(phase) or table.get("*") or _BOUNDS["Compound"]["*"]
    sets_min, sets_max, reps_min, reps_max, load_min, load_max = raw

    # 自重动作不标负荷百分比（俯卧撑没有 1RM）
    if free:
        load_min, load_max = None, None
        override = _BODYWEIGHT_REPS_OVERRIDE.get(phase)
        if override and etype == "Compound":
            reps_min, reps_max = override

    # 拉伸/等长在 cool_down 一律按秒计，其余按类型判断
    if etype in {"Stretch", "Isometric"}:
        timed = True
    if timed:
        # 计时动作的 reps 区间表示秒数，下界不能太小
        reps_min = max(reps_min, 15)

    if load_max is not None and load_cap is not None:
        load_max = min(load_max, load_cap)
        if load_min is not None:
            load_min = min(load_min, load_max)

    return PrescriptionBounds(
        sets_min=sets_min,
        sets_max=sets_max,
        reps_min=reps_min,
        reps_max=reps_max,
        load_min=load_min,
        load_max=load_max,
        timed=timed,
        max_impact=max_impact,
    )


def parse_reps(reps: Any, default_unit: str = "次") -> Tuple[int, int, str]:
    """解析 "8-10 次" / "30 秒" / 12 为 ``(下界, 上界, 单位)``。"""
    text = str(reps or "").strip()
    unit = "秒" if ("秒" in text or "s" == text.lower()[-1:]) else default_unit
    digits: List[int] = []
    buf = ""
    for ch in text:
        if ch.isdigit():
            buf += ch
        elif buf:
            digits.append(int(buf))
            buf = ""
    if buf:
        digits.append(int(buf))
    if not digits:
        return 0, 0, unit
    if len(digits) == 1:
        return digits[0], digits[0], unit
    return min(digits[0], digits[1]), max(digits[0], digits[1]), unit


def format_reps(low: int, high: int, unit: str) -> str:
    """``(8, 10, "次")`` → ``"8-10 次"``；上下界相同时省略区间。"""
    body = f"{low}" if low == high else f"{low}-{high}"
    return f"{body} {unit}"


__all__ = [
    "PHASE_COUNT",
    "PHASE_MAX_IMPACT",
    "Prescription",
    "PrescriptionBounds",
    "is_bodyweight",
    "prescribe",
    "prescribe_for_phase",
    "prescription_bounds",
    "parse_reps",
    "format_reps",
    "phase_quota",
    "phase_impact_limit",
]
