"""训练反馈的字段形状兼容。

规则后端把反馈翻译成强度约束（``_dynamic_limits``），这份基线同时是
**模型失败时的兜底**。所以字段名对不上 —— 例如前端提交的是疼痛量表
``{"knee": 3}``、自评强度叫 ``last_rpe`` —— 不只是「规则不够聪明」，
而是模型一旦降级就会把防护整个放掉。

这组测试锁两件事：

    1. 量表和「是/否」两种疼痛写法、``rpe`` 与 ``last_rpe`` 两种强度写法，
       都能算出同一组限额；
    2. 模型偶发返回不可解析内容时会重试一次，不把一次抖动当成最终降级。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.state_agent import StateRiskAgent

DB_PATH = Path(__file__).resolve().parent.parent / "exercise_db.json"

KNEE_HIGH = {
    "user_id": "usr_feedback_shape",
    "basic_info": {"age": 30, "gender": "male"},
    "fitness_level": "beginner",
    "medical_history": [
        {
            "location": "knee",
            "condition": "meniscus_tear",
            "severity": "high",
            "pain_trigger": "deep_flexion",
        }
    ],
}


@pytest.fixture(scope="module")
def exercise_db():
    return json.loads(DB_PATH.read_text(encoding="utf-8"))


def _analyze(exercise_db, feedback, enhance=None):
    agent = StateRiskAgent(exercise_db, llm_enhance_fn=enhance)
    return agent.analyze(KNEE_HIGH, feedback)


# ── 1. 疼痛反馈：两种写法必须等价 ────────────────────────────────────────────
def test_pain_scale_shape_tightens_limits(exercise_db) -> None:
    """前端量表 ``{"knee": 3}`` 以前读不出来，被当成无痛。"""

    profile = _analyze(exercise_db, {"pain_feedback": {"knee": 3}})

    assert profile.impact_ceiling == 3
    assert profile.load_pct_cap == 60


def test_pain_flag_shape_still_works(exercise_db) -> None:
    profile = _analyze(
        exercise_db, {"pain_feedback": {"has_pain": True, "locations": ["knee"]}}
    )

    assert profile.impact_ceiling == 3
    assert profile.load_pct_cap == 60


def test_zero_pain_scale_does_not_tighten(exercise_db) -> None:
    """全 0 表示今天不痛，不该按有痛处理。"""

    profile = _analyze(exercise_db, {"pain_feedback": {"knee": 0}})

    assert profile.impact_ceiling == 5
    assert profile.load_pct_cap is None


# ── 2. 自评强度：rpe 与 last_rpe 等价 ────────────────────────────────────────
def test_last_rpe_is_recognised(exercise_db) -> None:
    profile = _analyze(exercise_db, {"last_rpe": 8})

    assert profile.load_pct_cap == 70


def test_rpe_is_recognised(exercise_db) -> None:
    profile = _analyze(exercise_db, {"rpe": 8})

    assert profile.load_pct_cap == 70


def test_pain_beats_rpe_when_both_present(exercise_db) -> None:
    """两者同时给时取更严的那个。"""

    profile = _analyze(exercise_db, {"last_rpe": 8, "pain_feedback": {"knee": 3}})

    assert profile.impact_ceiling == 3
    assert profile.load_pct_cap == 60


def test_no_feedback_is_most_permissive(exercise_db) -> None:
    profile = _analyze(exercise_db, None)

    assert profile.impact_ceiling == 5
    assert profile.load_pct_cap is None


# ── 3. 模型抖动：重试一次，不直接降级 ────────────────────────────────────────
def test_state_agent_retries_once_before_falling_back(exercise_db) -> None:
    calls = {"n": 0}

    def flaky(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("Could not parse a JSON object from the LLM reply.")
        return {"constraints": {"impact_ceiling_override": 2}, "rationale": "重试后成功"}

    profile = _analyze(exercise_db, {"last_rpe": 8}, enhance=flaky)

    assert calls["n"] == 2
    assert profile.llm_status == "applied"
    assert profile.impact_ceiling == 2


def test_state_agent_falls_back_after_two_failures(exercise_db) -> None:
    calls = {"n": 0}

    def always_broken(payload):
        calls["n"] += 1
        raise ValueError("Could not parse a JSON object from the LLM reply.")

    profile = _analyze(exercise_db, {"last_rpe": 8}, enhance=always_broken)

    assert calls["n"] == 2
    assert profile.llm_status == "error"
    # 降级后仍然带着反馈算出的限额，而不是最宽松的 5 / 无上限
    assert profile.load_pct_cap == 70
