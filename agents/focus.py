"""训练部位定向：把 ``workout_type`` 编译成候选动作的物理范围。

为什么必须放在这一层：

    ``workout_type`` 此前只是被塞进 payload 和 ``PlanDraft``，从未参与筛选。
    用户说「今天练下肢」，生成结果的主项却是阿诺德推举和双杠臂屈伸 ——
    需求进了系统却没有执行力，等价于没有这个字段。

    做法与禁忌一致：不改提示词去「请求」模型关注部位，而是直接缩小候选集。
    模型看不到上肢动作，就不可能排出上肢计划。

豁免规则：

    ``warm_up`` / ``cool_down`` 不做部位过滤。全身升温与放松本来就不分部位，
    按部位裁剪只会让候选枯竭；而且这两个阶段的动作不会溢到主项段
    （阶段硬过滤 + fallback 只接受未声明 phase 的动作）。

    ``core`` / ``stability`` 等模式视为中性：核心与稳定性训练在任何分化里
    都成立，强行按部位排除反而会让练腿日一个核心动作都不剩。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Set

UPPER_MUSCLES: Set[str] = {
    "Pectorals",
    "Deltoids",
    "Rear Deltoids",
    "Latissimus Dorsi",
    "Rhomboids",
    "Trapezius",
    "Triceps Brachii",
    "Biceps Brachii",
    "Brachialis",
    "Forearm Flexors",
}

LOWER_MUSCLES: Set[str] = {
    "Quadriceps",
    "Gluteus Maximus",
    "Hamstrings",
    "Gastrocnemius",
    "Soleus",
    "Adductors",
    "Abductors",
    "Hip Flexors",
    "Calves",
}

CORE_MUSCLES: Set[str] = {
    "Rectus Abdominis",
    "Obliques",
    "Erector Spinae",
    "Transverse Abdominis",
    "Lower Back",
}

UPPER_PATTERNS: Set[str] = {
    "push_h",
    "push_v",
    "pull_h",
    "pull_v",
    "elbow_flexion",
    "elbow_extension",
    "shrug",
    "wrist",
    "abduction",
}

LOWER_PATTERNS: Set[str] = {
    "squat",
    "hinge",
    "lunge",
    "calf",
    "knee_extension",
    "knee_flexion",
}

PUSH_PATTERNS: Set[str] = {"push_h", "push_v", "elbow_extension"}
PUSH_MUSCLES: Set[str] = {"Pectorals", "Deltoids", "Triceps Brachii"}
PULL_PATTERNS: Set[str] = {"pull_h", "pull_v", "elbow_flexion", "shrug"}
PULL_MUSCLES: Set[str] = {
    "Latissimus Dorsi",
    "Rhomboids",
    "Trapezius",
    "Biceps Brachii",
    "Brachialis",
    "Rear Deltoids",
    "Forearm Flexors",
}

# 中性模式：任何分化都保留（核心、稳定、活动度）
NEUTRAL_PATTERNS: Set[str] = {"core", "stability", "mobility"}

# 不做部位过滤的阶段：全身升温与放松
FOCUS_EXEMPT_PHASES: frozenset = frozenset({"warm_up", "cool_down"})

_SUPPORTED = {"full_body", "upper_body", "lower_body", "push", "pull"}


def normalize_workout_type(workout_type: Optional[str]) -> str:
    key = str(workout_type or "").strip().lower()
    return key if key in _SUPPORTED else "full_body"


def _matches(meta: Dict[str, Any], focus: str) -> bool:
    muscle = str(meta.get("target_muscle") or "").strip()
    pattern = str(meta.get("motion_pattern") or "").strip().lower()

    if pattern in NEUTRAL_PATTERNS or muscle in CORE_MUSCLES:
        return True

    if focus in ("lower_body", "upper_body"):
        # 目标肌肉明确时**以肌肉为准**，动作模式只作兜底。
        # 反例：侧平举与蚌式开合的 motion_pattern 都是 abduction，
        # 只按模式判会把侧平举放进练腿日。
        if muscle in UPPER_MUSCLES:
            return focus == "upper_body"
        if muscle in LOWER_MUSCLES:
            return focus == "lower_body"
        return pattern in (LOWER_PATTERNS if focus == "lower_body" else UPPER_PATTERNS)

    if focus == "push":
        return pattern in PUSH_PATTERNS or muscle in PUSH_MUSCLES
    if focus == "pull":
        return pattern in PULL_PATTERNS or muscle in PULL_MUSCLES
    return True


def resolve_focus(
    workout_type: Optional[str],
    exercise_index: Dict[int, Dict[str, Any]],
) -> Optional[frozenset]:
    """返回该训练类型允许的动作 ID 集合；``None`` 表示不限制（全身）。"""
    focus = normalize_workout_type(workout_type)
    if focus == "full_body":
        return None
    ids: Iterable[int] = (
        eid for eid, meta in exercise_index.items() if _matches(meta, focus)
    )
    return frozenset(ids)


__all__ = [
    "FOCUS_EXEMPT_PHASES",
    "NEUTRAL_PATTERNS",
    "normalize_workout_type",
    "resolve_focus",
]
