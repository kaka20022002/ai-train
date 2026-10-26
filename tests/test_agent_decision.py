"""验证 v3 的权力结构：模型决策、规则兜底。

这组测试锁的是三件事：
    1. 模型给出的 sets / reps / load / rest / note **确实被采纳** ——
       否则「让大模型来」只是一句口号；
    2. 模型越界时参数被**夹紧**而不是静默丢弃，且计数进 ``adjusted_slots``；
    3. 兜底层依然完整 —— 禁忌 ID、阶段错配、非法参数进不了最终计划。
"""
from __future__ import annotations

import pytest

from agents.contracts import Slot
from agents.grammar import build_exercise_index, compile_risk_grammar
from agents.plan_agent import PlanAgent
from agents.prescription import prescription_bounds
from agents.state_agent import StateRiskAgent

KNEE_HIGH = {
    "user_id": "t_knee",
    "basic_info": {"age": 28, "gender": "male"},
    "fitness_level": "beginner",
    "medical_history": [
        {
            "location": "knee",
            "condition": "meniscus_tear",
            "severity": "high",
            "notes": "术后两年，深蹲到底时膝内侧刺痛",
        }
    ],
}


@pytest.fixture()
def env(risk_engine):
    db = risk_engine.exercise_db
    index = build_exercise_index(db)
    profile = StateRiskAgent(db).analyze(KNEE_HIGH, None)
    grammar = compile_risk_grammar(profile, index)
    return db, index, profile, grammar


def _first(rows, **want):
    for row in rows:
        if all(row.get(k) == v for k, v in want.items()):
            return row
    return None


# ── 模型决策权 ──────────────────────────────────────────────────────────────
def test_model_supplied_params_are_adopted(env) -> None:
    """模型给在区间内的参数，必须原样出现在计划里。"""
    _, _, profile, grammar = env
    captured = {}

    def fake_plan(payload, schema):
        warm = payload["phase_candidates"]["warm_up"]
        target = warm[0]
        captured["id"] = target["exercise_id"]
        # 完全按模型自己的判断给参数（Wrapup 区间 1-2 组 / 8-15 次 / 无负荷）
        return {
            "warm_up": [
                {
                    "exercise_id": target["exercise_id"],
                    "sets": 2,
                    "reps": "14",
                    "load_pct": None,
                    "rest_seconds": 25,
                    "note": "髋部还没热开，先小幅活动",
                }
            ]
        }

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, grammar, "full_body")
    slot = draft.phases["warm_up"][0]

    assert draft.generator == "llm"
    assert slot.exercise_id == captured["id"]
    assert (slot.sets, slot.reps, slot.load_pct) == (2, "14 次", None)
    assert slot.rest_seconds == 25
    assert slot.note == "髋部还没热开，先小幅活动"
    assert draft.adjusted_slots == 0


def test_model_load_pct_is_adopted_for_compound(env) -> None:
    """主项复合动作的负荷百分比由模型决定，规则只保证在区间内。"""
    _, _, profile, grammar = env

    def fake_plan(payload, schema):
        rows = payload["phase_candidates"]["main_lifts"]
        target = next((r for r in rows if not r.get("bodyweight")), None)
        if target is None:
            return {}
        b = prescription_bounds("main_lifts", grammar.index[target["exercise_id"]],
                                profile.load_pct_cap)
        # 选区间上限，模拟模型判断「这位用户今天状态好」
        return {
            "main_lifts": [
                {
                    "exercise_id": target["exercise_id"],
                    "sets": b.sets_max,
                    "reps": str(b.reps_max),
                    "load_pct": b.load_max,
                    "rest_seconds": 120,
                    "note": "状态好，顶到上限",
                }
            ]
        }

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, grammar, "full_body")
    slot = draft.phases["main_lifts"][0]
    b = prescription_bounds("main_lifts", grammar.index[slot.exercise_id],
                            profile.load_pct_cap)
    assert slot.sets == b.sets_max
    assert slot.load_pct == b.load_max
    assert draft.adjusted_slots == 0


# ── 规则兜底 ────────────────────────────────────────────────────────────────
def test_out_of_range_params_are_clamped_not_dropped(env) -> None:
    """越界参数被夹到边界，动作本身保留 —— 夹紧比丢弃更符合「模型主决策」。"""
    _, _, profile, grammar = env

    def fake_plan(payload, schema):
        target = payload["phase_candidates"]["warm_up"][0]
        return {
            "warm_up": [
                {
                    "exercise_id": target["exercise_id"],
                    "sets": 99,
                    "reps": "500",
                    "load_pct": 300,
                    "rest_seconds": 9999,
                    "note": "明显越界",
                }
            ]
        }

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, grammar, "full_body")
    slot = draft.phases["warm_up"][0]
    b = prescription_bounds("warm_up", grammar.index[slot.exercise_id], profile.load_pct_cap)

    assert slot.sets == b.sets_max
    assert slot.load_pct is None          # 热身动作不允许标负荷，越界的丢掉了
    assert slot.rest_seconds == 300       # 夹到上限
    assert draft.adjusted_slots >= 1
    # 夹紧之后必须能通过谓词校验
    assert grammar.validate(slot, "warm_up") is None


def test_forbidden_id_from_model_is_rejected(env) -> None:
    """模型幻觉出一个禁忌动作，依然进不了 draft。"""
    _, _, profile, grammar = env
    forbidden_id = sorted(profile.forbidden_reasons)[0]

    def fake_plan(payload, schema):
        return {
            "main_lifts": [
                {"exercise_id": forbidden_id, "sets": 3, "reps": "8", "load_pct": 70}
            ]
        }

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, grammar, "full_body")
    assert forbidden_id not in draft.all_ids()
    assert forbidden_id in draft.rejected_ids


def test_phase_mismatch_is_rejected(env) -> None:
    """把放松类动作塞进主项段，ID 合法也要挡回。"""
    _, _, profile, grammar = env
    cool = grammar.candidates("cool_down")
    assert cool, "放松段应有候选"

    def fake_plan(payload, schema):
        return {
            "main_lifts": [
                {"exercise_id": cool[0], "sets": 3, "reps": "8", "load_pct": 70}
            ]
        }

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, grammar, "full_body")
    # 该动作被主项段拒绝（进了 rejected_ids），但它本身是合法的放松动作，
    # 补位时仍可能出现在 cool_down 段 —— 所以只断言它没进主项段。
    assert cool[0] not in [s.exercise_id for s in draft.phases["main_lifts"]]
    assert cool[0] in draft.rejected_ids


def test_missing_params_fall_back_to_prescription(env) -> None:
    """模型只给 ID 不给参数时，用处方推荐值兜底，而不是给出非法默认。"""
    _, _, profile, grammar = env

    def fake_plan(payload, schema):
        target = payload["phase_candidates"]["warm_up"][0]
        return {"warm_up": [{"exercise_id": target["exercise_id"]}]}

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, grammar, "full_body")
    slot = draft.phases["warm_up"][0]
    assert slot.sets >= 1 and slot.reps.endswith("次")
    assert grammar.validate(slot, "warm_up") is None
    assert draft.adjusted_slots >= 1


def test_short_phase_is_topped_up(env) -> None:
    """模型给了但数量不足时，由文法补满，保证计划可用。"""
    _, _, profile, grammar = env

    def fake_plan(payload, schema):
        target = payload["phase_candidates"]["activation"][0]
        return {
            "activation": [
                {"exercise_id": target["exercise_id"], "sets": 2, "reps": "12"}
            ]
        }

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, grammar, "full_body")
    assert len(draft.phases["activation"]) >= 2
    for slot in draft.phases["activation"]:
        assert grammar.validate(slot, "activation") is None


# ── 区间校验 ────────────────────────────────────────────────────────────────
def test_prescription_range_violation_code(env) -> None:
    """手工构造越界槽位，谓词必须报 PRESCRIPTION_RANGE。"""
    _, _, _, grammar = env
    eid = grammar.candidates("cool_down")[0]
    b = prescription_bounds("cool_down", grammar.index[eid], None)

    bad_sets = Slot(exercise_id=eid, sets=b.sets_max + 5, reps=f"{b.reps_min} 秒", impact=1)
    v = grammar.validate(bad_sets, "cool_down")
    assert v is not None and v.code == "PRESCRIPTION_RANGE"

    bad_reps = Slot(exercise_id=eid, sets=b.sets_min, reps="999 秒", impact=1)
    v2 = grammar.validate(bad_reps, "cool_down")
    assert v2 is not None and v2.code == "PRESCRIPTION_RANGE"


def test_stretch_must_not_carry_load(env) -> None:
    """拉伸给了负荷百分比 → 区间违规。"""
    _, _, _, grammar = env
    eid = grammar.candidates("cool_down")[0]
    b = prescription_bounds("cool_down", grammar.index[eid], None)
    slot = Slot(exercise_id=eid, sets=b.sets_min, reps=f"{b.reps_min} 秒",
                load_pct=50, impact=1)
    v = grammar.validate(slot, "cool_down")
    assert v is not None and v.code == "PRESCRIPTION_RANGE"


# ── 语义约束（avoid_patterns / session cap）─────────────────────────────────
def test_avoid_patterns_removes_candidates(env) -> None:
    """模式禁忌把整类动作从候选池里物理移除。"""
    _, index, profile, grammar = env
    squat_ids = [
        eid for eid, meta in index.items()
        if str(meta.get("motion_pattern") or "").lower() == "squat"
    ]
    assert squat_ids, "动作库应包含 squat 模式"

    from dataclasses import replace
    blocked = replace(profile, avoid_patterns=("squat",), profile_hash="")
    g2 = compile_risk_grammar(blocked, index)

    remaining = set()
    for phase in ("warm_up", "activation", "main_lifts", "accessories", "cool_down"):
        remaining.update(g2.candidates(phase, allow_fallback=True))
    assert not (set(squat_ids) & remaining)


def test_session_cap_reaches_plan_payload(env) -> None:
    """时长上限从档案一路传到生成 Agent 的请求体。"""
    _, _, profile, grammar = env
    from dataclasses import replace
    capped = replace(profile, session_cap_minutes=35, profile_hash="")
    g2 = compile_risk_grammar(capped, build_exercise_index(_db_of(env)))

    payload = PlanAgent().build_request_payload(capped, g2, "full_body")
    assert payload["session_cap_minutes"] == 35
    assert "prescription_rules" in payload
    assert payload["fitness_level"] == "beginner"


def test_payload_carries_bounds_per_type(env) -> None:
    """模型必须能从 payload 里读到每类动作的合法区间，否则无从取值。"""
    _, _, profile, grammar = env
    payload = PlanAgent().build_request_payload(profile, grammar, "full_body")
    rules = payload["prescription_rules"]
    assert rules, "应下发处方区间表"
    sample = rules[0]
    assert {"phase", "type", "bodyweight", "sets", "reps", "load_pct"} <= set(sample)
    assert isinstance(sample["sets"], list) and len(sample["sets"]) == 2

    row = payload["phase_candidates"]["main_lifts"][0]
    assert {"exercise_id", "type", "impact"} <= set(row)
    # bodyweight / timed / motion_pattern 只在真值/非空时出现
    assert set(row) <= {
        "exercise_id", "name_zh", "type", "impact",
        "bodyweight", "timed", "motion_pattern",
    }


def _db_of(env):
    return env[0]


# ── Agent 1 的语义通道 ──────────────────────────────────────────────────────
def test_state_agent_merges_semantic_constraints(risk_engine) -> None:
    """规则算不出 avoid_patterns / 时长上限，只能由模型补。"""
    db = risk_engine.exercise_db

    def fake_enhance(payload):
        assert "available_motion_patterns" in payload
        return {
            "avoid_patterns": ["squat", "lunge"],
            "session_cap_minutes": 40,
            "progression_note": "先恢复关节活动度，两周内不加负荷",
            "capacity_note": "当前容量偏低，单次不宜超过 40 分钟",
            "rationale": "病历提到深蹲到底时膝内侧刺痛",
        }

    profile = StateRiskAgent(db, llm_enhance_fn=fake_enhance).analyze(KNEE_HIGH, None)
    assert profile.llm_status == "applied"
    assert profile.avoid_patterns == ("lunge", "squat")
    assert profile.session_cap_minutes == 40
    assert "两周" in profile.progression_note
    assert profile.profile_hash


def test_state_agent_ignores_unknown_patterns(risk_engine) -> None:
    """模型编一个不存在的动作模式 → 丢弃，不能污染下游过滤。"""
    db = risk_engine.exercise_db

    def fake_enhance(payload):
        return {"avoid_patterns": ["jumping_lunges_of_doom"], "session_cap_minutes": 9999}

    profile = StateRiskAgent(db, llm_enhance_fn=fake_enhance).analyze(KNEE_HIGH, None)
    assert profile.avoid_patterns == ()
    assert profile.session_cap_minutes == 120   # 夹到上限


def test_state_agent_reads_notes_without_structured_injury(risk_engine) -> None:
    """只写 notes、没填 severity 时，规则算不出约束，必须让模型看文本。"""
    db = risk_engine.exercise_db
    calls = []

    def fake_enhance(payload):
        calls.append(payload)
        return {"avoid_patterns": ["squat"], "rationale": "从 notes 判断"}

    profile_text_only = {
        "user_id": "t_text",
        "basic_info": {"age": 40},
        "fitness_level": "beginner",
        "medical_history": [{"notes": "蹲厕所起来时右膝发软，已经三个月"}],
    }
    profile = StateRiskAgent(db, llm_enhance_fn=fake_enhance).analyze(profile_text_only, None)

    assert calls, "有 notes 就应该调用模型"
    assert profile.llm_status == "applied"
    assert profile.avoid_patterns == ("squat",)
    # 没有结构化伤情时，允许动作是全量的（模型需要完整视野）
    assert len(calls[0]["allowed_exercises"]) > 20
