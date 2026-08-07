"""Simple integration test script for the FastAPI HTTP API.

Usage (ensure the API server is already running, e.g.):

    /usr/bin/python3 -m uvicorn main:app --reload --host 127.0.0.1 --port 8000

Then, in another terminal from the same directory:

    /usr/bin/python3 integration_test.py

The script will:
- Call GET /health and validate the basic fields
- Call POST /generate_plan with the demo request JSON
- Print a short success summary or raise on failure
"""

import json
import sys
from pathlib import Path

import httpx

BASE_URL = "http://127.0.0.1:8000"
PROJECT_ROOT = Path(__file__).parent


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_health(client: httpx.Client) -> None:
    url = f"{BASE_URL}/health"
    resp = client.get(url, timeout=5.0)
    assert_true(resp.status_code == 200, f"/health returned {resp.status_code}")

    data = resp.json()
    for key in ["status", "version", "exercise_db_loaded", "exercise_count", "timestamp"]:
        assert_true(key in data, f"/health missing field: {key}")

    print("[OK] /health passed")


def load_demo_request() -> dict:
    demo_path = PROJECT_ROOT / "generate_plan_request_demo.json"
    if demo_path.is_file():
        with demo_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    # Fallback: minimal inline request
    return {
        "user_profile": {
            "user_id": "usr_demo_fallback",
            "basic_info": {"age": 28, "gender": "male"},
            "fitness_level": "beginner",
            "medical_history": [],
        },
        "feedback": {
            "session_id": "sess_demo_fallback",
            "user_id": "usr_demo_fallback",
            "date": "2026-03-27",
            "rpe": 7,
            "pain_feedback": {"has_pain": False},
        },
        "workout_type": "full_body",
    }


def test_generate_plan(client: httpx.Client) -> None:
    url = f"{BASE_URL}/generate_plan"
    payload = load_demo_request()

    resp = client.post(url, json=payload, timeout=20.0)
    assert_true(resp.status_code == 200, f"/generate_plan returned {resp.status_code}: {resp.text}")

    data = resp.json()

    # Basic top-level fields
    for key in [
        "plan_id",
        "user_id",
        "date",
        "workout_type",
        "estimated_duration_minutes",
        "phases",
        "safety_notes",
        "risk_analysis",
        "generated_at",
        "generator_version",
    ]:
        assert_true(key in data, f"/generate_plan response missing field: {key}")

    phases = data["phases"]
    for phase_key in ["warm_up", "activation", "main_lifts", "accessories", "cool_down"]:
        assert_true(phase_key in phases, f"phases missing: {phase_key}")
        assert_true(isinstance(phases[phase_key], list), f"phases.{phase_key} should be a list")

    print("[OK] /generate_plan passed")


def main() -> None:
    try:
        with httpx.Client(base_url=BASE_URL) as client:
            print("Running HTTP integration tests against:", BASE_URL)
            test_health(client)
            test_generate_plan(client)
        print("\nAll integration tests passed ✅")
    except Exception as exc:  # noqa: BLE001
        print("Integration tests FAILED:", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
