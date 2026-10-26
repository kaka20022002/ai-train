"""降级后端的候选采样（Risk Grammar）。

v3 起，这个模块**不再参与主路径**。中间那层「约束解码」被移除了：
模型拿到全量动作库、自由出计划，安全性由审查 Agent 事后裁决。
本模块现在只服务一种场景 —— 没有配置模型时的确定性生成：那时没有任何
Agent 能做判断，只能靠一份可复现的规则采样。

保留的能力（仅降级后端）：
    candidates(phase)   该阶段的候选集：档案禁忌 / 模式禁忌 / 部位定向 / 阶段归属
    impact_of(id)       动作冲击等级
    stats()             屏蔽比例，供审计

已移除的能力（正是这次改造拆掉的东西）：
    slot_schema / plan_schema   enum 掩码，让禁忌 ID 在解码期不可能出现
    validate / bounds           事后谓词校验与处方区间夹紧

为什么移除后仍然安全：判定权移交给 safety_agent —— 它拿到计划、病历原文与
基线命中项，由审查模型给出最终结论；判 fail 就把违规清单回灌给生成 Agent
重写。规则不再是判决者，只是提示者。
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agents.contracts import PHASES, RiskProfile
from agents.focus import (
    FOCUS_EXEMPT_PHASES,
    normalize_workout_type,
    resolve_focus,
)


GRAMMAR_VERSION = "grammar/2.2.0"

# 严重程度 → 该关节允许的最大 impact（与 RiskAssessmentEngine 阈值严格对齐）
# HIGH   : risk_level >= 3 禁止 → 允许 <=2
# MEDIUM : risk_level >= 4 禁止 → 允许 <=3
# LOW    : risk_level >= 5 禁止 → 允许 <=4
SEVERITY_JOINT_CAP: Dict[str, int] = {"high": 2, "medium": 3, "low": 4}

# 兼容路径：仅当动作缺 ``phase`` 字段时，用类型偏好推断它属于哪个阶段。
# 新数据一律显式声明 phase，这条路径只为兼容未升级的历史动作库。
PHASE_PREFERRED_TYPES: Dict[str, Tuple[str, ...]] = {
    "warm_up": ("Warmup", "Mobility", "Isolation", "Isometric"),
    "activation": ("Activation", "Mobility", "Isometric", "Isolation"),
    "main_lifts": ("Compound",),
    "accessories": ("Isolation", "Compound", "Activation"),
    "cool_down": ("Stretch", "Isometric", "Isolation"),
}


def joint_cap_for_severity(severity: str) -> int:
    return SEVERITY_JOINT_CAP.get((severity or "").lower(), 5)


def phases_of(meta: Dict[str, Any]) -> Tuple[str, ...]:
    """读取动作的阶段归属；缺字段时回退到类型推断。"""
    raw = meta.get("phase")
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, (list, tuple)):
        return tuple(str(p) for p in raw)
    return ()


class RiskGrammar:
    """用户专属的加权文法：既回答「能不能生成」，也限定「怎么生成」。"""

    version = GRAMMAR_VERSION

    def __init__(
        self,
        profile: RiskProfile,
        exercise_index: Dict[int, Dict[str, Any]],
    ) -> None:
        self.profile = profile
        self.index = exercise_index
        self.allowed_ids: Tuple[int, ...] = profile.allowed_ids
        self._allowed_set = frozenset(self.allowed_ids)

        # 部位定向：把 workout_type 变成候选集的物理范围。
        # 与 allow 集取交集 —— 部位范围不能成为越过禁忌的通道。
        self.focus = normalize_workout_type((profile.user_context or {}).get("workout_type"))
        scoped = resolve_focus(self.focus, exercise_index)
        self.focus_ids: Optional[frozenset] = (
            None if scoped is None else frozenset(scoped) & self._allowed_set
        )

    # ── 候选集 ────────────────────────────────────────────────────────────
    def is_allowed(self, exercise_id: int) -> bool:
        return int(exercise_id) in self._allowed_set

    def phase_matches(self, exercise_id: int, phase: str) -> bool:
        """动作是否声明归属该阶段（缺 phase 字段时退化为类型推断）。"""
        meta = self.index.get(int(exercise_id)) or {}
        phases = phases_of(meta)
        if phases:
            return phase in phases
        return meta.get("type") in PHASE_PREFERRED_TYPES.get(phase, ())

    def candidates(
        self,
        phase: str,
        exclude: Sequence[int] = (),
        rng: Optional[random.Random] = None,
        allow_fallback: bool = False,
    ) -> List[int]:
        """返回该阶段可用动作 ID 列表。

        默认只返回 ``phase`` 字段声明属于该阶段的动作（硬过滤）；
        ``allow_fallback=True`` 时把其余允许动作追加在末尾，供候选不足时兜底 ——
        兜底也只在 ``allowed_ids`` 内部，禁忌动作永不出现在任何一档。

        三层裁剪依次生效：**档案禁忌**（``allowed_ids``）→ **模式禁忌**
        （``avoid_patterns``，来自病历语义）→ **部位定向**
        （``workout_type``）→ **阶段归属**。禁忌动作在此处已被物理移除。

        ``allow_fallback`` 只接受「类型与目标阶段偏好相容」的动作：
        宁可少一个动作，也不把热身或拉伸塞进主项段。
        """
        banned = set(exclude)
        avoid = set(self.profile.avoid_patterns)
        apply_focus = self.focus_ids is not None and phase not in FOCUS_EXEMPT_PHASES
        desired_types = PHASE_PREFERRED_TYPES.get(phase, ())
        strict: List[int] = []
        fallback: List[int] = []
        for eid in self.allowed_ids:
            if eid in banned:
                continue
            meta = self.index.get(eid)
            if not meta:
                continue
            # 模式禁忌：整类动作模式被病历排除（如深屈膝），比逐个动作更粗、
            # 也更能覆盖「规则表按关节映射时漏掉的同族动作」。
            if avoid and str(meta.get("motion_pattern") or "").lower() in avoid:
                continue
            # 部位定向：练腿日看不到上肢动作（热身/放松阶段豁免）
            if apply_focus and eid not in self.focus_ids:  # type: ignore[operator]
                continue
            phases = phases_of(meta)
            if phases:
                in_phase = phase in phases
            else:
                in_phase = meta.get("type") in desired_types
            if in_phase:
                strict.append(eid)
            elif allow_fallback and (not phases or meta.get("type") in desired_types):
                fallback.append(eid)

        if rng is not None:
            rng.shuffle(strict)
            rng.shuffle(fallback)
        return strict + fallback if allow_fallback else strict

    def phase_coverage(self, exclude: Sequence[int] = ()) -> Dict[str, int]:
        """各阶段严格候选数量 —— 用于诊断「某阶段是否被档案掏空」。"""
        return {phase: len(self.candidates(phase, exclude=exclude)) for phase in PHASES}

    def impact_of(self, exercise_id: int) -> int:
        meta = self.index.get(int(exercise_id)) or {}
        return int(meta.get("risk_level", 1))

    # ── 统计 ──────────────────────────────────────────────────────────────
    def stats(self) -> Dict[str, Any]:
        total = len(self.index)
        allowed = len(self.allowed_ids)
        return {
            "grammar_version": self.version,
            "profile_hash": self.profile.profile_hash,
            "total_exercises": total,
            "allowed": allowed,
            "masked": total - allowed,
            "mask_ratio": round((total - allowed) / total, 4) if total else 0.0,
        }


def compile_risk_grammar(
    profile: RiskProfile,
    exercise_index: Dict[int, Dict[str, Any]],
) -> RiskGrammar:
    """把风险档案编译成文法。纯函数，可复现。"""
    return RiskGrammar(profile, exercise_index)


def build_exercise_index(exercise_db: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    return {int(ex["id"]): ex for ex in exercise_db if "id" in ex}
