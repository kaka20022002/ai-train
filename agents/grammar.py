"""风险条件约束解码（Constrained Decoding over Risk Grammar）。

核心命题：把「禁忌动作倾向于不被生成」升级为「禁忌动作不可能被生成」。

实现分三层，层层兜底：

1. **候选集硬裁剪**（``candidates``）：生成器只能从 ``allowed_ids`` 采样，
   采样空间里根本不存在禁忌动作。
2. **Schema 约束**（``slot_schema`` / ``plan_schema``）：下发给支持结构化输出的
   模型时，``exercise_id`` 的 enum 只包含允许 ID —— 解码阶段即被 mask，
   模型无法输出 enum 之外的值。
3. **事后校验**（``validate``）：对任何来源（LLM 幻觉、缓存、外部脚本）的槽位
   做谓词校验，返回结构化违规码。前两层被绕过时由这层兜住。

三层共用同一份 ``RiskProfile``，避免规则出现第二份真相。

v2 变更：候选集从「按动作类型排序、取前 N 个」改为「按 ``phase`` 字段硬过滤」。
原实现的 ``PHASE_PREFERRED_TYPES`` 只是把偏好类型排到前面，排在后面的类型
仍会追加进结果，实际等于没过滤 —— 所以热身段能抽到杠铃弯举。现在每个阶段
只保留 ``phase`` 字段显式声明属于该阶段的动作，且 schema 的 enum 也按阶段
收敛，使「阶段不匹配的动作」同样不可能被输出。
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agents.contracts import PHASES, RiskProfile, Slot, Violation
from agents.prescription import (
    PrescriptionBounds,
    is_bodyweight,
    parse_reps,
    prescription_bounds,
)

GRAMMAR_VERSION = "grammar/2.1.0"

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
        （``avoid_patterns``，来自病历语义）→ **阶段归属**。禁忌动作在此处
        已被物理移除。
        """
        banned = set(exclude)
        avoid = set(self.profile.avoid_patterns)
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
            phases = phases_of(meta)
            if phases:
                in_phase = phase in phases
            else:
                in_phase = meta.get("type") in PHASE_PREFERRED_TYPES.get(phase, ())
            (strict if in_phase else fallback).append(eid)

        if rng is not None:
            rng.shuffle(strict)
            rng.shuffle(fallback)
        return strict + fallback if allow_fallback else strict

    def bounds(self, phase: str, exercise_id: int) -> PrescriptionBounds:
        """该动作在该阶段的合法取值区间。"""
        meta = self.index.get(int(exercise_id)) or {}
        return prescription_bounds(phase, meta, self.profile.load_pct_cap)

    def prescription_rules(self) -> List[Dict[str, Any]]:
        """把各阶段候选归纳成「类型 → 区间」表，供模型参考取值。

        只出现该阶段真实存在的类型，最多十几条，避免逐动作重复下发。
        """
        seen: Dict[Tuple[str, str, bool], Dict[str, Any]] = {}
        for phase in PHASES:
            for eid in self.phase_allowed_ids(phase):
                meta = self.index.get(eid) or {}
                etype = str(meta.get("type") or "Compound")
                free = is_bodyweight(meta)
                key = (phase, etype, free)
                if key in seen:
                    continue
                b = prescription_bounds(phase, meta, self.profile.load_pct_cap)
                seen[key] = {
                    "phase": phase,
                    "type": etype,
                    "bodyweight": free,
                    **b.to_dict(),
                }
        return list(seen.values())

    def phase_coverage(self, exclude: Sequence[int] = ()) -> Dict[str, int]:
        """各阶段严格候选数量 —— 用于诊断「某阶段是否被档案掏空」。"""
        return {phase: len(self.candidates(phase, exclude=exclude)) for phase in PHASES}

    def impact_of(self, exercise_id: int) -> int:
        meta = self.index.get(int(exercise_id)) or {}
        return int(meta.get("risk_level", 1))

    # ── 谓词校验 ──────────────────────────────────────────────────────────
    def validate(self, slot: Slot, phase: str = "") -> Optional[Violation]:
        eid = slot.exercise_id
        meta = self.index.get(eid)
        if meta is None:
            return Violation("UNKNOWN_ID", eid, phase, "ID 不在知识库")
        if eid not in self._allowed_set:
            return Violation(
                "FORBIDDEN_ID", eid, phase,
                self.profile.forbidden_reasons.get(eid, "命中禁忌谓词"),
            )
        impact = int(meta.get("risk_level", 1))
        if impact > self.profile.impact_ceiling:
            return Violation("IMPACT_CEILING", eid, phase, f"impact={impact} > {self.profile.impact_ceiling}")
        for joint in meta.get("involved_joints", []) or []:
            cap = self.profile.joint_caps.get(str(joint).lower())
            if cap is not None and impact > cap:
                return Violation(
                    "JOINT_CAP", eid, phase,
                    f"{joint} 上限 {cap}，动作 impact={impact}",
                )
        if (
            slot.load_pct is not None
            and self.profile.load_pct_cap is not None
            and slot.load_pct > self.profile.load_pct_cap
        ):
            return Violation(
                "LOAD_PCT", eid, phase,
                f"load_pct={slot.load_pct} > {self.profile.load_pct_cap}",
            )
        # 处方区间校验：模型有取值自由，但只能在区间内取。
        # 阶段为空时无法确定区间（同一个动作在不同阶段区间不同），跳过。
        if phase:
            b = self.bounds(phase, eid)
            if slot.sets < b.sets_min or slot.sets > b.sets_max:
                return Violation(
                    "PRESCRIPTION_RANGE", eid, phase,
                    f"sets={slot.sets} 超出 [{b.sets_min},{b.sets_max}]",
                )
            low, high, unit = parse_reps(slot.reps, default_unit=b.unit)
            if unit != b.unit or low < b.reps_min or high > b.reps_max:
                return Violation(
                    "PRESCRIPTION_RANGE", eid, phase,
                    f"reps={slot.reps} 超出 [{b.reps_min},{b.reps_max}] {b.unit}",
                )
            if slot.load_pct is not None:
                if b.load_max is None:
                    return Violation(
                        "PRESCRIPTION_RANGE", eid, phase,
                        f"该动作不应标注负荷，却给了 load_pct={slot.load_pct}",
                    )
                if slot.load_pct < (b.load_min or 0) or slot.load_pct > b.load_max:
                    return Violation(
                        "PRESCRIPTION_RANGE", eid, phase,
                        f"load_pct={slot.load_pct} 超出 [{b.load_min},{b.load_max}]",
                    )
        return None

    def validate_draft_slots(self, slots: Sequence[Tuple[str, Slot]]) -> List[Violation]:
        out: List[Violation] = []
        for phase, slot in slots:
            v = self.validate(slot, phase)
            if v is not None:
                out.append(v)
        return out

    # ── 解码约束：发给模型的结构化输出 schema ─────────────────────────────
    def phase_allowed_ids(self, phase: str) -> Tuple[int, ...]:
        """该阶段的可解码 ID 集合。

        严格候选为空时退回全局允许集 —— enum 不能是空数组（schema 非法），
        而退回的仍然是 ``allowed_ids``，禁忌动作依旧不可能出现。
        """
        ids = self.candidates(phase)
        return tuple(ids) if ids else self.allowed_ids

    def slot_schema(self, phase: Optional[str] = None) -> Dict[str, Any]:
        ids = self.phase_allowed_ids(phase) if phase else self.allowed_ids
        return {
            "type": "object",
            "properties": {
                "exercise_id": {"type": "integer", "enum": list(ids)},
                "sets": {"type": "integer", "minimum": 1, "maximum": 6},
                "reps": {"type": "string"},
                "load_pct": {"type": ["integer", "null"], "minimum": 0, "maximum": 100},
                "impact": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["exercise_id", "sets", "reps", "impact"],
            "additionalProperties": False,
        }

    def plan_schema(
        self,
        phase_limits: Optional[Dict[str, Tuple[int, int]]] = None,
    ) -> Dict[str, Any]:
        """整份计划的解码 schema。

        每个阶段的 ``exercise_id`` enum 各自收敛到该阶段的候选集 —— 模型不仅
        无法输出禁忌动作，也无法把「热身动作」塞进主项段。
        """
        props: Dict[str, Any] = {}
        for phase in PHASES:
            lo, hi = (phase_limits or {}).get(phase, (1, 6))
            props[phase] = {
                "type": "array",
                "items": self.slot_schema(phase=phase),
                "minItems": lo,
                "maxItems": hi,
            }
        return {
            "name": "workout_plan_draft",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": props,
                "required": list(PHASES),
                "additionalProperties": False,
            },
        }

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
