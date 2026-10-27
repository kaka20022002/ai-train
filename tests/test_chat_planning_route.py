"""对话内生成/修改计划的路由契约。

核心断言只有一条：**要计划的对话一定过三 Agent，问答不许偷偷跑管线**。
管线本身在 test_agents_pipeline.py 里测，这里测分派。
"""
from __future__ import annotations

import pytest

import crud
import routers.chat as chat_router
from agents.contracts import PHASES, PlanDraft, Slot
from chat_planning import PlanTurn, draft_from_record


def _fake_plan(plan_id: str = "draft_test0001") -> dict:
    return {
        "plan_id": plan_id,
        "user_id": "usr_demo",
        "date": "2026-10-27",
        "workout_type": "lower_body",
        "estimated_duration_minutes": 22,
        "phases": {
            "warm_up": [
                {
                    "name": "Bike",
                    "name_zh": "固定单车",
                    "sets": 1,
                    "reps": "5 分钟",
                    "rest_seconds": 0,
                    "target_muscle": "Multiple",
                }
            ],
            "activation": [],
            "main_lifts": [],
            "accessories": [],
            "cool_down": [],
        },
        "safety_notes": ["膝主导动作负荷 ≤50%"],
        "generator_version": "llm+catalog/1.0.0",
    }


def _make_draft(plan_id: str = "draft_seed0001") -> PlanDraft:
    draft = PlanDraft(
        plan_id=plan_id,
        user_id="usr_demo",
        workout_type="lower_body",
        phases={p: [] for p in PHASES},
        generator="llm",
        grammar_version="catalog/test",
    )
    draft.phases["main_lifts"] = [Slot(exercise_id=1, sets=3, reps="8")]
    return draft


def _fake_turn(
    agents=("state_risk", "plan_gen", "safety_eval"),
    plan_id="draft_test0001",
    draft: PlanDraft | None = None,
) -> PlanTurn:
    return PlanTurn(
        plan=_fake_plan(plan_id),
        safety={
            "passed": True,
            "review_mode": "agent",
            "violations": [],
            "risk_level": "moderate",
            "clearance": "conditional",
        },
        text="按风险报告出了一版计划：1 个动作，约 22 分钟。",
        agents_run=list(agents),
        review_rounds=0,
        elapsed_ms=1234,
        stage_ms={"pipeline": 1200},
        draft=draft,
    )


def _save_plan_with_draft(db, plan_id="draft_seed0001") -> None:
    crud.save_generated_plan(
        db,
        _fake_plan(plan_id),
        generator_version="test",
        draft_data=_make_draft(plan_id).to_dict(),
    )


class TestGenerateRoute:
    def test_plan_request_runs_three_agents(self, client, monkeypatch) -> None:
        calls = []

        def _fake(db, **kw):
            calls.append(kw["intent"].intent)
            return _fake_turn()

        monkeypatch.setattr(chat_router, "_run_plan_turn", _fake)

        resp = client.post(
            "/chat",
            json={"user_id": "usr_demo", "message": "给我一份下肢训练计划"},
        )
        assert resp.status_code == 200
        body = resp.json()

        assert calls == ["generate_plan"]
        assert body["intent"] == "generate_plan"
        assert body["plan"] is not None
        assert body["agent_trace"]["agents"] == [
            "state_risk",
            "plan_gen",
            "safety_eval",
        ]
        assert body["safety"]["passed"] is True
        assert body["assistant_message"]["content"].startswith("按风险报告")

    def test_plan_is_persisted_for_next_revision(self, client, monkeypatch) -> None:
        """生成后落库（含 draft_data），下一句「把深蹲去掉」才会被判成修订。"""
        seed = _make_draft("draft_gen00001")
        monkeypatch.setattr(
            chat_router,
            "_run_plan_turn",
            lambda db, **kw: _fake_turn(plan_id="draft_gen00001", draft=seed),
        )
        first = client.post(
            "/chat",
            json={"user_id": "usr_demo", "message": "帮我制定一个训练计划"},
        )
        assert first.json()["intent"] == "generate_plan"

        # 再问一次「改计划」应被识别为修订 —— 说明草稿真的存下来了
        resp = client.post(
            "/chat",
            json={"user_id": "usr_demo", "message": "把深蹲去掉"},
        )
        assert resp.json()["intent"] == "revise_plan"


class TestAskRoute:
    def test_question_does_not_run_pipeline(self, client, monkeypatch) -> None:
        def _boom(*args, **kwargs):
            raise AssertionError("问答不该跑三 Agent 管线")

        monkeypatch.setattr(chat_router, "_run_plan_turn", _boom)

        resp = client.post(
            "/chat",
            json={"user_id": "usr_demo", "message": "深蹲和硬拉有什么区别"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["intent"] == "ask"
        assert body["plan"] is None
        assert body["agent_trace"] is None


class TestReviseRoute:
    def test_revision_route_runs_when_draft_exists(self, client, db_session, monkeypatch) -> None:
        _save_plan_with_draft(db_session)
        seen = {}

        def _fake(db, **kw):
            seen["intent"] = kw["intent"].intent
            return _fake_turn(
                agents=("state_risk", "safety_eval"), plan_id="draft_revised01"
            )

        monkeypatch.setattr(chat_router, "_run_plan_turn", _fake)

        resp = client.post(
            "/chat",
            json={"user_id": "usr_demo", "message": "把深蹲去掉"},
        )
        body = resp.json()
        assert seen["intent"] == "revise_plan"
        assert body["intent"] == "revise_plan"
        assert body["agent_trace"]["agents"] == ["state_risk", "safety_eval"]
        assert body["plan"]["plan_id"] == "draft_revised01"

    def test_revision_without_draft_falls_back_to_generate(
        self, client, db_session, monkeypatch
    ) -> None:
        """老计划没有 draft_data —— 改不动，只能重新生成（仍然过三 Agent）。"""
        assert draft_from_record(None) is None
        seen = {}

        def _fake(db, **kw):
            seen["draft"] = chat_router._revisable_draft(db, kw["user_id"])
            return _fake_turn()

        monkeypatch.setattr(chat_router, "_run_plan_turn", _fake)
        resp = client.post(
            "/chat",
            json={"user_id": "usr_demo", "message": "帮我改一下计划，换几个动作"},
        )
        # 没有草稿 → 分类为 generate（"帮我…计划"命中生成规则）
        assert resp.json()["intent"] == "generate_plan"
        assert seen["draft"] is None


class TestPipelineFailure:
    def test_failure_falls_back_to_coach(self, client, monkeypatch) -> None:
        monkeypatch.setattr(chat_router, "_run_plan_turn", lambda db, **kw: None)
        resp = client.post(
            "/chat",
            json={"user_id": "usr_demo", "message": "给我一份训练计划"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["plan"] is None
        # 仍如实记录这一轮被判定为「要计划」
        assert body["intent"] == "generate_plan"
        assert body["assistant_message"]["content"]
