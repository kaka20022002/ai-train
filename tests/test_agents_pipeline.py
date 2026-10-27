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

from agents.catalog import ExerciseCatalog
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
    """跨 Agent 的槽位字段是封闭集合。

    前五个是**决策字段**，参与谓词判定，任何一份计划都必须能被这五个字段
    完整描述；后两个是**表达性字段**（模型给的单动作要点、组间休息），
    不参与合规判定。除此之外不允许再往通道里塞东西 —— 这是「Agent 之间
    只传结构化字段」的护栏。
    """
    decision = {"exercise_id", "sets", "reps", "load_pct", "impact"}
    expressive = {"note", "rest_seconds"}
    slot = Slot(exercise_id=7, sets=3, reps="8-12", load_pct=70, impact=3)
    keys = set(slot.to_dict().keys())
    assert decision <= keys
    assert keys == decision | expressive


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


# ── 审查 Agent 的独立性 ─────────────────────────────────────────────────────
def test_safety_agent_catches_injected_forbidden(exercise_db) -> None:
    """生成 Agent 被绕过（外部注入禁忌动作）时，基线谓词必须报出来。"""
    result = run_pipeline(exercise_db, KNEE_HIGH, seed=1)
    profile = result.profile
    bad_id = sorted(profile.forbidden_reasons)[0]

    poisoned = PlanDraft(
        plan_id="poisoned",
        user_id=profile.user_id,
        workout_type="full_body",
        phases={p: list(result.draft.phases.get(p, [])) for p in PHASES},
        generator="external",
        grammar_version="catalog/1.0.0",
        profile_hash=profile.profile_hash,
    )
    poisoned.phases["main_lifts"].insert(0, Slot(bad_id, 3, "10", 50, 4))

    report = SafetyEvalAgent().evaluate(poisoned, profile, ExerciseCatalog(exercise_db))

    assert not report.passed
    assert any(v.code == "FORBIDDEN_ID" and v.exercise_id == bad_id for v in report.violations)


def test_baseline_flags_are_recorded_as_evidence(exercise_db) -> None:
    """基线命中项现在以「证据」形式存在：合规计划下应为空，且被记入报告。"""
    result = run_pipeline(exercise_db, KNEE_HIGH, seed=3)
    assert result.report.passed
    assert result.report.baseline_flags == ()
    assert result.report.review_mode == "baseline"   # 未接模型 → 降级判定
    assert result.reviewed_by_agent is False


def test_joint_cap_predicate(exercise_db) -> None:
    """基线谓词仍能算出 JOINT_CAP —— 只是它现在作为证据交给审查 Agent。"""
    index = build_exercise_index(exercise_db)
    catalog = ExerciseCatalog(exercise_db)
    profile = RiskProfile(
        user_id="u_cap",
        allowed_ids=tuple(index.keys()),
        forbidden_reasons={},
        joint_caps={"knee": 1},
        impact_ceiling=5,
        load_pct_cap=None,
    )
    squat = next(eid for eid, ex in index.items() if "knee" in ex.get("involved_joints", []))
    draft = PlanDraft(
        plan_id="p", user_id="u_cap", workout_type="full_body",
        phases={p: [] for p in PHASES} | {"main_lifts": [Slot(squat, 3, "10", 50)]},
        generator="llm", grammar_version=catalog.version,
        profile_hash=profile.profile_hash,
    )
    flags = SafetyEvalAgent._baseline_flags(draft, profile, catalog)
    assert any(f.code == "JOINT_CAP" and f.exercise_id == squat for f in flags)


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


# ── LLM 后端（用假模型验证，不需要真 key）────────────────────────────────────
def _knee_profile_and_catalog(exercise_db):
    catalog = ExerciseCatalog(exercise_db)
    profile = run_pipeline(exercise_db, KNEE_HIGH).profile
    return profile, catalog


def test_llm_backend_sees_the_whole_catalog(exercise_db) -> None:
    """v3 起没有 enum 掩码：模型看到整库，禁忌动作也在里面。"""
    profile, catalog = _knee_profile_and_catalog(exercise_db)
    captured = {}

    def fake_llm(payload, schema):
        captured["payload"] = payload
        captured["schema"] = schema
        return {}

    PlanAgent(llm_plan_fn=fake_llm).generate(profile, catalog, "full_body")

    rows = captured["payload"]["exercise_catalog"]
    ids = {row["exercise_id"] for row in rows}
    assert ids == set(catalog.ids)
    assert set(profile.forbidden_reasons) <= ids, "基线禁忌也要给模型看到"

    props = captured["schema"]["schema"]["properties"]
    for phase in PHASES:
        assert "enum" not in props[phase]["items"]["properties"]["exercise_id"]
    # 请求体里可以出现病历原文（生成端要自己判断），但不含内部规则细节
    dumped = json.dumps(captured["payload"], ensure_ascii=False)
    assert "meniscus" in dumped


def test_llm_backend_keeps_model_choices_and_flags_only_unknown_ids(exercise_db) -> None:
    """禁忌 ID 与阶段错配都放行（交给审查），只有库里没有的 ID 被丢弃。"""
    profile, catalog = _knee_profile_and_catalog(exercise_db)
    forbidden = sorted(profile.forbidden_reasons)[:2]
    good = next(row["exercise_id"] for row in catalog.rows() if "main_lifts" in row["phases"])

    def rogue_llm(payload, schema):
        return {
            "warm_up": [{"exercise_id": forbidden[0], "sets": 2, "reps": "15"}],
            "main_lifts": [
                {"exercise_id": forbidden[1], "sets": 4, "reps": "6-8"},
                {"exercise_id": good, "sets": 4, "reps": "6-8"},
                {"exercise_id": 999999, "sets": 3, "reps": "10"},
            ],
        }

    draft = PlanAgent(llm_plan_fn=rogue_llm).generate(profile, catalog, "full_body")

    assert draft.generator == "llm"
    assert set(draft.all_ids()) == {forbidden[0], forbidden[1], good}
    assert draft.rejected_ids == (999999,)

    # 放行的代价：基线会把这两条标出来，模型可以在会审里被驳回
    report = SafetyEvalAgent().evaluate(draft, profile, catalog)
    assert not report.passed
    assert {v.exercise_id for v in report.violations if v.code == "FORBIDDEN_ID"} == set(forbidden)


def test_llm_backend_falls_back_to_deterministic_on_error(exercise_db) -> None:
    profile, catalog = _knee_profile_and_catalog(exercise_db)

    def broken_llm(payload, schema):
        raise RuntimeError("api down")

    draft = PlanAgent(llm_plan_fn=broken_llm).generate(profile, catalog, "full_body", seed=1)
    assert draft.generator == "deterministic"
    assert draft.slot_count() > 0
    assert not (set(draft.all_ids()) & set(profile.forbidden_reasons))
