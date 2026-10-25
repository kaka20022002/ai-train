"""多 Agent 计划生成管线的回归测试。

重点锁住三件事：
  1. 禁忌动作不可能出现在计划里（文法裁剪 + 对抗探针）
  2. Agent 之间只传结构化字段（Slot 就是那五个字段）
  3. 评估 Agent 能独立发现问题（不依赖生成 Agent 自检）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.contracts import PHASES, PlanDraft, RiskProfile, Slot
from agents.grammar import build_exercise_index, compile_risk_grammar
from agents.pipeline import run_pipeline
from agents.plan_agent import PlanAgent
from agents.safety_agent import SafetyEvalAgent

DB_PATH = Path(__file__).resolve().parent.parent / "exercise_db.json"


@pytest.fixture(scope="module")
def exercise_db():
    return json.loads(DB_PATH.read_text(encoding="utf-8"))


KNEE_HIGH = {
    "user_id": "t_knee_high",
    "basic_info": {"age": 30, "gender": "male"},
    "fitness_level": "beginner",
    "medical_history": [
        {"location": "knee", "condition": "meniscus_tear", "severity": "high"}
    ],
}

HEALTHY = {
    "user_id": "t_healthy",
    "basic_info": {"age": 25, "gender": "female"},
    "fitness_level": "intermediate",
    "medical_history": [],
}


# ── 契约 ────────────────────────────────────────────────────────────────────
def test_slot_carries_only_structured_fields() -> None:
    slot = Slot(exercise_id=7, sets=3, reps="8-12", load_pct=70, impact=3)
    assert set(slot.to_dict().keys()) == {"exercise_id", "sets", "reps", "load_pct", "impact"}


def test_plan_draft_roundtrip() -> None:
    draft = PlanDraft(
        plan_id="p1",
        user_id="u1",
        workout_type="full_body",
        phases={p: [Slot(i + 1, 3, "10", 50, 2)] for i, p in enumerate(PHASES)},
        generator="deterministic",
        grammar_version="grammar/1.0.0",
        profile_hash="abc",
    )
    again = PlanDraft.from_dict(draft.to_dict())
    assert again.to_dict() == draft.to_dict()


# ── 文法裁剪 ────────────────────────────────────────────────────────────────
def test_grammar_masks_forbidden_ids(exercise_db) -> None:
    index = build_exercise_index(exercise_db)
    result = run_pipeline(exercise_db, KNEE_HIGH)
    profile = result.profile
    grammar = compile_risk_grammar(profile, index)

    assert profile.forbidden_reasons, "膝伤 HIGH 应当至少禁掉一个动作"
    assert not (set(profile.allowed_ids) & set(profile.forbidden_reasons))
    assert grammar.stats()["masked"] == len(profile.forbidden_reasons)


def test_candidates_never_include_forbidden(exercise_db) -> None:
    index = build_exercise_index(exercise_db)
    result = run_pipeline(exercise_db, KNEE_HIGH)
    profile = result.profile
    grammar = compile_risk_grammar(profile, index)
    for phase in PHASES:
        pool = set(grammar.candidates(phase))
        assert not (pool & set(profile.forbidden_reasons)), phase


def test_generated_plan_is_violation_free(exercise_db) -> None:
    result = run_pipeline(exercise_db, KNEE_HIGH, seed=42)
    assert result.report.passed, [v.to_dict() for v in result.report.violations]
    assert not (set(result.draft.all_ids()) & set(result.profile.forbidden_reasons))
    assert result.draft.slot_count() > 0


def test_pipeline_is_deterministic_with_seed(exercise_db) -> None:
    a = run_pipeline(exercise_db, KNEE_HIGH, seed=7)
    b = run_pipeline(exercise_db, KNEE_HIGH, seed=7)
    assert a.draft.all_ids() == b.draft.all_ids()


# ── 评估 Agent 的独立性 ─────────────────────────────────────────────────────
def test_safety_agent_catches_injected_forbidden(exercise_db) -> None:
    """生成 Agent 被绕过（外部注入禁忌动作）时，评估 Agent 必须拦下。"""
    result = run_pipeline(exercise_db, KNEE_HIGH, seed=1)
    profile = result.profile
    bad_id = sorted(profile.forbidden_reasons)[0]

    poisoned = PlanDraft(
        plan_id="poisoned",
        user_id=profile.user_id,
        workout_type="full_body",
        phases={p: list(result.draft.phases.get(p, [])) for p in PHASES},
        generator="external",
        grammar_version="grammar/1.0.0",
        profile_hash=profile.profile_hash,
    )
    poisoned.phases["main_lifts"].insert(0, Slot(bad_id, 3, "10", 50, 4))

    grammar = compile_risk_grammar(profile, build_exercise_index(exercise_db))
    report = SafetyEvalAgent().evaluate(poisoned, profile, grammar)

    assert not report.passed
    assert any(v.code == "FORBIDDEN_ID" and v.exercise_id == bad_id for v in report.violations)


def test_adversarial_probe_blocks_everything(exercise_db) -> None:
    result = run_pipeline(exercise_db, KNEE_HIGH, seed=3)
    assert result.report.adversarial_probes > 0
    assert result.report.adversarial_blocked == result.report.adversarial_probes


def test_joint_cap_predicate(exercise_db) -> None:
    index = build_exercise_index(exercise_db)
    # 人为把 knee 上限压到 1，深蹲(risk 4)应触发 JOINT_CAP
    profile = RiskProfile(
        user_id="u_cap",
        allowed_ids=tuple(index.keys()),
        forbidden_reasons={},
        joint_caps={"knee": 1},
        impact_ceiling=5,
        load_pct_cap=None,
    )
    grammar = compile_risk_grammar(profile, index)
    squat = next(eid for eid, ex in index.items() if "knee" in ex.get("involved_joints", []))
    v = grammar.validate(Slot(squat, 3, "10", 50, grammar.impact_of(squat)), "main_lifts")
    assert v is not None and v.code == "JOINT_CAP"


def test_load_pct_cap_applied_from_feedback(exercise_db) -> None:
    result = run_pipeline(
        exercise_db,
        KNEE_HIGH,
        feedback={"rpe": 9, "completion_rate": 0.5, "pain_feedback": {"has_pain": True}},
        seed=11,
    )
    assert result.profile.load_pct_cap == 60
    for _, slot in result.draft.iter_slots():
        if slot.load_pct is not None:
            assert slot.load_pct <= 60


# ── 审计 ────────────────────────────────────────────────────────────────────
def test_audit_is_structured_and_ordered(exercise_db) -> None:
    result = run_pipeline(exercise_db, HEALTHY, seed=5)
    audit = result.audit.to_dict()
    stages = [e["stage"] for e in audit["entries"]]
    assert stages[:3] == ["state_risk", "plan_gen", "safety_eval"]
    # 全部可 JSON 序列化，且不带自然语言长文本
    dumped = json.dumps(audit, ensure_ascii=False)
    assert len(dumped) < 20000
    for entry in audit["entries"]:
        assert set(entry.keys()) == {"seq", "stage", "in", "out"}


def test_healthy_user_gets_richer_plan_than_injured(exercise_db) -> None:
    healthy = run_pipeline(exercise_db, HEALTHY, seed=5)
    injured = run_pipeline(exercise_db, KNEE_HIGH, seed=5)
    assert len(healthy.profile.allowed_ids) > len(injured.profile.allowed_ids)
    assert injured.report.passed and healthy.report.passed
