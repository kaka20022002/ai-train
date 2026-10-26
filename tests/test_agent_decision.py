"""锁定 v4 的权力结构：模型全权决策，规则只出现在「基线证据」与「降级后端」两处。

这组测试锁五件事：
    1. 动作库**全量**下发 —— 没有候选裁剪、没有 enum、没有阶段硬过滤；
    2. 模型给的 sets / reps / load / rest / note 原样落库，**越界也不夹紧**；
    3. 模型少给就少给 —— 不再由规则补位到固定数量；
    4. 唯一的硬清洗是「ID 必须对得上知识库」，因为渲染不出名字；
    5. 上游基线（禁忌 / 模式 / 上限）以参考证据的形式随请求下发，
       并且审查意见可以通过 ``revise`` 回灌给同一个生成 Agent。
"""
from __future__ import annotations

import pytest

from agents.catalog import ExerciseCatalog
from agents.contracts import PHASES, PlanDraft, Slot
from agents.plan_agent import PlanAgent
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
    catalog = ExerciseCatalog(db)
    profile = StateRiskAgent(db).analyze(KNEE_HIGH, None)
    return db, catalog, profile


def _pick(catalog: ExerciseCatalog, phase: str) -> dict:
    for row in catalog.rows():
        if phase in row["phases"]:
            return row
    raise AssertionError(f"动作库里没有属于 {phase} 的动作")


# ── 全库视野 ────────────────────────────────────────────────────────────────
def test_catalog_payload_is_unfiltered(env) -> None:
    """生成端拿到的是整库，不是「允许集」。"""
    db, catalog, profile = env
    payload = PlanAgent().build_request_payload(profile, catalog, "full_body")

    rows = payload["exercise_catalog"]
    assert len(rows) == len(db) == len(catalog)
    # 基线里的禁忌动作照样出现在目录里（模型自己看 baseline 判断）
    forbidden = set(profile.forbidden_reasons)
    assert forbidden, "测试前提：膝伤 HIGH 应有基线禁忌"
    assert forbidden <= {row["exercise_id"] for row in rows}
    # 每条都带阶段归属，模型据此决定放哪里
    assert all(row["phases"] for row in rows)


def test_schema_carries_no_enum(env) -> None:
    """解码期不再 mask —— schema 只描述形状。"""
    _, catalog, _ = env
    schema = catalog.slot_schema()["schema"]
    for phase in PHASES:
        item = schema["properties"][phase]["items"]
        assert "enum" not in item["properties"]["exercise_id"]


def test_baseline_is_evidence_not_constraint(env) -> None:
    """基线以「参考意见」名义下发，附带说明它不是硬约束。"""
    _, catalog, profile = env
    payload = PlanAgent().build_request_payload(profile, catalog, "full_body")
    baseline = payload["baseline"]

    assert "不是硬约束" in baseline["note"]
    assert {row["exercise_id"] for row in baseline["forbidden_exercises"]} == set(
        profile.forbidden_reasons
    )
    assert baseline["impact_ceiling"] == profile.impact_ceiling
    assert baseline["joint_caps"] == profile.joint_caps
    # 病历原文也要给到生成端，否则它无从判断某条禁忌是否适用于本次训练
    assert payload["medical_history"], "病历原文必须进入生成端"

    # 参考剂量表在，但明确是「参考」
    assert payload["reference_doses"]
    assert {"phase", "type", "sets", "reps"} <= set(payload["reference_doses"][0])


# ── 模型决策权：原样采纳 ────────────────────────────────────────────────────
def test_model_supplied_params_are_adopted_verbatim(env) -> None:
    _, catalog, profile = env
    target = _pick(catalog, "warm_up")
    captured = {}

    def fake_plan(payload, schema):
        captured["payload"] = payload
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

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, catalog, "full_body")
    slot = draft.phases["warm_up"][0]

    assert draft.generator == "llm"
    assert slot.exercise_id == target["exercise_id"]
    assert (slot.sets, slot.reps, slot.load_pct) == (2, "14", None)
    assert slot.rest_seconds == 25
    assert slot.note == "髋部还没热开，先小幅活动"
    assert draft.adjusted_slots == 0
    # payload 里带 schema 形状提示（由 bridge 附加），Agent 侧不注入 enum
    assert captured["payload"]["catalog_version"] == catalog.version


def test_out_of_range_params_are_kept_as_is(env) -> None:
    """越界不再被夹紧 —— 「合不合理」由审查 Agent 判，不由解析层偷偷改。"""
    _, catalog, profile = env
    target = _pick(catalog, "warm_up")

    def fake_plan(payload, schema):
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

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, catalog, "full_body")
    slot = draft.phases["warm_up"][0]

    assert slot.sets == 99
    assert slot.reps == "500"
    assert slot.load_pct == 300
    # 休息时长只做渲染兜底（负数/天文数字会让时长估算失真）
    assert slot.rest_seconds == 600
    assert draft.adjusted_slots == 0


def test_model_may_choose_a_baseline_forbidden_exercise(env) -> None:
    """基线禁忌不再被解析层挡掉 —— 模型可以调用，代价是被审查驳回。"""
    _, catalog, profile = env
    forbidden_id = sorted(profile.forbidden_reasons)[0]

    def fake_plan(payload, schema):
        return {
            "main_lifts": [
                {"exercise_id": forbidden_id, "sets": 3, "reps": "8", "load_pct": 70}
            ]
        }

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, catalog, "full_body")
    assert forbidden_id in draft.all_ids()
    assert draft.rejected_ids == ()


def test_phase_assignment_is_left_to_the_model(env) -> None:
    """把拉伸放进主项段不再被解析层拒绝 —— 由审查 Agent 判 SEQUENCE。"""
    _, catalog, profile = env
    stretch = next(
        row for row in catalog.rows()
        if row["type"] == "Stretch"
    )

    def fake_plan(payload, schema):
        return {
            "main_lifts": [
                {"exercise_id": stretch["exercise_id"], "sets": 2, "reps": "30"}
            ]
        }

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, catalog, "full_body")
    assert [s.exercise_id for s in draft.phases["main_lifts"]] == [stretch["exercise_id"]]


def test_short_phase_is_not_topped_up(env) -> None:
    """模型只给了 1 个动作，阶段就保留 1 个 —— 不再用规则补位。"""
    _, catalog, profile = env
    target = _pick(catalog, "activation")

    def fake_plan(payload, schema):
        return {
            "activation": [
                {"exercise_id": target["exercise_id"], "sets": 2, "reps": "12"}
            ]
        }

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, catalog, "full_body")
    assert len(draft.phases["activation"]) == 1
    assert draft.phases["main_lifts"] == []


def test_missing_params_fall_back_to_prescription(env) -> None:
    """参数缺失时用处方默认值补全，并计入 defaulted 计数。"""
    _, catalog, profile = env
    target = _pick(catalog, "warm_up")

    def fake_plan(payload, schema):
        return {"warm_up": [{"exercise_id": target["exercise_id"]}]}

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, catalog, "full_body")
    slot = draft.phases["warm_up"][0]
    assert slot.sets >= 1
    assert slot.reps
    assert draft.adjusted_slots == 1


# ── 唯一的硬清洗：ID 必须存在 ───────────────────────────────────────────────
def test_unknown_id_is_dropped(env) -> None:
    _, catalog, profile = env
    bogus = max(catalog.ids) + 12345
    good = _pick(catalog, "main_lifts")["exercise_id"]

    def fake_plan(payload, schema):
        return {
            "main_lifts": [
                {"exercise_id": bogus, "sets": 3, "reps": "8"},
                {"exercise_id": good, "sets": 3, "reps": "8"},
            ]
        }

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, catalog, "full_body")
    assert [s.exercise_id for s in draft.phases["main_lifts"]] == [good]
    assert draft.rejected_ids == (bogus,)


def test_duplicate_across_phases_kept_once(env) -> None:
    _, catalog, profile = env
    target = _pick(catalog, "main_lifts")

    def fake_plan(payload, schema):
        item = {"exercise_id": target["exercise_id"], "sets": 3, "reps": "8"}
        return {"main_lifts": [item], "accessories": [dict(item)]}

    draft = PlanAgent(llm_plan_fn=fake_plan).generate(profile, catalog, "full_body")
    assert draft.all_ids().count(target["exercise_id"]) == 1


# ── 修订轮 ──────────────────────────────────────────────────────────────────
def test_revise_feeds_back_violations_and_previous_attempt(env) -> None:
    _, catalog, profile = env
    target = _pick(catalog, "main_lifts")
    seen = {}

    def fake_plan(payload, schema):
        seen.update(payload)
        return {
            "main_lifts": [
                {"exercise_id": target["exercise_id"], "sets": 3, "reps": "6"}
            ]
        }

    draft = PlanDraft(
        plan_id="draft_prev",
        user_id=profile.user_id,
        workout_type="full_body",
        phases={p: [] for p in PHASES} | {"main_lifts": [Slot(target["exercise_id"], 9, "99")]},
        generator="llm",
        grammar_version=catalog.version,
        profile_hash=profile.profile_hash,
    )
    violations = [{"code": "VOLUME", "exercise_id": target["exercise_id"], "phase": "main_lifts"}]

    revised = PlanAgent(llm_plan_fn=fake_plan).revise(
        profile, catalog, draft, violations, "单次 9 组过载"
    )

    assert revised is not None and revised.generator == "llm_revised"
    assert seen["review_feedback"]["violations"] == violations
    assert "previous_attempt" in seen
    assert revised.phases["main_lifts"][0].sets == 3


def test_revise_requires_llm(env) -> None:
    _, catalog, profile = env
    draft = PlanDraft(
        plan_id="p", user_id="u", workout_type="full_body",
        phases={p: [] for p in PHASES}, generator="deterministic",
        grammar_version=catalog.version, profile_hash=profile.profile_hash,
    )
    agent = PlanAgent()
    assert agent.can_revise is False
    assert agent.revise(profile, catalog, draft, []) is None


# ── 降级后端仍然完整（没配 key 时的行为）───────────────────────────────────
def test_deterministic_backend_still_masks(env) -> None:
    _, catalog, profile = env
    draft = PlanAgent().generate(profile, catalog, "full_body", seed=3)

    assert draft.generator == "deterministic"
    assert draft.slot_count() > 0
    assert not (set(draft.all_ids()) & set(profile.forbidden_reasons))


# ── 语义约束（avoid_patterns / session cap）─────────────────────────────────
def test_avoid_patterns_removes_candidates(env) -> None:
    """降级后端里模式禁忌仍会把整类动作从候选池移除。"""
    from dataclasses import replace
    from agents.grammar import compile_risk_grammar

    _, catalog, profile = env
    squat_ids = [
        eid for eid, meta in catalog.index.items()
        if str(meta.get("motion_pattern") or "").lower() == "squat"
    ]
    assert squat_ids, "动作库应包含 squat 模式"

    blocked = replace(profile, avoid_patterns=("squat",), profile_hash="")
    g2 = compile_risk_grammar(blocked, catalog.index)

    remaining = set()
    for phase in PHASES:
        remaining.update(g2.candidates(phase, allow_fallback=True))
    assert not (set(squat_ids) & remaining)


def test_session_cap_reaches_plan_payload(env) -> None:
    from dataclasses import replace

    _, catalog, profile = env
    capped = replace(profile, session_cap_minutes=35, profile_hash="")
    payload = PlanAgent().build_request_payload(capped, catalog, "full_body")
    assert payload["session_cap_minutes"] == 35
    assert payload["fitness_level"] == "beginner"
    assert "reference_doses" in payload


# ── 基线谓词本身（供审查 Agent 使用的证据来源）───────────────────────────────
def test_baseline_flags_report_joint_cap(env) -> None:
    from dataclasses import replace
    from agents.safety_agent import SafetyEvalAgent

    _, catalog, profile = env
    capped = replace(profile, joint_caps={"knee": 1}, impact_ceiling=5, profile_hash="")
    squat = next(
        eid for eid, ex in catalog.index.items()
        if "knee" in ex.get("involved_joints", [])
    )
    draft = PlanDraft(
        plan_id="p", user_id=capped.user_id, workout_type="full_body",
        phases={p: [] for p in PHASES} | {"main_lifts": [Slot(squat, 3, "10", 50)]},
        generator="llm", grammar_version=catalog.version,
        profile_hash=capped.profile_hash,
    )
    flags = SafetyEvalAgent._baseline_flags(draft, capped, catalog)
    assert any(f.code == "JOINT_CAP" for f in flags)


# ── Agent 1 的语义通道（规则降级为基线，但抽取逻辑不变）─────────────────────
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
    """模型编一个不存在的动作模式 → 丢弃，不能污染下游。"""
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
