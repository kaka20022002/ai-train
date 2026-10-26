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


def test_plan_recommendation_can_be_adopted(client) -> None:
    user_id = "usr_api_recommend"
    profile = {
        "user_id": user_id,
        "basic_info": {"age": 29, "gender": "female"},
        "fitness_level": "intermediate",
        "fitness_goal": "strength",
        "training_frequency": 4,
        "available_equipment": [],
        "medical_history": [
            {
                "location": "knee",
                "condition": "meniscus_tear",
                "severity": "high",
            }
        ],
    }
    create = client.post("/users", json=profile)
    assert create.status_code == 201, create.text

    recommendation = client.get(f"/users/{user_id}/plan-recommendations?limit=3")
    assert recommendation.status_code == 200, recommendation.text
    data = recommendation.json()
    assert data["user_snapshot"]["goal"] == "strength"
    assert len(data["recommendations"]) == 3

    best = data["recommendations"][0]
    assert best["goal"] == "strength"
    assert 0 <= best["score"] <= 100
    assert best["match_reasons"]

    generate = client.post(
        "/programs/generate",
        json={
            "user_profile": profile,
            "goal": best["goal"],
            "total_weeks": best["total_weeks"],
            "sessions_per_week": best["sessions_per_week"],
            "split_type": best["split_type"],
            "use_history": False,
        },
    )
    assert generate.status_code == 201, generate.text
    assert generate.json()["user_id"] == user_id

# ── 三 Agent 管线接入 HTTP ──────────────────────────────────────────────────
KNEE_HIGH_PAYLOAD = {
    "user_profile": {
        "user_id": "usr_api_agents",
        "basic_info": {"age": 28, "gender": "male"},
        "fitness_level": "beginner",
        "medical_history": [
            {"location": "knee", "condition": "meniscus_tear", "severity": "high"}
        ],
    },
    "workout_type": "full_body",
}


def test_generate_plan_defaults_to_agents_pipeline(client) -> None:
    """默认引擎必须是三 Agent 管线，并带回安全结论与审计链。"""
    resp = client.post("/generate_plan", json=KNEE_HIGH_PAYLOAD)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "+grammar/" in data["generator_version"]
    safety = data["safety"]
    assert safety is not None, "engine=agents 必须返回 safety"
    assert safety["passed"] is True
    assert safety["checked_slots"] > 0
    assert safety["masked_count"] > 0
    assert safety["adversarial_probes"] > 0
    assert safety["adversarial_blocked"] == safety["adversarial_probes"]
    assert safety["profile_hash"]

    audit = data["audit"]
    assert audit is not None
    assert [e["stage"] for e in audit[:3]] == ["state_risk", "plan_gen", "safety_eval"]


def test_agents_engine_never_leaks_forbidden_exercise(client) -> None:
    resp = client.post("/generate_plan", json=KNEE_HIGH_PAYLOAD)
    data = resp.json()
    forbidden = {ex["name"] for ex in data["risk_analysis"]["forbidden_exercises"]}
    planned = {ex["name"] for slots in data["phases"].values() for ex in slots}
    assert forbidden, "膝伤 HIGH 应至少禁掉一个动作"
    assert not (planned & forbidden)


def test_agents_engine_fills_every_phase(client) -> None:
    """每个阶段都要按处方填满，不能出现「放松段只有 1 个动作」。"""
    resp = client.post("/generate_plan", json=KNEE_HIGH_PAYLOAD)
    phases = resp.json()["phases"]
    expected = {"warm_up": 3, "activation": 3, "main_lifts": 3, "accessories": 4, "cool_down": 3}
    for phase, n in expected.items():
        assert len(phases[phase]) == n, f"{phase} 只有 {len(phases[phase])} 个动作"


def test_legacy_engine_still_available_for_comparison(client) -> None:
    """engine=legacy 保留旧生成器，供对照实验与回退。"""
    resp = client.post("/generate_plan?engine=legacy", json=KNEE_HIGH_PAYLOAD)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["generator_version"] in ("mock_v1.0", "mock_v1.0_fallback", "llm_v1.0")
    assert data["safety"] is None
    assert data["audit"] is None
