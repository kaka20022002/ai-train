"""
Plan ↔ Program Synchronisation
==============================

Bridges single-session plan generation (`POST /generate_plan`) with the
multi-week program model so that, after a user generates a plan:

1. Their profile is persisted/refreshed in the DB  → 「我的档案」stays in sync.
2. The freshly generated session is woven into a training program → 「周期计划」
   and 「今日训练」 immediately reflect the new plan.

Behaviour
---------
- No active program  → generate a fresh 4-week mesocycle seeded from the user's
  profile, inject the generated plan into week 1 / session 1, and persist it.
- Active program     → inject the generated plan into the current week's next
  not-yet-completed session, keeping the existing periodisation intact.

The function is defensive: any failure is swallowed and `None` is returned so
that plan generation itself never fails because of the sync step.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import crud

# Goals understood by ProgramGeneratorService; anything else falls back.
_VALID_GOALS = {"strength", "hypertrophy", "general_fitness"}


def sync_plan_after_generation(
    db,
    plan_export: Dict[str, Any],
    user_profile: Dict[str, Any],
    program_generator,
    generator_version: str,
    history_summary=None,
) -> Optional[str]:
    """
    Persist the user profile and attach the generated plan to a training program.

    Returns the program_id the plan was synced into, or None on failure.
    """
    try:
        # 1. Keep the user's profile authoritative & up to date.
        crud.upsert_user(db, user_profile)

        user_id = user_profile.get("user_id")
        if not user_id:
            return None

        # 2. Reuse the active program if there is one, else build a new mesocycle.
        active = crud.get_active_program(db, user_id)
        if active is not None:
            return _attach_to_active_program(db, active, plan_export)

        return _create_program_from_plan(
            db, plan_export, user_profile, program_generator, history_summary
        )
    except Exception as exc:  # never break plan generation
        print(f"   ⚠️  plan/program sync skipped due to error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_goal(user_profile: Dict[str, Any]) -> str:
    goal = (user_profile.get("fitness_goal") or "").strip().lower()
    return goal if goal in _VALID_GOALS else "general_fitness"


def _resolve_sessions_per_week(user_profile: Dict[str, Any]) -> int:
    freq = user_profile.get("training_frequency")
    try:
        freq = int(freq)
    except (TypeError, ValueError):
        freq = 3
    return max(2, min(6, freq))


def _create_program_from_plan(
    db,
    plan_export: Dict[str, Any],
    user_profile: Dict[str, Any],
    program_generator,
    history_summary,
) -> Optional[str]:
    """Generate a new program and seed week 1 / session 1 with the plan."""
    program_data = program_generator.generate_program(
        user_profile=user_profile,
        goal=_resolve_goal(user_profile),
        total_weeks=4,
        sessions_per_week=_resolve_sessions_per_week(user_profile),
        split_type="auto",
        history_summary=history_summary,
    )

    weeks = program_data.get("weeks", [])
    if weeks and weeks[0].get("sessions"):
        _inject_plan_into_session(weeks[0]["sessions"][0], plan_export)

    program = crud.create_program(db, program_data)
    return program.program_id


def _attach_to_active_program(db, active, plan_export: Dict[str, Any]) -> Optional[str]:
    """Inject the plan into the active program's next open session this week."""
    program_data = dict(active.program_data or {})
    weeks = program_data.get("weeks", [])
    current_week = active.current_week or 1

    current_week_data = next(
        (w for w in weeks if w.get("week_number") == current_week), None
    )
    if not current_week_data or not current_week_data.get("sessions"):
        return active.program_id  # nothing to attach to; leave program untouched

    sessions = current_week_data["sessions"]

    # Determine the next not-yet-completed session of the current week.
    completed = crud.get_sessions_for_program_week(db, active.program_id, current_week)
    idx = min(len(completed), len(sessions) - 1)

    _inject_plan_into_session(sessions[idx], plan_export)

    # Persist; preserve current_week / status so update_program keeps them intact.
    program_data["current_week"] = current_week
    program_data["status"] = active.status
    crud.update_program(db, active.program_id, program_data)
    return active.program_id


def _inject_plan_into_session(session: Dict[str, Any], plan_export: Dict[str, Any]) -> None:
    """
    Overlay a generated single-session plan onto a program session template.

    Sets the rich five-phase view (`phases`), links the source plan
    (`source_plan_id`), and derives `key_exercises` from the plan's main lifts
    and accessories so the program timeline shows the real exercises.
    """
    phases = plan_export.get("phases") or {}
    session["phases"] = phases
    session["source_plan_id"] = plan_export.get("plan_id")

    duration = plan_export.get("estimated_duration_minutes")
    if duration:
        session["estimated_duration_minutes"] = duration

    workout_type = plan_export.get("workout_type")
    if workout_type:
        session["workout_type"] = workout_type

    key_exercises = _phases_to_key_exercises(phases)
    if key_exercises:
        session["key_exercises"] = key_exercises


def _phases_to_key_exercises(phases: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flatten main_lifts + accessories into the program's key_exercises shape."""
    out: List[Dict[str, Any]] = []
    for phase_key in ("main_lifts", "accessories"):
        for ex in phases.get(phase_key, []):
            out.append({
                "name":           ex.get("name", ""),
                "sets":           ex.get("sets", 3),
                "reps":           str(ex.get("reps", "8-12")),
                "rest_seconds":   ex.get("rest_seconds", 90),
                "intensity_note": ex.get("notes") or "",
                "target_muscle":  ex.get("target_muscle"),
            })
    return out
