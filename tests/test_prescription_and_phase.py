# -*- coding: utf-8 -*-
"""处方推导与阶段过滤的回归测试。

这一组锁住 v2 的两处质量改进，防止后续改动把它们悄悄退回去：

1. **阶段硬过滤**：热身段只能选到热身动作，放松段只能选到拉伸动作。
   原实现的"类型偏好排序"会把不匹配的动作追加在末尾，等于没过滤。
2. **处方推导**：参数由「动作类型 × 阶段」决定，而不是五张固定常量表。
   拉伸必须给秒数、等长必须标记 timed、自重动作不得标注负荷百分比。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.contracts import PHASES
from agents.grammar import build_exercise_index, compile_risk_grammar
from agents.pipeline import run_pipeline
from agents.plan_agent import PlanAgent, pick_diverse
from agents.prescription import is_bodyweight, prescribe
from agents.render import render_plan_draft

DB_PATH = Path(__file__).resolve().parent.parent / "exercise_db.json"

KNEE_HIGH = {
    "user_id": "u_test_knee",
    "basic_info": {"age": 28, "gender": "male"},
    "fitness_level": "beginner",
    "medical_history": [
        {"location": "knee", "condition": "meniscus_tear", "severity": "high"}
    ],
}

HEALTHY = {
    "user_id": "u_test_healthy",
    "basic_info": {"age": 26, "gender": "male"},
    "fitness_level": "intermediate",
    "medical_history": [],
}

MULTI = {
    "user_id": "u_test_multi",
    "basic_info": {"age": 41, "gender": "female"},
    "fitness_level": "beginner",
    "medical_history": [
        {"location": "knee", "condition": "meniscus_tear", "severity": "high"},
        {"location": "shoulder", "condition": "shoulder_impingement", "severity": "low"},
        {"location": "spine", "condition": "lumbar_herniation", "severity": "low"},
    ],
}


@pytest.fixture(scope="module")
def exercise_db():
    return json.loads(DB_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def index(exercise_db):
    return build_exercise_index(exercise_db)


# ── 阶段硬过滤 ────────────────────────────────────────────────────────────
def test_every_exercise_declares_a_valid_phase(exercise_db) -> None:
    valid = set(PHASES)
    for ex in exercise_db:
        assert ex.get("phase"), f"{ex['name']} 缺 phase 字段"
        assert set(ex["phase"]) <= valid, f"{ex['name']} phase 非法: {ex['phase']}"


def test_warm_up_candidates_are_warmups_only(exercise_db, index) -> None:
    """热身段候选必须全是动态热身/活动度动作，不能混进力量动作。"""
    profile = run_pipeline(exercise_db, KNEE_HIGH).profile
    grammar = compile_risk_grammar(profile, index)

    pool = grammar.candidates("warm_up")
    assert pool, "热身段候选不应为空"
    for eid in pool:
        etype = index[eid]["type"]
        assert etype == "Warmup", f"热身段混入了 {index[eid]['name']} ({etype})"


def test_cool_down_candidates_are_stretches_only(exercise_db, index) -> None:
    """放松段候选必须全是静态拉伸。"""
    profile = run_pipeline(exercise_db, KNEE_HIGH).profile
    grammar = compile_risk_grammar(profile, index)

    pool = grammar.candidates("cool_down")
    assert pool, "放松段候选不应为空"
    for eid in pool:
        etype = index[eid]["type"]
        assert etype == "Stretch", f"放松段混入了 {index[eid]['name']} ({etype})"


def test_main_lifts_candidates_are_compound_only(exercise_db, index) -> None:
    profile = run_pipeline(exercise_db, KNEE_HIGH).profile
    grammar = compile_risk_grammar(profile, index)

    pool = grammar.candidates("main_lifts")
    assert pool
    for eid in pool:
        assert index[eid]["type"] == "Compound", index[eid]["name"]


def test_generated_phases_respect_their_type_contract(exercise_db, index) -> None:
    """实际生成的计划，每个阶段的动作类型都要符合该阶段语义。"""
    expected = {
        "warm_up": {"Warmup"},
        "cool_down": {"Stretch"},
        "main_lifts": {"Compound"},
    }
    result = run_pipeline(exercise_db, MULTI, seed=7)
    for phase, allowed in expected.items():
        for slot in result.draft.phases[phase]:
            etype = index[slot.exercise_id]["type"]
            assert etype in allowed, f"{phase} 出现 {index[slot.exercise_id]['name']} ({etype})"


def test_phase_mismatch_is_left_to_the_reviewer(exercise_db, index) -> None:
    """v3 起解析层不再挡「阶段错配」，改由审查 Agent 判 SEQUENCE。

    这里只锁「模型放进去的东西原样保留」—— 判定权在 safety_agent，
    对应测试见 test_agent_llm.py::test_review_rejects_phase_mismatch。
    """
    from agents.catalog import ExerciseCatalog

    profile = run_pipeline(exercise_db, KNEE_HIGH).profile
    catalog = ExerciseCatalog(exercise_db)
    stretch_id = next(
        row["exercise_id"] for row in catalog.rows() if row["type"] == "Stretch"
    )

    def rogue(payload, schema):
        return {
            "main_lifts": [
                {"exercise_id": stretch_id, "sets": 4, "reps": "6-8", "impact": 1}
            ]
        }

    draft = PlanAgent(llm_plan_fn=rogue).generate(profile, catalog, "full_body")
    assert [s.exercise_id for s in draft.phases["main_lifts"]] == [stretch_id]
    assert draft.rejected_ids == ()


# ── 处方推导 ──────────────────────────────────────────────────────────────
def test_stretch_prescription_is_timed_and_unloaded(exercise_db) -> None:
    meta = next(e for e in exercise_db if e["type"] == "Stretch")
    p = prescribe("cool_down", meta, None)
    assert p.timed is True
    assert "秒" in p.reps
    assert p.load_pct is None
    assert p.sets == 1


def test_isometric_prescription_is_timed(exercise_db) -> None:
    meta = next(e for e in exercise_db if e["type"] == "Isometric")
    p = prescribe("accessories", meta, None)
    assert p.timed is True
    assert "秒" in p.reps


def test_bodyweight_actions_carry_no_load_percentage(exercise_db) -> None:
    """俯卧撑没有 1RM 可言，不该标 75%。"""
    pushup = next(e for e in exercise_db if e["name"] == "Push-Up")
    assert is_bodyweight(pushup)
    p = prescribe("main_lifts", pushup, None)
    assert p.load_pct is None


def test_barbell_compound_gets_heavy_low_rep_prescription(exercise_db) -> None:
    bench = next(e for e in exercise_db if e["name"] == "Barbell Bench Press")
    p = prescribe("main_lifts", bench, None)
    assert p.load_pct == 75
    assert "6-8" in p.reps
    assert p.sets == 4


def test_load_cap_tightens_prescription(exercise_db) -> None:
    bench = next(e for e in exercise_db if e["name"] == "Barbell Bench Press")
    p = prescribe("main_lifts", bench, load_cap=50)
    assert p.load_pct == 50


def test_rendered_plan_variants_have_reasonable_duration(exercise_db, index) -> None:
    result = run_pipeline(exercise_db, KNEE_HIGH, seed=11)
    rendered = render_plan_draft(result.draft, index, result.profile, result.report)
    # 五个阶段各 3-4 个动作，含热身拉伸，40 分钟左右是合理的
    assert 25 <= rendered["estimated_duration_minutes"] <= 75
    # 拉伸的休息时间应短于主项的休息时间
    assert rendered["phases"]["cool_down"][0]["rest_seconds"] < rendered["phases"]["main_lifts"][0]["rest_seconds"]


def test_rendered_plan_exposes_chinese_names(exercise_db, index) -> None:
    result = run_pipeline(exercise_db, KNEE_HIGH, seed=11)
    rendered = render_plan_draft(result.draft, index, result.profile, result.report)
    for slots in rendered["phases"].values():
        for it in slots:
            assert it["name_zh"], f"{it['name']} 缺中文名"


# ── 编排质量 ──────────────────────────────────────────────────────────────
def test_pick_diverse_prefers_distinct_patterns(index) -> None:
    """同一阶段内优先覆盖不同动作模式，避免三个弯举。"""
    # 23/24/25 都是 elbow_flexion 模式
    pool = [23, 24, 25, 27, 13]
    picked = pick_diverse(pool, 3, index)
    patterns = {index[e].get("motion_pattern") for e in picked}
    assert len(patterns) == 3, f"模式重复: {[index[e]['name'] for e in picked]}"


def test_all_phases_filled_for_every_profile(exercise_db) -> None:
    """三类档案都必须填满五个阶段，不能出现残缺计划。"""
    for profile in (HEALTHY, KNEE_HIGH, MULTI):
        result = run_pipeline(exercise_db, profile, seed=3)
        for phase in PHASES:
            assert result.draft.phases[phase], f"{profile['user_id']} 的 {phase} 为空"


def test_plan_never_contains_forbidden_across_profiles(exercise_db) -> None:
    for profile in (HEALTHY, KNEE_HIGH, MULTI):
        result = run_pipeline(exercise_db, profile, seed=5)
        planned = {s.exercise_id for _, s in result.draft.iter_slots()}
        assert not (planned & set(result.profile.forbidden_reasons))
