"""Hybrid training-program recommender.

This module adapts the plan-level recommender from the
``training-plan-recommendation`` project to the ``ai-train`` domain.

The recommender never bypasses the existing safety layer:

1. Equipment-incompatible templates are removed.
2. The profile/content score captures goal, experience and schedule fit.
3. The behaviour score uses completion, RPE and actual training cadence.
4. A small population prior reflects which plan shapes are already adopted.

The final score is intentionally explainable so the API can show users why a
plan was recommended.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple


GOAL_LABELS = {
    "strength": "力量",
    "hypertrophy": "增肌",
    "general_fitness": "综合体能",
}

SPLIT_LABELS = {
    "full_body": "全身训练",
    "upper_lower": "上下肢分化",
    "push_pull_legs": "推拉腿分化",
}

LEVEL_LABELS = {
    "beginner": "初级",
    "intermediate": "中级",
    "advanced": "高级",
}

EQUIPMENT_LABELS = {
    "bodyweight": "自重",
    "barbell": "杠铃",
    "dumbbell": "哑铃",
    "machine": "固定器械",
    "cable": "龙门/绳索",
    "kettlebell": "壶铃",
    "resistance_band": "弹力带",
    "bench": "训练凳",
    "pull_up_bar": "单杠",
    "squat_rack": "深蹲架",
}

_LEVEL_INDEX = {"beginner": 1, "intermediate": 2, "advanced": 3}
_GOAL_ALIASES = {
    "fat_loss": "general_fitness",
    "weight_loss": "general_fitness",
    "endurance": "general_fitness",
    "fitness": "general_fitness",
    "general": "general_fitness",
}


@dataclass(frozen=True)
class ProgramTemplate:
    template_id: str
    name: str
    description: str
    goal: str
    split_type: str
    total_weeks: int
    sessions_per_week: int
    difficulty: str
    estimated_duration_minutes: int
    focus_areas: Tuple[str, ...]
    required_equipment: Tuple[str, ...] = ()
    popularity_prior: float = 0.55
    low_impact: bool = False


# The catalogue contains only configurations supported by ProgramGeneratorService.
PROGRAM_CATALOG: Tuple[ProgramTemplate, ...] = (
    ProgramTemplate(
        template_id="strength_ul_4d",
        name="力量进阶 · 上下肢 4 日",
        description="覆盖全身主要动作模式，以复合动作和渐进超负荷为核心，适合已有训练基础的用户。",
        goal="strength",
        split_type="upper_lower",
        total_weeks=6,
        sessions_per_week=4,
        difficulty="intermediate",
        estimated_duration_minutes=65,
        focus_areas=("复合力量", "上下肢分化", "渐进超负荷"),
        popularity_prior=0.92,
    ),
    ProgramTemplate(
        template_id="strength_foundation_3d",
        name="力量起步 · 全身 3 日",
        description="用较低训练频率建立动作技术和基础力量，留出充分的恢复时间。",
        goal="strength",
        split_type="full_body",
        total_weeks=4,
        sessions_per_week=3,
        difficulty="beginner",
        estimated_duration_minutes=50,
        focus_areas=("动作技术", "基础力量", "规律训练"),
        popularity_prior=0.82,
    ),
    ProgramTemplate(
        template_id="strength_peak_4d",
        name="力量峰值 · 上下肢 4 日",
        description="面向高阶训练者的高强度周期，包含更大比例的复合动作与峰值周。",
        goal="strength",
        split_type="upper_lower",
        total_weeks=8,
        sessions_per_week=4,
        difficulty="advanced",
        estimated_duration_minutes=75,
        focus_areas=("最大力量", "峰值周期", "高训练负荷"),
        required_equipment=("barbell", "squat_rack", "bench"),
        popularity_prior=0.56,
    ),
    ProgramTemplate(
        template_id="hypertrophy_ul_4d",
        name="增肌进阶 · 上下肢 4 日",
        description="平衡上下肢训练量，以中等次数和稳定容量促进肌肉增长。",
        goal="hypertrophy",
        split_type="upper_lower",
        total_weeks=8,
        sessions_per_week=4,
        difficulty="intermediate",
        estimated_duration_minutes=65,
        focus_areas=("肌肥大", "训练容量", "上下肢均衡"),
        required_equipment=("dumbbell", "bench"),
        popularity_prior=0.88,
    ),
    ProgramTemplate(
        template_id="hypertrophy_full_3d",
        name="增肌基础 · 全身 3 日",
        description="每周三次全身训练，优先提高动作熟练度与主要肌群训练量。",
        goal="hypertrophy",
        split_type="full_body",
        total_weeks=6,
        sessions_per_week=3,
        difficulty="intermediate",
        estimated_duration_minutes=55,
        focus_areas=("全身增肌", "中等容量", "动作熟练度"),
        popularity_prior=0.74,
    ),
    ProgramTemplate(
        template_id="hypertrophy_ppl_5d",
        name="增肌强化 · 推拉腿 5 日",
        description="采用推拉腿分化提高单肌群训练容量，适合恢复能力较好的进阶用户。",
        goal="hypertrophy",
        split_type="push_pull_legs",
        total_weeks=8,
        sessions_per_week=5,
        difficulty="advanced",
        estimated_duration_minutes=75,
        focus_areas=("推拉腿分化", "高容量", "肌群强化"),
        required_equipment=("barbell", "bench", "pull_up_bar"),
        popularity_prior=0.64,
    ),
    ProgramTemplate(
        template_id="general_balance_3d",
        name="综合体能 · 全身 3 日",
        description="兼顾力量、动作稳定和日常体能，训练压力适中，适合长期坚持。",
        goal="general_fitness",
        split_type="full_body",
        total_weeks=6,
        sessions_per_week=3,
        difficulty="intermediate",
        estimated_duration_minutes=50,
        focus_areas=("综合体能", "动作稳定", "长期坚持"),
        popularity_prior=0.86,
    ),
    ProgramTemplate(
        template_id="general_busy_2d",
        name="忙碌日程 · 全身 2 日",
        description="每周两次、每次约 40 分钟的高效率全身训练，适合日程紧张阶段。",
        goal="general_fitness",
        split_type="full_body",
        total_weeks=4,
        sessions_per_week=2,
        difficulty="beginner",
        estimated_duration_minutes=40,
        focus_areas=("低频率", "高效率", "建立习惯"),
        popularity_prior=0.71,
    ),
    ProgramTemplate(
        template_id="general_reentry_3d",
        name="低负荷重启 · 全身 3 日",
        description="降低单次训练负荷，强调动作控制、关节活动和稳定恢复。",
        goal="general_fitness",
        split_type="full_body",
        total_weeks=4,
        sessions_per_week=3,
        difficulty="beginner",
        estimated_duration_minutes=38,
        focus_areas=("低负荷", "恢复训练", "动作控制"),
        popularity_prior=0.67,
        low_impact=True,
    ),
    ProgramTemplate(
        template_id="home_bodyweight_3d",
        name="居家自重 · 全身 3 日",
        description="不依赖器械的全身训练方案，通过动作进阶和训练量变化持续提高。",
        goal="general_fitness",
        split_type="full_body",
        total_weeks=4,
        sessions_per_week=3,
        difficulty="beginner",
        estimated_duration_minutes=35,
        focus_areas=("纯自重", "居家训练", "动作进阶"),
        popularity_prior=0.79,
        low_impact=True,
    ),
    ProgramTemplate(
        template_id="home_dumbbell_4d",
        name="家庭哑铃 · 上下肢 4 日",
        description="使用哑铃与训练凳完成上下肢分化，在有限器材下保持足够训练量。",
        goal="hypertrophy",
        split_type="upper_lower",
        total_weeks=6,
        sessions_per_week=4,
        difficulty="intermediate",
        estimated_duration_minutes=48,
        focus_areas=("家庭训练", "哑铃增肌", "上下肢分化"),
        required_equipment=("dumbbell", "bench"),
        popularity_prior=0.77,
    ),
    ProgramTemplate(
        template_id="general_ul_4d",
        name="综合进阶 · 上下肢 4 日",
        description="兼顾力量与体能的四日分化方案，适合希望稳定提升整体训练表现的用户。",
        goal="general_fitness",
        split_type="upper_lower",
        total_weeks=8,
        sessions_per_week=4,
        difficulty="intermediate",
        estimated_duration_minutes=60,
        focus_areas=("综合表现", "上下肢分化", "稳定进阶"),
        popularity_prior=0.73,
    ),
)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _normalise_goal(goal: Optional[str]) -> str:
    value = (goal or "general_fitness").lower()
    value = _GOAL_ALIASES.get(value, value)
    return value if value in GOAL_LABELS else "general_fitness"


def _level_value(level: Optional[str]) -> int:
    return _LEVEL_INDEX.get((level or "beginner").lower(), 1)


def _goal_similarity(user_goal: str, template_goal: str) -> float:
    if user_goal == template_goal:
        return 1.0
    if "general_fitness" in (user_goal, template_goal):
        return 0.62
    return 0.58


def _available_equipment(profile: Dict[str, Any]) -> Optional[set[str]]:
    configured = profile.get("available_equipment")
    if not configured:
        return None
    equipment = {str(item).lower() for item in configured if item}
    equipment.add("bodyweight")
    return equipment


def _template_is_available(
    template: ProgramTemplate,
    equipment: Optional[set[str]],
) -> bool:
    if equipment is None:
        return True
    return set(template.required_equipment).issubset(equipment)


def _pain_locations(sessions: Iterable[Dict[str, Any]]) -> set[str]:
    locations: set[str] = set()
    for session in sessions:
        feedback = session.get("pain_feedback") or {}
        if feedback.get("has_pain") and feedback.get("pain_location"):
            locations.add(str(feedback["pain_location"]).lower())
    return locations


def _history_stats(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not sessions:
        return {
            "session_count": 0,
            "average_completion_rate": None,
            "average_rpe": None,
            "pain_sessions": 0,
            "actual_sessions_per_week": None,
            "pain_locations": [],
        }

    completion_values = [
        float(session["completion_rate"])
        for session in sessions
        if session.get("completion_rate") is not None
    ]
    rpe_values = [
        float(session["rpe"])
        for session in sessions
        if session.get("rpe") is not None
    ]
    pain_locations = sorted(_pain_locations(sessions))

    parsed_dates: List[date] = []
    for session in sessions:
        raw_date = session.get("date")
        if not raw_date:
            continue
        try:
            parsed_dates.append(date.fromisoformat(str(raw_date)[:10]))
        except ValueError:
            continue

    actual_frequency = None
    if parsed_dates:
        span_days = max(7, (max(parsed_dates) - min(parsed_dates)).days + 1)
        actual_frequency = len(sessions) / (span_days / 7.0)

    return {
        "session_count": len(sessions),
        "average_completion_rate": (
            sum(completion_values) / len(completion_values)
            if completion_values
            else None
        ),
        "average_rpe": (
            sum(rpe_values) / len(rpe_values) if rpe_values else None
        ),
        "pain_sessions": len(pain_locations),
        "actual_sessions_per_week": actual_frequency,
        "pain_locations": pain_locations,
    }


def _safety_fit(profile: Dict[str, Any], template: ProgramTemplate) -> float:
    medical_history = profile.get("medical_history") or []
    has_high_severity = any(
        str(item.get("severity", "")).lower() == "high"
        for item in medical_history
    )
    demand = _LEVEL_INDEX.get(template.difficulty, 2)

    score = 1.0
    if medical_history and demand == 3:
        score -= 0.22
    if has_high_severity and demand == 3:
        score -= 0.20
    elif has_high_severity and demand == 2:
        score -= 0.08
    if template.low_impact:
        score += 0.08
    return _clamp(score)


def _behaviour_fit(
    template: ProgramTemplate,
    stats: Dict[str, Any],
) -> float:
    if not stats["session_count"]:
        return 0.55

    completion = stats["average_completion_rate"]
    average_rpe = stats["average_rpe"]
    actual_frequency = stats["actual_sessions_per_week"]
    completion = 0.72 if completion is None else _clamp(completion)
    average_rpe = 7.0 if average_rpe is None else average_rpe

    if completion < 0.60 or average_rpe >= 8.5 or stats["pain_sessions"]:
        capacity = 1
    elif completion < 0.80 or average_rpe >= 7.8:
        capacity = 2
    else:
        capacity = 3

    demand = _LEVEL_INDEX.get(template.difficulty, 2)
    demand_fit = 1.0 - abs(capacity - demand) / 2.0

    if actual_frequency is None:
        schedule_fit = 0.55
    else:
        schedule_fit = 1.0 - min(
            abs(actual_frequency - template.sessions_per_week) / 4.0,
            1.0,
        )

    score = 0.45 * completion + 0.35 * demand_fit + 0.20 * schedule_fit
    if stats["pain_sessions"] and not template.low_impact:
        score -= 0.10
    return _clamp(score)


def _population_fit(
    template: ProgramTemplate,
    adoption_programs: List[Dict[str, Any]],
) -> float:
    if not adoption_programs:
        return template.popularity_prior

    same_goal = 0
    exact_shape = 0
    for program in adoption_programs:
        if program.get("goal") != template.goal:
            continue
        same_goal += 1
        if (
            program.get("split_type") == template.split_type
            and program.get("sessions_per_week") == template.sessions_per_week
            and program.get("total_weeks") == template.total_weeks
        ):
            exact_shape += 1

    observed = 0.35 * min(1.0, exact_shape / 2.0)
    observed += 0.20 * min(1.0, same_goal / 5.0)
    return _clamp(0.45 * template.popularity_prior + observed)


def _reasons_and_cautions(
    template: ProgramTemplate,
    profile: Dict[str, Any],
    user_goal: str,
    stats: Dict[str, Any],
) -> Tuple[List[str], List[str]]:
    reasons: List[str] = []
    cautions: List[str] = []
    user_level = (profile.get("fitness_level") or "beginner").lower()
    training_frequency = int(profile.get("training_frequency") or 3)

    if user_goal == template.goal:
        reasons.append(f"目标完全匹配：{GOAL_LABELS[template.goal]}")
    if user_level == template.difficulty:
        reasons.append(f"难度匹配{LEVEL_LABELS[template.difficulty]}水平")
    if training_frequency == template.sessions_per_week:
        reasons.append(f"每周 {template.sessions_per_week} 次与目标频率一致")

    completion = stats["average_completion_rate"]
    average_rpe = stats["average_rpe"]
    if completion is not None:
        reasons.append(f"近 {stats['session_count']} 次训练平均完成率 {completion:.0%}")
    if average_rpe is not None and average_rpe <= 8.2:
        reasons.append(f"近期平均 RPE {average_rpe:.1f}，仍有进阶空间")

    medical_history = profile.get("medical_history") or []
    if medical_history:
        cautions.append("采用计划时会继续按伤病史过滤高风险动作")
    if template.difficulty == "advanced" and user_level != "advanced":
        cautions.append("该计划训练负荷较高，建议先完成基础周期")

    actual_frequency = stats["actual_sessions_per_week"]
    if actual_frequency is not None and actual_frequency + 1.0 < template.sessions_per_week:
        cautions.append(
            f"历史训练约每周 {actual_frequency:.1f} 次，低于本计划安排的 "
            f"{template.sessions_per_week} 次"
        )
    if average_rpe is not None and average_rpe >= 8.5:
        cautions.append("近期自觉强度偏高，采用后建议先执行减量或重复适应周")

    return reasons[:4], cautions[:2]


class ProgramRecommendationService:
    """Rank supported program templates for one user."""

    MODEL_NAME = "Hybrid Program Recommender"
    MODEL_VERSION = "1.0.0"
    WEIGHTS = {
        "profile": 0.60,
        "behaviour": 0.30,
        "population": 0.10,
    }

    def recommend(
        self,
        user_profile: Dict[str, Any],
        sessions: Optional[List[Dict[str, Any]]] = None,
        adoption_programs: Optional[List[Dict[str, Any]]] = None,
        safe_exercise_count: int = 0,
        forbidden_exercise_count: int = 0,
        limit: int = 6,
    ) -> Dict[str, Any]:
        sessions = sessions or []
        adoption_programs = adoption_programs or []
        user_goal = _normalise_goal(user_profile.get("fitness_goal"))
        equipment = _available_equipment(user_profile)
        stats = _history_stats(sessions)
        user_level = _level_value(user_profile.get("fitness_level"))
        training_frequency = int(user_profile.get("training_frequency") or 3)

        candidates = [
            template
            for template in PROGRAM_CATALOG
            if _template_is_available(template, equipment)
        ]

        scored: List[Dict[str, Any]] = []
        for template in candidates:
            goal_fit = _goal_similarity(user_goal, template.goal)
            level_fit = 1.0 - abs(
                user_level - _LEVEL_INDEX[template.difficulty]
            ) / 2.0
            frequency_fit = 1.0 - min(
                abs(training_frequency - template.sessions_per_week) / 4.0,
                1.0,
            )
            safety_fit = _safety_fit(user_profile, template)
            profile_fit = _clamp(
                0.45 * goal_fit
                + 0.20 * level_fit
                + 0.20 * frequency_fit
                + 0.15 * safety_fit
            )
            behaviour_fit = _behaviour_fit(template, stats)
            population_fit = _population_fit(template, adoption_programs)
            final_score = (
                self.WEIGHTS["profile"] * profile_fit
                + self.WEIGHTS["behaviour"] * behaviour_fit
                + self.WEIGHTS["population"] * population_fit
            )
            reasons, cautions = _reasons_and_cautions(
                template,
                user_profile,
                user_goal,
                stats,
            )
            scored.append(
                {
                    "template_id": template.template_id,
                    "name": template.name,
                    "description": template.description,
                    "goal": template.goal,
                    "goal_label": GOAL_LABELS[template.goal],
                    "split_type": template.split_type,
                    "split_label": SPLIT_LABELS[template.split_type],
                    "total_weeks": template.total_weeks,
                    "sessions_per_week": template.sessions_per_week,
                    "difficulty": template.difficulty,
                    "difficulty_label": LEVEL_LABELS[template.difficulty],
                    "estimated_duration_minutes": template.estimated_duration_minutes,
                    "focus_areas": list(template.focus_areas),
                    "required_equipment": [
                        EQUIPMENT_LABELS.get(item, item)
                        for item in template.required_equipment
                    ],
                    "score": round(final_score * 100.0, 1),
                    "component_scores": {
                        "profile": round(profile_fit * 100.0, 1),
                        "behaviour": round(behaviour_fit * 100.0, 1),
                        "population": round(population_fit * 100.0, 1),
                    },
                    "match_reasons": reasons,
                    "cautions": cautions,
                    "safe_exercise_count": safe_exercise_count,
                    "forbidden_exercise_count": forbidden_exercise_count,
                }
            )

        scored.sort(key=lambda item: (-item["score"], item["template_id"]))
        recommendations = scored[: max(1, min(limit, len(PROGRAM_CATALOG)))]
        for rank, recommendation in enumerate(recommendations, 1):
            recommendation["rank"] = rank

        return {
            "model": {
                "name": self.MODEL_NAME,
                "version": self.MODEL_VERSION,
                "weights": self.WEIGHTS,
            },
            "user_snapshot": {
                "goal": user_goal,
                "goal_label": GOAL_LABELS[user_goal],
                "fitness_level": (user_profile.get("fitness_level") or "beginner"),
                "training_frequency": training_frequency,
                "available_equipment": list(
                    user_profile.get("available_equipment") or []
                ),
                "injury_count": len(user_profile.get("medical_history") or []),
                "session_count": stats["session_count"],
                "average_completion_rate": (
                    round(stats["average_completion_rate"] * 100.0, 1)
                    if stats["average_completion_rate"] is not None
                    else None
                ),
                "average_rpe": (
                    round(stats["average_rpe"], 1)
                    if stats["average_rpe"] is not None
                    else None
                ),
                "actual_sessions_per_week": (
                    round(stats["actual_sessions_per_week"], 1)
                    if stats["actual_sessions_per_week"] is not None
                    else None
                ),
                "pain_locations": stats["pain_locations"],
            },
            "recommendations": recommendations,
        }
