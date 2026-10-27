# -*- coding: utf-8 -*-
"""动作库视图 —— 全量目录，不做任何裁剪。

与 ``RiskGrammar`` 的分工（v3 起）：

    RiskGrammar   旧的可生成空间：候选硬裁剪 + enum 掩码 + 区间夹紧。
                  现在只服务于**降级后端**（没配 key 时的确定性生成）。
    ExerciseCatalog 新的可生成空间：**整库**。所有动作都下发给模型，
                  「哪些动作不适合这个人」由 Agent 判断并由 Agent 审查裁决。

为什么拆出来
------------
中间那层规则拦截被移除后，Agent 之间的数据流变成「档案 → 全量目录 → 计划 →
会审」。目录只回答「世界上有哪些动作、它们长什么样」，不回答「你能做哪些」，
这样生成端看到的信息就不再被上游规则预先剪掉 —— 模型第一次拥有完整的视野。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from agents.contracts import PHASES
from agents.prescription import is_bodyweight, prescription_bounds

CATALOG_VERSION = "catalog/1.0.0"

# 兼容路径：动作缺 ``phase`` 字段时用类型推断它属于哪个阶段。
# 只为兼容未升级的历史动作库，新数据一律显式声明 phase。
PHASE_PREFERRED_TYPES: Dict[str, Tuple[str, ...]] = {
    "warm_up": ("Warmup", "Mobility", "Isolation", "Isometric"),
    "activation": ("Activation", "Mobility", "Isometric", "Isolation"),
    "main_lifts": ("Compound",),
    "accessories": ("Isolation", "Compound", "Activation"),
    "cool_down": ("Stretch", "Isometric", "Isolation"),
}

# 自重/弹力带动作不标强度百分比：俯卧撑没有 1RM 可言
FREE_EQUIPMENT = frozenset({"bodyweight", "band", "none", "", "pull_up_bar"})


def phases_of(meta: Dict[str, Any]) -> Tuple[str, ...]:
    """读取动作的阶段归属；缺字段时按类型推断。"""
    raw = meta.get("phase")
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, (list, tuple)):
        return tuple(str(p) for p in raw)
    etype = str(meta.get("type") or "")
    return tuple(p for p, types in PHASE_PREFERRED_TYPES.items() if etype in types)


class ExerciseCatalog:
    """整库视图：全量 ID + 紧凑元信息，供生成端与审查端共享。"""

    version = CATALOG_VERSION

    def __init__(self, exercise_db: Sequence[Dict[str, Any]]) -> None:
        self.exercise_db = [ex for ex in exercise_db if "id" in ex]
        self.index: Dict[int, Dict[str, Any]] = {
            int(ex["id"]): ex for ex in self.exercise_db
        }
        self.ids: Tuple[int, ...] = tuple(sorted(self.index))

    # ── 基础查询 ──────────────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self.ids)

    def meta(self, exercise_id: int) -> Dict[str, Any]:
        return self.index.get(int(exercise_id)) or {}

    def has(self, exercise_id: int) -> bool:
        return int(exercise_id) in self.index

    def name(self, exercise_id: int) -> str:
        meta = self.meta(exercise_id)
        return str(meta.get("name_zh") or meta.get("name") or f"#{exercise_id}")

    def impact_of(self, exercise_id: int) -> int:
        return int(self.meta(exercise_id).get("risk_level", 1))

    def phases_of(self, exercise_id: int) -> Tuple[str, ...]:
        return phases_of(self.meta(exercise_id))

    def patterns(self) -> List[str]:
        return sorted(
            {
                str(ex.get("motion_pattern") or "").strip().lower()
                for ex in self.exercise_db
                if ex.get("motion_pattern")
            }
        )

    # ── 下发给模型的紧凑行 ────────────────────────────────────────────────
    def rows(self, prefs: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """全量动作行，包含生成端做决策所需的最小信息集。

        与旧版 ``phase_candidates`` 的差别：不再按阶段拆开（那本身就是一层
        硬过滤），而是每条动作自带 ``phases`` 字段，由模型自己决定放哪里。
        """
        liked, disliked_patterns, disliked_names = _split_prefs(prefs)
        rows: List[Dict[str, Any]] = []
        for eid in self.ids:
            meta = self.meta(eid)
            pattern = str(meta.get("motion_pattern") or "").strip().lower()
            name_zh = str(meta.get("name_zh") or meta.get("name") or "")
            row: Dict[str, Any] = {
                "exercise_id": eid,
                "name": name_zh,
                "type": meta.get("type", ""),
                "impact": int(meta.get("risk_level", 1)),
                "phases": list(self.phases_of(eid)),
            }
            if pattern:
                row["pattern"] = pattern
            # 只在非默认时出现，压住 payload 体积（77 行里大半为 false）
            if is_bodyweight(meta):
                row["bodyweight"] = True
            if bool(meta.get("is_timed")) or str(meta.get("type")) in {"Stretch", "Isometric"}:
                row["timed"] = True
            gear = [
                str(g).strip().lower()
                for g in (meta.get("required_equipment") or [])
                if str(g).strip().lower() not in FREE_EQUIPMENT
            ]
            if gear:
                row["gear"] = gear
            # 偏好只是标签：不喜欢 ≠ 不能做，模型据此在同等条件下取舍
            if (pattern and pattern in disliked_patterns) or name_zh.lower() in disliked_names \
                    or str(meta.get("name", "")).lower() in disliked_names:
                row["disliked"] = True
            elif pattern and pattern in liked:
                row["liked"] = True
            rows.append(row)
        return rows

    def reference_doses(self) -> List[Dict[str, Any]]:
        """各「阶段 × 类型 × 自重」的**参考**剂量区间。

        注意：这是参考，不是边界。生成端给出区间外的取值不会再被夹紧，
        只会由审查 Agent 判断是否合理。
        """
        seen: Dict[Tuple[str, str, bool], Dict[str, Any]] = {}
        for eid in self.ids:
            meta = self.meta(eid)
            etype = str(meta.get("type") or "Compound")
            free = is_bodyweight(meta)
            for phase in self.phases_of(eid) or PHASES:
                key = (phase, etype, free)
                if key in seen:
                    continue
                b = prescription_bounds(phase, meta, None)
                seen[key] = {
                    "phase": phase,
                    "type": etype,
                    "bodyweight": free,
                    **b.to_dict(),
                }
        return list(seen.values())

    # ── 结构性信息（非安全判定）────────────────────────────────────────────
    def slot_schema(self) -> Dict[str, Any]:
        """下发给模型的输出形状。

        刻意**不含 enum**：取值的合法与否不在这里决定 —— 那正是本次改造
        移除的那层东西。schema 只描述形状，不限制内容。
        """
        item = {
            "type": "object",
            "properties": {
                "exercise_id": {"type": "integer", "minimum": 1},
                "sets": {"type": "integer", "minimum": 1},
                "reps": {"type": "string"},
                "load_pct": {"type": ["integer", "null"]},
                "rest_seconds": {"type": ["integer", "null"]},
                "note": {"type": "string"},
            },
            "required": ["exercise_id"],
            "additionalProperties": False,
        }
        return {
            "name": "workout_plan",
            "strict": False,
            "schema": {
                "type": "object",
                "properties": {phase: {"type": "array", "items": item} for phase in PHASES},
                "required": list(PHASES),
                "additionalProperties": False,
            },
        }

    def phase_coverage(self) -> Dict[str, int]:
        return {
            phase: sum(1 for eid in self.ids if phase in self.phases_of(eid))
            for phase in PHASES
        }

    def stats(self) -> Dict[str, Any]:
        return {
            "catalog_version": self.version,
            "total_exercises": len(self.ids),
            "phase_coverage": self.phase_coverage(),
            "patterns": len(self.patterns()),
        }


def _split_prefs(
    prefs: Optional[Dict[str, Any]],
) -> Tuple[set, set, set]:
    if not prefs:
        return set(), set(), set()

    def _norm(values: Iterable[Any]) -> set:
        return {str(v).strip().lower() for v in (values or []) if str(v).strip()}

    return (
        _norm(prefs.get("liked_patterns")),
        _norm(prefs.get("disliked_patterns")),
        _norm(prefs.get("disliked_exercises")),
    )


def build_catalog(exercise_db: Sequence[Dict[str, Any]]) -> ExerciseCatalog:
    return ExerciseCatalog(exercise_db)


__all__ = [
    "CATALOG_VERSION",
    "ExerciseCatalog",
    "build_catalog",
    "phases_of",
    "PHASE_PREFERRED_TYPES",
    "FREE_EQUIPMENT",
]
