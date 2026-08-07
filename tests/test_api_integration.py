"""API integration tests (health, plan generation, risk analysis, profile sync)."""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_demo_request() -> dict:
    demo_path = PROJECT_ROOT / "generate_plan_request_demo.json"
    if demo_path.is_file():
        with demo_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    return {
        "user_profile": {
            "user_id": "usr_demo_pytest",
            "basic_info": {"age": 28, "gender": "male"},
            "fitness_level": "beginner",
            "medical_history": [],
        },
        "feedback": {
            "session_id": "sess_demo_pytest",
            "user_id": "usr_demo_pytest",
            "date": "2026-03-27",
            "rpe": 7,
            "pain_feedback": {"has_pain": False},
        },
        "workout_type": "full_body",
    }


def test_health_ok(client) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    for key in ["status", "version", "exercise_db_loaded", "exercise_count", "timestamp"]:
        assert key in data


def test_generate_plan_ok(client) -> None:
    payload = _load_demo_request()
    resp = client.post("/generate_plan", json=payload)
    assert resp.status_code == 200, resp.text

    data = resp.json()
    for key in [
        "plan_id", "user_id", "date", "workout_type",
        "estimated_duration_minutes", "phases", "safety_notes",
        "risk_analysis", "generated_at", "generator_version",
    ]:
        assert key in data

    phases = data["phases"]
    for phase_key in ["warm_up", "activation", "main_lifts", "accessories", "cool_down"]:
        assert phase_key in phases
        assert isinstance(phases[phase_key], list)

    risk = data["risk_analysis"]
    for key in ["forbidden_exercises", "safe_exercise_count", "constraints"]:
        assert key in risk


def test_analyze_risk_knee_injury(client) -> None:
    payload = {
        "user_id": "usr_api_risk",
        "basic_info": {"age": 28, "gender": "male"},
        "fitness_level": "intermediate",
        "medical_history": [
            {
                "location": "knee",
                "condition": "meniscus_tear",
                "severity": "high",
            }
        ],
    }
    resp = client.post("/analyze_risk", json=payload)
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert data["summary"]["forbidden_count"] > 0
    names = {ex["name"] for ex in data["forbidden_exercises"]}
    assert "Barbell Back Squat" in names


def test_user_update_medical_history_triggers_revalidation(client, db_session) -> None:
    user_id = "usr_api_reval"
    bad = "Barbell Back Squat"

    create = client.post(
        "/users",
        json={
            "user_id": user_id,
            "basic_info": {"age": 28, "gender": "male"},
            "fitness_level": "intermediate",
            "medical_history": [],
        },
    )
    assert create.status_code == 201, create.text

    import crud

    crud.create_program(
        db_session,
        {
            "program_id": "prog_api_reval",
            "user_id": user_id,
            "name": "API Test Program",
            "status": "active",
            "goal": "strength",
            "split_type": "full_body",
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

    update = client.put(
        f"/users/{user_id}",
        json={
            "medical_history": [
                {
                    "location": "knee",
                    "condition": "meniscus_tear",
                    "severity": "high",
                }
            ],
        },
    )
    assert update.status_code == 200, update.text

    body = update.json()
    rev = body.get("safety_revalidation")
    assert rev is not None
    assert rev["programs_updated"] >= 1
    assert rev["exercises_replaced"] >= 1

    prog_resp = client.get(f"/programs/prog_api_reval")
    assert prog_resp.status_code == 200, prog_resp.text
    weeks = prog_resp.json().get("weeks") or []
    assert weeks
    ex_name = weeks[0]["sessions"][0]["key_exercises"][0]["name"]
    assert ex_name != bad
