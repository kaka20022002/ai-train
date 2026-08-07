#!/usr/bin/env python3
"""
Seed demo data for the AI fitness coach system.

Creates:
  - Demo user usr_001 (intermediate, knee injury history)
  - 8 training sessions over ~4 weeks (RPE trend + recurring knee pain)
  - A 4-week strength program (Mock, fast) with 3 week-1 sessions linked

Usage:
    python seed_demo_data.py
    python seed_demo_data.py --base-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

# Ensure project modules & .env are available for in-process program generation
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except ImportError:
    pass

DEMO_USER_ID = "usr_001"
BASE_DEFAULT = "http://localhost:8000"


def _ok(resp: httpx.Response, label: str) -> dict:
    if resp.status_code in (200, 201):
        return resp.json()
    if resp.status_code == 409 or (resp.status_code == 400 and "already" in resp.text.lower()):
        print(f"  ↪ {label}: already exists, skipping")
        return {}
    resp.raise_for_status()
    return resp.json()


def seed_user(client: httpx.Client) -> None:
    print("👤 Registering demo user …")
    payload = {
        "user_id": DEMO_USER_ID,
        "basic_info": {
            "age": 28,
            "gender": "male",
            "height_cm": 175,
            "weight_kg": 78,
            "bmi": 25.5,
        },
        "fitness_level": "intermediate",
        "fitness_goal": "strength",
        "training_frequency": 4,
        "medical_history": [
            {
                "location": "knee",
                "condition": "meniscus_tear",
                "severity": "high",
                "pain_trigger": "deep_flexion",
                "notes": "右膝半月板损伤，避免深蹲过深",
            },
            {
                "location": "shoulder",
                "condition": "mild_impingement",
                "severity": "low",
                "notes": "偶尔弹响，大重量推举需注意",
            },
        ],
    }
    r = client.post("/users", json=payload)
    if r.status_code == 201:
        print(f"  ✓ User '{DEMO_USER_ID}' created")
    elif r.status_code == 409 or (r.status_code == 400 and "unique" in r.text.lower()):
        print(f"  ↪ User '{DEMO_USER_ID}' already exists")
        # Refresh profile in case fields changed
        client.put(f"/users/{DEMO_USER_ID}", json={
            "fitness_level": "intermediate",
            "fitness_goal": "strength",
            "training_frequency": 4,
        })
    else:
        r.raise_for_status()


def seed_sessions(client: httpx.Client, program_id: str | None = None) -> int:
    """Insert 8 historical sessions. Returns count created."""
    print("📊 Logging training sessions …")
    today = date.today()
    # Sessions span ~28 days, oldest first
    sessions_spec = [
        # Week 1 — building base
        dict(days_ago=28, workout_type="upper_body", rpe=6, completion=0.95,
             pain=False, fatigue=3, sleep=8, perf=[("Barbell Bench Press", 60, [10, 10, 9, 8])]),
        dict(days_ago=26, workout_type="lower_body", rpe=7, completion=0.90,
             pain=False, fatigue=4, sleep=7, perf=[("Leg Press", 120, [12, 12, 10])]),
        dict(days_ago=24, workout_type="upper_body", rpe=7, completion=0.88,
             pain=False, fatigue=5, sleep=7, perf=[("Barbell Bench Press", 62.5, [9, 9, 8, 8])]),
        dict(days_ago=22, workout_type="lower_body", rpe=8, completion=0.85,
             pain=True, pain_loc="knee", pain_sev=4, trigger="Leg Press",
             fatigue=6, sleep=6, perf=[("Leg Press", 120, [10, 9, 8])]),
        # Week 2 — intensity up
        dict(days_ago=17, workout_type="upper_body", rpe=8, completion=0.90,
             pain=False, fatigue=5, sleep=7, perf=[("Barbell Bench Press", 65, [8, 8, 7, 7])]),
        dict(days_ago=15, workout_type="lower_body", rpe=8, completion=0.82,
             pain=True, pain_loc="knee", pain_sev=5, trigger="Romanian Deadlift",
             fatigue=7, sleep=5, perf=[("Romanian Deadlift", 70, [8, 8, 7])]),
        # Week 3 — fatigue accumulation (deload signals)
        dict(days_ago=10, workout_type="upper_body", rpe=9, completion=0.78,
             pain=False, fatigue=8, sleep=5, perf=[("Barbell Bench Press", 65, [7, 6, 6])]),
        dict(days_ago=7, workout_type="lower_body", rpe=9, completion=0.75,
             pain=True, pain_loc="knee", pain_sev=6, trigger="Leg Press",
             fatigue=8, sleep=4, perf=[("Leg Press", 110, [8, 7, 6])]),
    ]

    created = 0
    for i, spec in enumerate(sessions_spec):
        session_date = (today - timedelta(days=spec["days_ago"])).isoformat()
        sid = f"sess_demo_{i+1:02d}"

        pain_fb = {"has_pain": spec.get("pain", False)}
        if spec.get("pain"):
            pain_fb.update({
                "pain_location": spec.get("pain_loc", "knee"),
                "pain_severity": spec.get("pain_sev", 5),
                "pain_type": "sharp",
                "trigger_exercise": spec.get("trigger", "Unknown"),
            })

        perf = [
            {
                "name": name,
                "weight_kg": weight,
                "sets_completed": len(reps),
                "reps_per_set": reps,
            }
            for name, weight, reps in spec.get("perf", [])
        ]

        body: dict = {
            "session_id": sid,
            "date": session_date,
            "workout_type": spec["workout_type"],
            "duration_minutes": 55 + (i % 3) * 5,
            "rpe": spec["rpe"],
            "completion_rate": spec["completion"],
            "pain_feedback": pain_fb,
            "fatigue_feedback": {
                "overall_fatigue": spec["fatigue"],
                "sleep_quality_last_night": spec["sleep"],
                "stress_level": 4 + (i % 3),
            },
            "exercise_performance": perf,
            "notes": "演示数据 — 自动生成",
        }

        # Link last 3 sessions to program week 1 if program exists
        if program_id and i >= len(sessions_spec) - 3:
            body["program_id"] = program_id
            body["program_week"] = 1

        r = client.post(f"/users/{DEMO_USER_ID}/sessions", json=body)
        if r.status_code == 201:
            created += 1
            print(f"  ✓ {session_date}  RPE={spec['rpe']}  {spec['workout_type']}")
        elif r.status_code == 409 or "unique" in r.text.lower():
            print(f"  ↪ {sid} already logged")
        else:
            print(f"  ✗ {sid}: {r.status_code} {r.text[:120]}")

    return created


def seed_program_inprocess() -> str | None:
    """Generate program via Mock generator (fast, no LLM timeout)."""
    print("🎯 Generating 4-week strength program (mock) …")
    from database import SessionLocal
    import crud
    from program_generator import ProgramGeneratorService
    from risk_engine import RiskAssessmentEngine

    db = SessionLocal()
    try:
        existing = crud.get_user_programs(db, DEMO_USER_ID, status="active", limit=1)
        if existing:
            pid = existing[0].program_id
            print(f"  ↪ Reusing existing program: {pid}")
            return pid

        user = crud.get_user(db, DEMO_USER_ID)
        if not user:
            print("  ✗ User not found — register first")
            return None

        profile = crud.user_to_profile_dict(user)
        db_path = str(_ROOT / "exercise_db.json")
        engine = RiskAssessmentEngine(db_path=db_path)
        svc = ProgramGeneratorService(engine, use_llm=False)

        program_data = svc.generate_program(
            user_profile=profile,
            goal="strength",
            total_weeks=4,
            sessions_per_week=4,
            split_type="upper_lower",
        )
        record = crud.create_program(db, program_data)
        print(f"  ✓ Program '{record.name}' created (id={record.program_id})")
        return record.program_id
    finally:
        db.close()


def seed_program(client: httpx.Client) -> str | None:
    """Prefer in-process mock generation to avoid LLM timeouts."""
    return seed_program_inprocess()


def link_program_sessions(client: httpx.Client, program_id: str) -> None:
    """Ensure the 3 most recent sessions are linked to program week 1."""
    print("🔗 Linking sessions to program week 1 …")
    r = client.get(f"/users/{DEMO_USER_ID}/sessions?limit=10")
    if r.status_code != 200:
        return
    sessions = r.json().get("sessions", [])
    # Re-log is not possible; sessions created with program_id in seed_sessions handle this.
    linked = sum(1 for s in sessions if s.get("program_id") == program_id)
    print(f"  ✓ {linked} sessions linked to program")


def print_summary(client: httpx.Client) -> None:
    print("\n" + "=" * 50)
    print("📋 Demo data summary")
    print("=" * 50)

    r = client.get(f"/users/{DEMO_USER_ID}")
    if r.status_code == 200:
        u = r.json()
        print(f"  用户: {u['user_id']} | {u['fitness_level']} | 目标: {u['fitness_goal']}")

    r = client.get(f"/users/{DEMO_USER_ID}/sessions?limit=20")
    if r.status_code == 200:
        total = r.json().get("total", 0)
        print(f"  训练记录: {total} 次")

    r = client.get(f"/users/{DEMO_USER_ID}/programs")
    if r.status_code == 200:
        programs = r.json().get("programs", [])
        for p in programs:
            print(f"  计划: {p['name']} | 第 {p['current_week']}/{p['total_weeks']} 周 | {p['status']}")

    print(f"\n  前端访问: http://localhost:3000")
    print(f"  用户 ID:  {DEMO_USER_ID}")
    print("=" * 50)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo data for AI fitness coach")
    parser.add_argument("--base-url", default=BASE_DEFAULT)
    args = parser.parse_args()

    print(f"\n🌱 Seeding demo data → {args.base_url}\n")

    try:
        with httpx.Client(base_url=args.base_url, timeout=60.0) as client:
            # Health check
            h = client.get("/health")
            if h.status_code != 200:
                print(f"❌ Backend not healthy: {h.status_code}")
                return 1

            seed_user(client)

            # Generate program first so we can link sessions
            program_id = seed_program(client)

            seed_sessions(client, program_id=program_id)

            if program_id:
                link_program_sessions(client, program_id)

            print_summary(client)

    except httpx.ConnectError:
        print(f"❌ Cannot connect to {args.base_url}")
        print("   Start backend: uvicorn main:app --reload --port 8000")
        return 1
    except httpx.HTTPStatusError as e:
        print(f"❌ HTTP error: {e.response.status_code} {e.response.text[:300]}")
        return 1

    print("\n✅ Demo data ready!\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
