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
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agents.contracts import PHASES, RiskProfile, Slot, Violation

GRAMMAR_VERSION = "grammar/1.0.0"

# 严重程度 → 该关节允许的最大 impact（与 RiskAssessmentEngine 阈值严格对齐）
# HIGH   : risk_level >= 3 禁止 → 允许 <=2
# MEDIUM : risk_level >= 4 禁止 → 允许 <=3
# LOW    : risk_level >= 5 禁止 → 允许 <=4
SEVERITY_JOINT_CAP: Dict[str, int] = {"high": 2, "medium": 3, "low": 4}

# 各阶段优先使用的动作类型（仅用于候选排序，不作为硬约束）
PHASE_PREFERRED_TYPES: Dict[str, Tuple[str, ...]] = {
    "warm_up": ("Isolation", "Isometric"),
    "activation": ("Isolation", "Isometric"),
    "main_lifts": ("Compound",),
    "accessories": ("Isolation", "Compound"),
    "cool_down": ("Isometric", "Isolation"),
}


def joint_cap_for_severity(severity: str) -> int:
    return SEVERITY_JOINT_CAP.get((severity or "").lower(), 5)


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

    def candidates(
        self,
        phase: str,
        exclude: Sequence[int] = (),
        rng: Optional[random.Random] = None,
    ) -> List[int]:
        """返回该阶段可用动作 ID 列表 —— 禁忌动作在此处已被物理移除。"""
        banned = set(exclude)
        preferred = PHASE_PREFERRED_TYPES.get(phase, ())
        pool: List[int] = []
        fallback: List[int] = []
        for eid in self.allowed_ids:
            if eid in banned:
                continue
            meta = self.index.get(eid)
            if not meta:
                continue
            (pool if meta.get("type") in preferred else fallback).append(eid)
        if rng is not None:
            rng.shuffle(pool)
            rng.shuffle(fallback)
        return pool + fallback if pool else fallback

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
        return None

    def validate_draft_slots(self, slots: Sequence[Tuple[str, Slot]]) -> List[Violation]:
        out: List[Violation] = []
        for phase, slot in slots:
            v = self.validate(slot, phase)
            if v is not None:
                out.append(v)
        return out

    # ── 解码约束：发给模型的结构化输出 schema ─────────────────────────────
    def slot_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "exercise_id": {"type": "integer", "enum": list(self.allowed_ids)},
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
        slot = self.slot_schema()
        props: Dict[str, Any] = {}
        for phase in PHASES:
            lo, hi = (phase_limits or {}).get(phase, (1, 6))
            props[phase] = {
                "type": "array",
                "items": slot,
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
