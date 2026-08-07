"""
Program Generator — Phase 3: Long-term Periodized Training Programs
====================================================================

Generates multi-week training programs (mesocycles) and handles
week-by-week adaptive progression based on logged training feedback.

Architecture
------------
ProgramGeneratorService
  ├─ generate_program()   → full mesocycle JSON (Mock or LLM)
  └─ advance_week()       → update program for next week with adaptive logic

Periodization concepts implemented
-----------------------------------
Split types     : full_body · upper_lower · push_pull_legs
Week types      : base · progression · peak · deload
Goals           : strength · hypertrophy · general_fitness
Periodization   : linear (beginner) · block (intermediate/advanced)

Adaptive advance rules
-----------------------
  Deload triggered          → override next week as "deload"
  Completion rate < 60%     → repeat same week (not ready to progress)
  Completion rate < 80%     → hold week type (no intensity bump)
  Avg RPE > 8.5             → hold week type
  Otherwise                 → advance to next planned week type

Usage
-----
    from program_generator import ProgramGeneratorService
    from risk_engine import RiskAssessmentEngine

    engine = RiskAssessmentEngine("exercise_db.json")
    svc = ProgramGeneratorService(engine, use_llm=False)

    program = svc.generate_program(
        user_profile=profile_dict,
        goal="strength",
        total_weeks=4,
        sessions_per_week=4,
    )
    # ... user trains for a week ...
    program, report = svc.advance_week(program, completed_sessions_dicts)
"""
from __future__ import annotations

import random
import statistics
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from risk_engine import RiskAssessmentEngine, ForbiddenExercise
from history_analyzer import HistorySummary
from exercise_meta import sanitize_program_weeks


# =============================================================================
# Constants — Periodization tables
# =============================================================================

# Canonical split patterns: sessions_per_week → ordered workout_type list
_SPLIT_PATTERNS: Dict[int, Dict[str, List[str]]] = {
    2: {
        "full_body":        ["full_body", "full_body"],
    },
    3: {
        "full_body":        ["full_body", "full_body", "full_body"],
        "upper_lower":      ["upper_body", "lower_body", "full_body"],
    },
    4: {
        "upper_lower":      ["upper_body", "lower_body", "upper_body", "lower_body"],
        "full_body":        ["full_body", "full_body", "full_body", "full_body"],
    },
    5: {
        "push_pull_legs":   ["push", "pull", "lower_body", "upper_body", "lower_body"],
        "upper_lower":      ["upper_body", "lower_body", "upper_body", "lower_body", "full_body"],
    },
    6: {
        "push_pull_legs":   ["push", "pull", "lower_body", "push", "pull", "lower_body"],
    },
}

# Default split selection by goal + sessions_per_week when user picks "auto"
_AUTO_SPLIT: Dict[str, Dict[int, str]] = {
    "strength":        {2: "full_body", 3: "full_body",  4: "upper_lower",  5: "upper_lower",   6: "push_pull_legs"},
    "hypertrophy":     {2: "full_body", 3: "upper_lower", 4: "upper_lower", 5: "push_pull_legs", 6: "push_pull_legs"},
    "general_fitness": {2: "full_body", 3: "full_body",  4: "full_body",    5: "upper_lower",    6: "upper_lower"},
}

# Week-type sequencing for different program lengths
_WEEK_SEQUENCES: Dict[int, List[str]] = {
    4:  ["base", "progression", "progression", "deload"],
    5:  ["base", "progression", "progression", "peak",        "deload"],
    6:  ["base", "progression", "progression", "peak",        "peak",        "deload"],
    8:  ["base", "base",        "progression", "progression", "deload",
         "progression", "peak", "deload"],
    12: ["base", "base", "progression", "deload",
         "progression", "progression", "peak", "deload",
         "progression", "peak", "peak", "deload"],
}

# Volume modifier per week type (multiplied against base volume)
_VOLUME_MODIFIER: Dict[str, float] = {
    "base":        1.00,
    "progression": 1.10,
    "peak":        0.90,
    "deload":      0.60,
}

# Rep schemes: goal → week_type → {sets, reps, rest_seconds, rpe_target}
_REP_SCHEMES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "strength": {
        "base":        {"sets": 3, "reps": "5-6",  "rest": 180, "rpe": "自觉强度 7，约 65% 一次最大重量"},
        "progression": {"sets": 4, "reps": "4-5",  "rest": 180, "rpe": "自觉强度 8，约 75% 一次最大重量"},
        "peak":        {"sets": 5, "reps": "3-4",  "rest": 180, "rpe": "自觉强度 9，约 85% 一次最大重量"},
        "deload":      {"sets": 2, "reps": "8-10", "rest": 120, "rpe": "自觉强度 6，约 55% 一次最大重量"},
    },
    "hypertrophy": {
        "base":        {"sets": 3, "reps": "10-12", "rest":  90, "rpe": "自觉强度 7，约 65% 一次最大重量"},
        "progression": {"sets": 4, "reps": "8-10",  "rest":  90, "rpe": "自觉强度 8，约 70% 一次最大重量"},
        "peak":        {"sets": 4, "reps": "6-8",   "rest":  90, "rpe": "自觉强度 8–9，约 75% 一次最大重量"},
        "deload":      {"sets": 2, "reps": "12-15", "rest":  60, "rpe": "自觉强度 6，约 55% 一次最大重量"},
    },
    "general_fitness": {
        "base":        {"sets": 3, "reps": "10-12", "rest":  90, "rpe": "自觉强度 6–7"},
        "progression": {"sets": 3, "reps": "8-12",  "rest":  90, "rpe": "自觉强度 7–8"},
        "peak":        {"sets": 3, "reps": "8-10",  "rest":  90, "rpe": "自觉强度 8"},
        "deload":      {"sets": 2, "reps": "12-15", "rest":  60, "rpe": "自觉强度 5–6"},
    },
}

# Intensity guidance per week type (Chinese)
_INTENSITY_NOTES: Dict[str, str] = {
    "base":        "以技术学习为主，重量约 65% 1RM，不追求极限",
    "progression": "逐步加重，在保证技术前提下挑战自我",
    "peak":        "接近最大重量，组间充分恢复，技术保持规范",
    "deload":      "大幅减量减强度，注重关节活动度与动作控制，让身体充分恢复",
}

# Exercise categorisation by target_muscle
_MUSCLE_CATEGORY: Dict[str, str] = {
    "Quadriceps":       "lower",
    "Hamstrings":       "lower",
    "Gluteus Maximus":  "lower",
    "Gastrocnemius":    "lower",
    "Hip Flexors":      "lower",
    "Pectorals":        "push",
    "Deltoids":         "push",
    "Triceps Brachii":  "push",
    "Anterior Deltoids":"push",
    "Latissimus Dorsi": "pull",
    "Rhomboids":        "pull",
    "Rear Deltoids":    "pull",
    "Biceps Brachii":   "pull",
    "Brachialis":       "pull",
    "Trapezius":        "pull",
    "Forearm Flexors":  "pull",
    "Erector Spinae":   "core",
    "Rectus Abdominis": "core",
    "Obliques":         "core",
}

# Workout-type → which exercise categories it draws from
_SESSION_CATEGORIES: Dict[str, List[str]] = {
    "upper_body":  ["push", "pull"],
    "lower_body":  ["lower", "core"],
    "full_body":   ["push", "pull", "lower", "core"],
    "push":        ["push"],
    "pull":        ["pull", "core"],
}

# Workout-type → Chinese label templates
_SESSION_LABELS: Dict[str, List[str]] = {
    "upper_body": ["上肢综合日", "上肢力量日"],
    "lower_body": ["下肢综合日", "下肢力量日"],
    "full_body":  ["全身综合日", "全身力量日"],
    "push":       ["推类日（胸·肩·三头）"],
    "pull":       ["拉类日（背·二头）"],
}

# Main lifts target counts per workout type
_MAIN_LIFT_COUNTS: Dict[str, int] = {
    "upper_body": 4,
    "lower_body": 3,
    "full_body":  5,
    "push":       4,
    "pull":       4,
}


# =============================================================================
# Public service class
# =============================================================================

class ProgramGeneratorService:
    """
    Orchestrates long-term training program generation and week advancement.

    Parameters
    ----------
    risk_engine : RiskAssessmentEngine
        Used for static risk filtering of exercises.
    use_llm : bool
        If True, delegates generation to the real LLM (falls back to Mock on error).
    llm_client : Optional[LLMClient]
        Pre-configured LLM client. Auto-initialised from env if None.
    """

    GENERATOR_VERSION_MOCK = "program_mock_v1.0"
    GENERATOR_VERSION_LLM  = "program_llm_v1.0"

    def __init__(
        self,
        risk_engine: RiskAssessmentEngine,
        use_llm: bool = False,
        llm_client=None,
    ) -> None:
        self.risk_engine = risk_engine
        self.use_llm = use_llm
        self._llm_client = llm_client

    # ── Primary API ──────────────────────────────────────────────────────────

    def generate_program(
        self,
        user_profile: Dict[str, Any],
        goal: str = "general_fitness",
        total_weeks: int = 4,
        sessions_per_week: int = 3,
        split_type: str = "auto",
        history_summary: Optional[HistorySummary] = None,
    ) -> Dict[str, Any]:
        """
        Generate a complete multi-week training program.

        Returns a program dict compatible with the TrainingProgram DB model.
        """
        # Validate and normalise inputs
        goal = goal if goal in _REP_SCHEMES else "general_fitness"
        total_weeks = max(2, min(12, total_weeks))
        sessions_per_week = max(2, min(6, sessions_per_week))

        # Resolve split type
        resolved_split = self._resolve_split(goal, sessions_per_week, split_type)

        # Risk filtering
        forbidden, safe = self.risk_engine.analyze_static_risk(user_profile)

        if self.use_llm:
            try:
                return self._llm_generate(
                    user_profile, goal, total_weeks, sessions_per_week,
                    resolved_split, safe, forbidden, history_summary,
                )
            except Exception as exc:
                print(f"   ⚠️  LLM program generation failed ({exc}). Falling back to Mock.")

        return self._mock_generate(
            user_profile, goal, total_weeks, sessions_per_week,
            resolved_split, safe, forbidden, history_summary,
        )

    def advance_week(
        self,
        program: Dict[str, Any],
        completed_sessions: List[Dict[str, Any]],
        history_summary: Optional[HistorySummary] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Advance the program to the next week, applying adaptive modifications.

        Parameters
        ----------
        program            : Current program dict (from DB or generate_program).
        completed_sessions : Dicts of training sessions completed in the current week.
        history_summary    : Optional pre-built HistorySummary (Phase 2 analysis).

        Returns
        -------
        (updated_program, adaptation_report)
            updated_program    — mutated program dict ready to save back to DB.
            adaptation_report  — human-readable dict explaining what was changed.
        """
        import copy
        program = copy.deepcopy(program)

        current_week_idx = program.get("current_week", 1) - 1
        weeks = program.get("weeks", [])
        total_weeks = program.get("total_weeks", len(weeks))

        if current_week_idx >= total_weeks:
            program["status"] = "completed"
            return program, {"message": "程序已完成所有训练周", "status": "completed"}

        current_week = weeks[current_week_idx] if current_week_idx < len(weeks) else {}
        sessions_planned = program.get("sessions_per_week", 3)

        # ── Analyse this week's completion ───────────────────────────────────
        n_done = len(completed_sessions)
        completion_rate = n_done / max(sessions_planned, 1)
        avg_rpe = (
            statistics.mean(s["rpe"] for s in completed_sessions)
            if completed_sessions else 5.0
        )
        pain_this_week = any(
            (s.get("pain_feedback") or {}).get("has_pain") for s in completed_sessions
        )

        # ── Determine next week's type ────────────────────────────────────────
        adaptation_notes: List[str] = []
        next_week_idx = current_week_idx + 1

        if next_week_idx >= len(weeks):
            # Already on last week
            program["status"] = "completed"
            return program, {"message": "已完成所有训练周", "status": "completed"}

        next_week = weeks[next_week_idx]
        planned_next_type = next_week.get("week_type", "progression")
        actual_next_type = planned_next_type  # may be overridden below

        # Rule 1 — Force deload if triggered by history analysis
        if history_summary and history_summary.deload_recommended:
            actual_next_type = "deload"
            adaptation_notes.append(
                f"🔴 触发减量周：{history_summary.deload_reason}"
            )

        # Rule 2 — Completion too low: repeat current week
        elif completion_rate < 0.60:
            actual_next_type = current_week.get("week_type", "base")
            adaptation_notes.append(
                f"⚠️ 本周完成率 {int(completion_rate*100)}%（不足60%），"
                "下周重复本周计划，无需进阶。"
            )
            # Rewind current_week pointer
            next_week_idx = current_week_idx

        # Rule 3 — Completion OK but RPE very high: hold intensity
        elif avg_rpe > 8.5 or completion_rate < 0.80:
            actual_next_type = current_week.get("week_type", "base")  # no progression
            adaptation_notes.append(
                f"⚠️ 本周平均 RPE {round(avg_rpe,1)}/完成率 {int(completion_rate*100)}%，"
                "下周维持同等强度，暂缓进阶。"
            )

        else:
            # Normal progression
            adaptation_notes.append(
                f"✅ 本周完成率 {int(completion_rate*100)}%，"
                f"平均 RPE {round(avg_rpe,1)}，下周正常进阶。"
            )

        if pain_this_week and actual_next_type not in ("deload",):
            adaptation_notes.append(
                "⚠️ 本周有疼痛记录，下周请关注受影响关节，必要时主动降低相关动作强度。"
            )

        # Apply the resolved type to next week
        next_week = weeks[next_week_idx]
        next_week["actual_week_type"] = actual_next_type
        next_week["volume_modifier"] = _VOLUME_MODIFIER.get(actual_next_type, 1.0)
        next_week["intensity_note"] = _INTENSITY_NOTES.get(actual_next_type, "")
        next_week["adaptation_notes"] = adaptation_notes

        # Mark current week as completed
        weeks[current_week_idx]["status"] = "completed"
        weeks[current_week_idx]["completed_sessions"] = n_done
        weeks[current_week_idx]["actual_avg_rpe"] = round(avg_rpe, 1)

        program["weeks"] = weeks
        program["current_week"] = next_week_idx + 1  # 1-based
        program["updated_at"] = datetime.now(timezone.utc).isoformat()

        adaptation_report = {
            "previous_week":     current_week_idx + 1,
            "next_week":         next_week_idx + 1,
            "sessions_completed": n_done,
            "completion_rate":   round(completion_rate, 2),
            "avg_rpe":           round(avg_rpe, 1),
            "planned_next_type": planned_next_type,
            "actual_next_type":  actual_next_type,
            "adaptation_notes":  adaptation_notes,
        }

        return program, adaptation_report

    # ── Internal generators ───────────────────────────────────────────────────

    def _resolve_split(
        self, goal: str, sessions_per_week: int, split_type: str
    ) -> str:
        if split_type != "auto" and sessions_per_week in _SPLIT_PATTERNS:
            available = list(_SPLIT_PATTERNS[sessions_per_week].keys())
            if split_type in available:
                return split_type
        # Auto-select or fallback
        goal_map = _AUTO_SPLIT.get(goal, _AUTO_SPLIT["general_fitness"])
        return goal_map.get(sessions_per_week, "full_body")

    def _mock_generate(
        self,
        user_profile: Dict[str, Any],
        goal: str,
        total_weeks: int,
        sessions_per_week: int,
        split_type: str,
        safe_exercises: List[str],
        forbidden_exercises: List[ForbiddenExercise],
        history_summary: Optional[HistorySummary],
    ) -> Dict[str, Any]:
        """
        Deterministic program generation without an LLM.
        Produces a realistic mesocycle structure based on periodization rules.
        """
        user_id = user_profile.get("user_id", "unknown")
        fitness_level = user_profile.get("fitness_level", "beginner")

        # Build exercise pool categorised by movement type
        ex_pool = self._build_exercise_pool(safe_exercises, split_type)

        # Week sequence
        week_sequence = _WEEK_SEQUENCES.get(total_weeks, _WEEK_SEQUENCES[4])
        if len(week_sequence) < total_weeks:
            # Extend by repeating progression/base pattern
            extras = ["progression"] * (total_weeks - len(week_sequence) - 1) + ["deload"]
            week_sequence = week_sequence[:-1] + extras + week_sequence[-1:]

        # If history says deload first, override week 1
        if history_summary and history_summary.deload_recommended:
            week_sequence = ["deload"] + list(week_sequence[1:])

        # Session pattern for this split
        session_types = _SPLIT_PATTERNS.get(sessions_per_week, {}).get(split_type, [])
        if not session_types:
            session_types = ["full_body"] * sessions_per_week

        weeks: List[Dict[str, Any]] = []
        for wk_idx, week_type in enumerate(week_sequence[:total_weeks]):
            scheme = _REP_SCHEMES[goal][week_type]
            volume_mod = _VOLUME_MODIFIER[week_type]
            sets = max(2, round(scheme["sets"] * volume_mod))

            sessions: List[Dict[str, Any]] = []
            for sess_idx, workout_type in enumerate(session_types):
                exercises = self._select_exercises(
                    ex_pool=ex_pool,
                    workout_type=workout_type,
                    goal=goal,
                    n_main=_MAIN_LIFT_COUNTS.get(workout_type, 4),
                )

                label_opts = _SESSION_LABELS.get(workout_type, [workout_type])
                label = label_opts[sess_idx % len(label_opts)]

                key_exercises = []
                for ex in exercises:
                    key_exercises.append({
                        "name":           ex.get("name", "Unknown"),
                        "sets":           sets,
                        "reps":           scheme["reps"],
                        "rest_seconds":   scheme["rest"],
                        "intensity_note": scheme["rpe"],
                        "target_muscle":  ex.get("target_muscle", ""),
                    })

                sessions.append({
                    "session_number":          sess_idx + 1,
                    "workout_type":            workout_type,
                    "label":                   label,
                    "estimated_duration_minutes": 50 + sets * 4,
                    "key_exercises":           key_exercises,
                    "notes": (
                        "减量周：减少组数和重量，专注动作质量"
                        if week_type == "deload"
                        else f"{'热身10分钟 → ' if sets >= 4 else '热身8分钟 → '}"
                             f"主训 → 拉伸放松5分钟"
                    ),
                })

            weeks.append({
                "week_number":    wk_idx + 1,
                "week_type":      week_type,
                "actual_week_type": week_type,  # may be overridden by advance_week
                "status":         "scheduled" if wk_idx > 0 else "in_progress",
                "label":          self._week_label(wk_idx + 1, week_type),
                "volume_modifier": volume_mod,
                "intensity_note":  _INTENSITY_NOTES[week_type],
                "sessions":        sessions,
                "adaptation_notes": [],
            })

        program_id = f"prog_{uuid.uuid4().hex[:10]}"
        program_name = self._program_name(goal, total_weeks, split_type, fitness_level)

        return {
            "program_id":           program_id,
            "user_id":              user_id,
            "name":                 program_name,
            "description":          self._program_description(goal, total_weeks, sessions_per_week, split_type),
            "status":               "active",
            "total_weeks":          total_weeks,
            "current_week":         1,
            "split_type":           split_type,
            "goal":                 goal,
            "sessions_per_week":    sessions_per_week,
            "periodization_model":  "linear" if fitness_level == "beginner" else "block",
            "generator_version":    self.GENERATOR_VERSION_MOCK,
            "forbidden_exercise_count": len(forbidden_exercises),
            "safe_exercise_count":      len(safe_exercises),
            "weeks":                sanitize_program_weeks(weeks, safe_exercises),
            "created_at":           datetime.now(timezone.utc).isoformat(),
            "updated_at":           datetime.now(timezone.utc).isoformat(),
        }

    def _llm_generate(
        self,
        user_profile: Dict[str, Any],
        goal: str,
        total_weeks: int,
        sessions_per_week: int,
        split_type: str,
        safe_exercises: List[str],
        forbidden_exercises: List[ForbiddenExercise],
        history_summary: Optional[HistorySummary],
    ) -> Dict[str, Any]:
        """Delegate to LLMClient.generate_training_program()."""
        from llm_client import LLMClient
        if self._llm_client is None:
            self._llm_client = LLMClient()

        history_context = history_summary.llm_context_text if history_summary else ""

        program_dict = self._llm_client.generate_training_program(
            user_profile=user_profile,
            goal=goal,
            total_weeks=total_weeks,
            sessions_per_week=sessions_per_week,
            split_type=split_type,
            safe_exercises=safe_exercises,
            forbidden_exercises=forbidden_exercises,
            history_context=history_context,
        )
        program_dict["generator_version"] = self.GENERATOR_VERSION_LLM
        if program_dict.get("weeks"):
            program_dict["weeks"] = sanitize_program_weeks(program_dict["weeks"], safe_exercises)
        return program_dict

    # ── Exercise selection helpers ────────────────────────────────────────────

    def _build_exercise_pool(
        self, safe_exercises: List[str], split_type: str
    ) -> Dict[str, List[Dict]]:
        """
        Build a {category → [exercise_dict]} pool from the safe exercise list.
        Compound exercises are preferred for main lifts.
        """
        pool: Dict[str, List[Dict]] = {
            "push": [], "pull": [], "lower": [], "core": [], "compound": []
        }
        name_to_ex = {ex["name"]: ex for ex in self.risk_engine.exercise_db}

        for ex_name in safe_exercises:
            ex = name_to_ex.get(ex_name)
            if not ex:
                continue
            muscle = ex.get("target_muscle", "")
            cat = _MUSCLE_CATEGORY.get(muscle, "compound")
            pool[cat].append(ex)
            if ex.get("type") == "Compound":
                pool["compound"].append(ex)  # also index in compound for priority

        return pool

    def _select_exercises(
        self,
        ex_pool: Dict[str, List[Dict]],
        workout_type: str,
        goal: str,
        n_main: int = 4,
    ) -> List[Dict]:
        """
        Select n_main exercises for a session, favouring compound lifts first.
        Deduplicates across the selection.
        """
        categories = _SESSION_CATEGORIES.get(workout_type, ["push", "pull", "lower"])
        # Collect candidate exercises
        candidates: List[Dict] = []
        seen: set = set()

        # Prioritise compound movements
        for ex in ex_pool.get("compound", []):
            cat = _MUSCLE_CATEGORY.get(ex.get("target_muscle", ""), "compound")
            if cat in categories and ex["name"] not in seen:
                candidates.append(ex)
                seen.add(ex["name"])

        # Fill with isolation / non-compound
        for cat in categories:
            for ex in ex_pool.get(cat, []):
                if ex["name"] not in seen:
                    candidates.append(ex)
                    seen.add(ex["name"])

        # Shuffle to add variety between program generations
        random.shuffle(candidates)

        # For strength, prefer heavier compound lifts (lower risk_level = safer but
        # here higher risk_level means more demanding — pick mid-range for safety)
        if goal == "strength":
            candidates.sort(key=lambda e: (e.get("type") != "Compound", e.get("risk_level", 3)))

        return candidates[:n_main]

    # ── Label helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _week_label(week_number: int, week_type: str) -> str:
        labels = {
            "base":        f"第 {week_number} 周 — 适应期",
            "progression": f"第 {week_number} 周 — 进阶期",
            "peak":        f"第 {week_number} 周 — 峰值期",
            "deload":      f"第 {week_number} 周 — 减量恢复",
        }
        return labels.get(week_type, f"第 {week_number} 周")

    @staticmethod
    def _program_name(
        goal: str, total_weeks: int, split_type: str, fitness_level: str
    ) -> str:
        goal_cn = {"strength": "力量", "hypertrophy": "增肌", "general_fitness": "综合体能"}
        split_cn = {
            "full_body": "全身", "upper_lower": "上下肢分化",
            "push_pull_legs": "推拉腿", "auto": "智能分化",
        }
        return (
            f"{total_weeks} 周{goal_cn.get(goal, goal)}"
            f"训练计划（{split_cn.get(split_type, split_type)}·"
            f"{'入门' if fitness_level == 'beginner' else '进阶'}）"
        )

    @staticmethod
    def _program_description(
        goal: str, total_weeks: int, sessions_per_week: int, split_type: str
    ) -> str:
        goal_desc = {
            "strength":        "以提升最大力量为核心，侧重低次数、高强度的复合动作训练",
            "hypertrophy":     "以肌肉增长为核心，侧重中等次数、高泵感的训练",
            "general_fitness": "兼顾力量、耐力与协调性的综合训练",
        }
        return (
            f"{goal_desc.get(goal, '')}。"
            f"共 {total_weeks} 周，每周 {sessions_per_week} 次训练。"
            f"采用{'上下肢分化' if 'upper' in split_type else '推拉腿分化' if 'push' in split_type else '全身训练'}模式，"
            f"周期末安排减量周以确保充分恢复。"
        )
