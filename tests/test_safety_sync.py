"""Unit tests for safety_sync — forbidden replacement & plan revalidation."""
from __future__ import annotations

import crud
from risk_engine import RiskAssessmentEngine
from safety_sync import (
    RevalidateReport,
    format_forbidden_context_for_coach,
    get_risk_snapshot,
    revalidate_plan_data,
    revalidate_program_data,
    revalidate_user_training_data,
    resolve_safe_exercise_name,
)

from tests.conftest import KNEE_HIGH_PROFILE


def test_resolve_safe_exercise_replaces_forbidden() -> None:
    forbidden, safe = get_risk_snapshot(KNEE_HIGH_PROFILE)
    assert forbidden

    bad_name = forbidden[0].name
    new_name, replaced = resolve_safe_exercise_name(bad_name, forbidden, safe)
    assert replaced is True
    assert new_name.lower() != bad_name.lower()
    assert new_name.lower() in {s.lower() for s in safe}


def test_resolve_safe_exercise_keeps_safe_name() -> None:
    forbidden, safe = get_risk_snapshot(KNEE_HIGH_PROFILE)
    assert safe
    keep = safe[0]
    new_name, replaced = resolve_safe_exercise_name(keep, forbidden, safe)
    assert replaced is False
    assert new_name == keep


def test_format_forbidden_context_lists_exercises() -> None:
    forbidden, safe = get_risk_snapshot(KNEE_HIGH_PROFILE)
    text = format_forbidden_context_for_coach(forbidden, len(safe))
    assert "禁止动作清单" in text
    assert forbidden[0].name in text
    assert str(len(safe)) in text


def test_revalidate_program_data_replaces_key_exercises() -> None:
    forbidden, safe = get_risk_snapshot(KNEE_HIGH_PROFILE)
    bad = forbidden[0].name
    program = {
        "program_id": "prog_test",
        "weeks": [
            {
                "week_number": 1,
                "sessions": [
                    {
                        "session_number": 1,
                        "key_exercises": [{"name": bad, "sets": 3, "reps": "8"}],
                    }
                ],
            }
        ],
    }
    report = RevalidateReport()
    new_data, changed = revalidate_program_data(program, forbidden, safe, report, "prog_test")
    assert changed is True
    assert report.exercises_replaced == 1
    new_name = new_data["weeks"][0]["sessions"][0]["key_exercises"][0]["name"]
    assert new_name != bad


def test_revalidate_plan_data_replaces_phases() -> None:
    forbidden, safe = get_risk_snapshot(KNEE_HIGH_PROFILE)
    bad = forbidden[0].name
    plan = {
        "plan_id": "plan_test",
        "phases": {
            "main_lifts": [{"name": bad, "sets": 4, "reps": "6"}],
            "warm_up": [],
        },
        "risk_analysis": {},
    }
    report = RevalidateReport()
    new_data, changed = revalidate_plan_data(plan, forbidden, safe, report, "plan_test")
    assert changed is True
    assert report.exercises_replaced == 1
    assert new_data["phases"]["main_lifts"][0]["name"] != bad


def test_revalidate_user_training_data_updates_db(db_session) -> None:
    forbidden, safe = get_risk_snapshot(KNEE_HIGH_PROFILE)
    bad = forbidden[0].name
    user_id = KNEE_HIGH_PROFILE["user_id"]

    crud.create_user(db_session, KNEE_HIGH_PROFILE)
    crud.create_program(
        db_session,
        {
            "program_id": "prog_reval",
            "user_id": user_id,
            "name": "Test Program",
            "status": "active",
            "goal": "strength",
            "split_type": "upper_lower",
            "total_weeks": 4,
            "current_week": 1,
            "sessions_per_week": 3,
            "weeks": [
                {
                    "week_number": 1,
                    "sessions": [
                        {
                            "session_number": 1,
                            "key_exercises": [{"name": bad, "sets": 3, "reps": "8"}],
                        }
                    ],
                }
            ],
        },
    )
    crud.save_generated_plan(
        db_session,
        {
            "plan_id": "plan_reval",
            "user_id": user_id,
            "workout_type": "full_body",
            "phases": {"main_lifts": [{"name": bad, "sets": 4, "reps": "6"}]},
        },
    )

    report = revalidate_user_training_data(db_session, user_id, KNEE_HIGH_PROFILE)
    assert report.programs_scanned >= 1
    assert report.programs_updated >= 1
    assert report.plans_updated >= 1
    assert report.exercises_replaced >= 2

    prog = crud.get_program(db_session, "prog_reval")
    assert prog is not None
    ex_name = prog.program_data["weeks"][0]["sessions"][0]["key_exercises"][0]["name"]
    assert ex_name.lower() != bad.lower()

    plan = crud.get_generated_plan(db_session, "plan_reval")
    assert plan is not None
    assert plan.plan_data["phases"]["main_lifts"][0]["name"].lower() != bad.lower()
