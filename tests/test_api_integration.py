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

    assert "+catalog/" in data["generator_version"]
    safety = data["safety"]
    assert safety is not None, "engine=agents 必须返回 safety"
    assert safety["passed"] is True
    assert safety["checked_slots"] > 0
    # 无 key 时如实标注「未经 Agent 审查」，而不是假装审查通过
    assert safety["review_mode"] == "baseline"
    assert safety["review_rounds"] == 0
    assert safety["baseline_flags"] == []
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


def test_pain_feedback_without_location_does_not_500(client) -> None:
    """回归：pain_feedback 只给 has_pain=true 时不得 500。

    线上真实路径里 feedback 由 Pydantic `model_dump()` 产出，未填写的字段会
    以 **None** 出现（而不是缺键）。旧实现用 `.get(k, default)` 取值，
    default 永远不生效，`pain_location.upper()` 直接把请求打成 500。
    """
    payload = {
        "user_profile": KNEE_HIGH_PAYLOAD["user_profile"],
        "feedback": {
            "session_id": "sess_pain_only",
            "user_id": "usr_api_agents",
            "date": "2026-10-26",
            "rpe": 8,
            "pain_feedback": {"has_pain": True, "locations": ["knee"]},
        },
        "workout_type": "full_body",
    }
    resp = client.post("/generate_plan", json=payload)
    assert resp.status_code == 200, resp.text

    data = resp.json()
    assert data["safety"]["passed"] is True
    # 疼痛反馈应把整体冲击上限压到 3
    assert data["audit"][0]["out"]["impact_ceiling"] == 3


def test_agents_pipeline_uses_one_key_three_prompts(client, monkeypatch) -> None:
    """装上三个 LLM 入口后，/generate_plan 必须真的走 LLM 且合规性不变。

    模拟的是「只配了一个 API Key」的真实情形：一个 client，三份 prompt。
    这里用假 client 替掉网络调用，只验证装配层与响应字段是否正确接线。
    """
    import main
    from agents import build_bridges

    class FakeClient:
        def __init__(self) -> None:
            self.systems: list[str] = []

        def chat_json(self, system_prompt: str, user_prompt: str):
            self.systems.append(system_prompt)
            if "力量与体能教练" in system_prompt:
                blob = user_prompt[user_prompt.index("{") : user_prompt.rindex("}") + 1]
                payload = json.loads(blob)
                rows = payload["exercise_catalog"]
                blocked = {
                    item["exercise_id"]
                    for item in payload["baseline"]["forbidden_exercises"]
                }
                picked: dict[str, list[dict]] = {}
                for phase in ("warm_up", "activation", "main_lifts",
                              "accessories", "cool_down"):
                    candidates = [
                        r for r in rows
                        if phase in r["phases"] and r["exercise_id"] not in blocked
                    ]
                    if candidates:
                        # 模拟模型给完整槽位（组次负荷 + 要点 + 休息）
                        row = candidates[0]
                        picked[phase] = [
                            {
                                "exercise_id": row["exercise_id"],
                                "sets": 2,
                                "reps": "30" if row.get("timed") else "10",
                                "load_pct": None,
                                "rest_seconds": 30,
                                "note": f"模型选择 {row['name']}",
                            }
                        ]
                return picked
            if "运动医学筛查" in system_prompt:
                return {"additional_forbidden": [], "rationale": "规则已覆盖"}
            if "独立的安全审查员" in system_prompt:
                return {"verdict": "pass", "violations": [], "rationale": "未发现违规"}
            raise AssertionError(f"出现了未预期的 prompt: {system_prompt[:40]}")

    fake = FakeClient()
    monkeypatch.setattr(main, "AGENT_BRIDGES", build_bridges(fake))

    resp = client.post("/generate_plan", json=KNEE_HIGH_PAYLOAD)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # 一个 key、三份不同 prompt
    assert len(fake.systems) >= 3
    assert len({s[:60] for s in fake.systems}) >= 3

    # 生成确实走了 LLM
    assert data["generator_version"].startswith("llm+")

    # 响应里带回三个 Agent 的状态
    safety = data["safety"]
    assert safety["llm_verdict"] == "pass"
    assert safety["llm_disagreed"] is False
    assert safety["state_llm_status"] in ("empty", "applied")
    assert safety["llm_prompt_version"].startswith("safety_eval/")
    assert safety["passed"] is True

    # 结论由审查 Agent 给出（不再是「规则 + 模型取合取」）
    assert safety["review_mode"] == "agent"
    assert safety["llm_rationale"]
    assert safety["passed"] is True


def test_model_decisions_reach_the_response(client, monkeypatch) -> None:
    """模型给出的组次负荷与动作要点，必须出现在最终响应里。

    这是 v3「模型主决策」的接线验证：如果响应里的 sets/reps/notes 全是
    处方模板值，说明模型输出在某一层被丢掉了。
    """
    import main
    from agents import build_bridges

    def fake_client():
        class FakeClient:
            def chat_json(self, system_prompt: str, user_prompt: str):
                if "力量与体能教练" in system_prompt:
                    blob = user_prompt[user_prompt.index("{") : user_prompt.rindex("}") + 1]
                    payload = json.loads(blob)
                    rows = payload["exercise_catalog"]
                    out: dict[str, list[dict]] = {}
                    for phase in ("warm_up", "activation", "main_lifts",
                                  "accessories", "cool_down"):
                        candidates = [r for r in rows if phase in r["phases"]]
                        if not candidates:
                            continue
                        row = candidates[0]
                        out[phase] = [
                            {
                                "exercise_id": row["exercise_id"],
                                "sets": 2,
                                "reps": "25" if row.get("timed") else "9",
                                "load_pct": None,
                                "rest_seconds": 45,
                                "note": f"模型提示：{row['name']}",
                            }
                        ]
                    return out
                if "运动医学筛查" in system_prompt:
                    return {
                        "avoid_patterns": ["squat"],
                        "session_cap_minutes": 45,
                        "progression_note": "先恢复活动度",
                        "rationale": "病历提到深蹲疼痛",
                    }
                if "独立的安全审查员" in system_prompt:
                    return {"verdict": "pass", "violations": [], "rationale": "剂量保守"}
                raise AssertionError(system_prompt[:40])

        return FakeClient()

    monkeypatch.setattr(main, "AGENT_BRIDGES", build_bridges(fake_client()))

    resp = client.post("/generate_plan", json=KNEE_HIGH_PAYLOAD)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    safety = data["safety"]
    # Agent 1 的语义抽取接到了响应
    assert safety["avoid_patterns"] == ["squat"]
    assert safety["session_cap_minutes"] == 45
    assert "恢复活动度" in safety["progression_note"]
    assert safety["state_llm_status"] == "applied"

    # 模型的休息时长与要点接到了响应
    warm = data["phases"]["warm_up"]
    assert warm, "热身段不应为空"
    assert warm[0]["rest_seconds"] == 45
    assert warm[0]["notes"].startswith("模型提示：")

    # 模型给的参数原样落库，不再被夹紧（本次全部在参考区间内，故为 0）
    assert safety["adjusted_slots"] == 0
    # 三个 Agent 的痕迹都在
    assert safety["review_mode"] == "agent"
    assert safety["llm_verdict"] == "pass"


def test_full_profile_and_query_reach_the_pipeline(client) -> None:
    """完整档案 + 一句话需求经 HTTP 抵达 Agent 层，且器械缺失被执行。"""
    payload = {
        "user_profile": {
            "user_id": "ctx_http",
            "basic_info": {"age": 34, "gender": "male"},
            "fitness_level": "intermediate",
            "fitness_goal": "strength",
            "training_frequency": 2,
            "available_equipment": ["bodyweight", "dumbbell"],
            "preferences": {
                "liked_patterns": ["hinge"],
                "disliked_patterns": ["core"],
                "disliked_exercises": ["Burpee"],
                "notes": "讨厌憋气式大重量",
            },
            "medical_history": [
                {
                    "location": "knee",
                    "condition": "meniscus_tear",
                    "severity": "high",
                    "notes": "蹲到底膝内侧刺痛",
                }
            ],
        },
        "workout_type": "lower_body",
        "query": "今天只有三十分钟，想练下肢",
    }
    resp = client.post("/generate_plan", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # 需求原话进入了状态分析阶段
    state_audit = data["audit"][0]
    assert state_audit["in"]["query"] == "今天只有三十分钟，想练下肢"
    assert state_audit["in"]["workout_type"] == "lower_body"

    # 完整上下文被记录下来（偏好在前，器械在后）
    ctx = state_audit["out"]["user_context"]
    assert ctx["fitness_goal"] == "strength"
    assert ctx["preferences"]["disliked_exercises"] == ["Burpee"]
    assert ctx["available_equipment"] == ["bodyweight", "dumbbell"]

    # 器械缺失真的排除了动作 —— 不是只记一笔
    assert state_audit["out"]["equipment_blocked"] > 0
    assert data["safety"]["passed"] is True

    # 只给自重+哑铃时，需要杠铃/绳索的动作不该出现在计划里
    index = {ex["name"]: ex for ex in _exercise_rows(data)}
    for slots in data["phases"].values():
        for ex in slots:
            gear = (index.get(ex["name"]) or {}).get("required_equipment") or []
            assert not [g for g in gear if g not in {"bodyweight", "dumbbell"}], ex["name"]


def _exercise_rows(data):
    """从计划里反查动作元信息（用于器械断言）。"""
    import json as _json
    from pathlib import Path

    db = _json.loads(Path("exercise_db.json").read_text(encoding="utf-8"))
    return [{"name": ex.get("name"), "required_equipment": [
        str(g).lower() for g in (ex.get("required_equipment") or [])
    ]} for ex in db]
