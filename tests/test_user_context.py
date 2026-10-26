"""验证「模型看到完整用户输入」这条链路。

背景：此前下发给 Agent 1 的档案只有 ``user_id / age / fitness_level /
medical_history`` 四项，且 ``age`` 取的是顶层的键（实际数据在 ``basic_info``
里），等于恒为 None。于是「想练力量」「没有杠铃」「讨厌深蹲」这三类信息
在 Agent 之间整段丢失 —— 而它们恰恰是决定处方取向的关键输入。

这组测试锁四件事：
    1. 原始档案完整进入 payload（含 basic_info / goal / 器械 / 偏好 / 本次需求）；
    2. 器械缺失变成**硬约束**（与伤情禁忌同级），偏好则**永远不是**禁忌；
    3. 上下文透传到 Agent 2，候选行自带 liked / disliked 标记；
    4. 上下文不参与 profile_hash —— 换目标不该让已生成的计划「过期」。
"""
from __future__ import annotations

import pytest

from agents.grammar import build_exercise_index, compile_risk_grammar
from agents.plan_agent import PlanAgent
from agents.state_agent import StateRiskAgent

BASE = {
    "user_id": "u_ctx",
    "basic_info": {"age": 32, "gender": "male", "height_cm": 178, "weight_kg": 80},
    "fitness_level": "intermediate",
    "fitness_goal": "strength",
    "training_frequency": 2,
    "medical_history": [
        {
            "location": "knee",
            "condition": "meniscus_tear",
            "severity": "high",
            "notes": "蹲到底膝内侧刺痛",
        }
    ],
}


@pytest.fixture()
def db(risk_engine):
    return risk_engine.exercise_db


# ── 1. payload 完整性 ──────────────────────────────────────────────────────
def test_state_payload_carries_full_profile(db) -> None:
    profile_ctx = {
        **BASE,
        "available_equipment": ["bodyweight", "dumbbell", "bench"],
        "preferences": {
            "liked_patterns": ["hinge"],
            "disliked_patterns": ["lunge"],
            "disliked_exercises": ["Burpee"],
            "notes": "讨厌憋气式大重量",
        },
    }
    agent = StateRiskAgent(db)
    profile = agent.analyze(
        profile_ctx, None, workout_type="lower_body", query="今天只有三十分钟"
    )
    payload = agent._build_enhance_payload(profile, profile_ctx, None)

    user = payload["user_profile"]
    assert user["basic_info"]["age"] == 32
    assert user["fitness_goal"] == "strength"
    assert user["training_frequency"] == 2
    assert user["available_equipment"] == ["bodyweight", "dumbbell", "bench"]
    assert user["preferences"]["disliked_patterns"] == ["lunge"]
    # 病历原文必须完整：notes 是模型唯一能读的自由文本
    assert user["medical_history"][0]["notes"] == "蹲到底膝内侧刺痛"

    # 本次需求与训练类型单独成块，避免与「用户固有属性」混淆
    assert payload["current_request"] == {
        "workout_type": "lower_body",
        "query": "今天只有三十分钟",
    }


def test_age_is_no_longer_none(db) -> None:
    """旧版读 user_profile['age']，数据其实在 basic_info 里，恒为 None。"""
    agent = StateRiskAgent(db)
    profile = agent.analyze(BASE, None)
    payload = agent._build_enhance_payload(profile, BASE, None)
    assert payload["user_profile"]["basic_info"]["age"] == 32


# ── 2. 器械是硬约束，偏好是软的 ────────────────────────────────────────────
def test_missing_equipment_becomes_forbidden(db) -> None:
    profile = StateRiskAgent(db).analyze(
        {**BASE, "available_equipment": ["bodyweight"]}, None
    )
    gear_reasons = [
        r for r in profile.forbidden_reasons.values() if r.startswith("EQUIPMENT_MISSING")
    ]
    assert gear_reasons, "只给 bodyweight 时应排除需要器械的动作"
    # 与伤情禁忌同处一个集合，说明它真的被执行了，不只是提示
    assert any(r.startswith("SEVERITY_") for r in profile.forbidden_reasons.values())
    assert any(r.kind == "equipment" for r in profile.rules)


def test_empty_equipment_list_means_full_access(db) -> None:
    """空/None 表示「没填 → 不限制」，与 risk_engine 的语义保持一致。"""
    agent = StateRiskAgent(db)
    none_case = agent.analyze({**BASE, "available_equipment": None}, None)
    empty_case = agent.analyze({**BASE, "available_equipment": []}, None)
    assert not any(
        r.startswith("EQUIPMENT") for r in none_case.forbidden_reasons.values()
    )
    assert not any(
        r.startswith("EQUIPMENT") for r in empty_case.forbidden_reasons.values()
    )
    assert none_case.allowed_ids == empty_case.allowed_ids


def test_preferences_never_become_forbidden(db) -> None:
    """「不喜欢」不等于「不能做」—— 偏好进了禁忌集就会白送掉可训练空间。"""
    plain = StateRiskAgent(db).analyze(BASE, None)
    picky = StateRiskAgent(db).analyze(
        {
            **BASE,
            "preferences": {
                "disliked_patterns": ["squat", "lunge", "hinge"],
                "disliked_exercises": ["Barbell Back Squat", "平板支撑"],
            },
        },
        None,
    )
    assert plain.allowed_ids == picky.allowed_ids
    assert plain.forbidden_reasons == picky.forbidden_reasons


# ── 3. 上下文透传到生成端 ──────────────────────────────────────────────────
def test_plan_payload_carries_goal_and_request(db) -> None:
    ctx = {
        **BASE,
        "available_equipment": ["bodyweight", "dumbbell"],
        "preferences": {"liked_patterns": ["hinge"]},
    }
    profile = StateRiskAgent(db).analyze(
        ctx, None, workout_type="lower_body", query="想练腿但只有半小时"
    )
    grammar = compile_risk_grammar(profile, build_exercise_index(db))
    payload = PlanAgent().build_request_payload(profile, grammar, "lower_body")

    assert payload["fitness_goal"] == "strength"
    assert payload["training_frequency"] == 2
    assert payload["user_request"] == "想练腿但只有半小时"
    assert payload["preferences"]["liked_patterns"] == ["hinge"]
    assert payload["available_equipment"] == ["bodyweight", "dumbbell"]


def test_candidate_rows_flag_liked_and_disliked(db) -> None:
    """把偏好标在候选行上，模型不必自己拿字符串去匹配动作模式。"""
    profile = StateRiskAgent(db).analyze(
        {
            **BASE,
            "preferences": {"liked_patterns": ["hinge"], "disliked_patterns": ["core"]},
        },
        None,
    )
    grammar = compile_risk_grammar(profile, build_exercise_index(db))
    payload = PlanAgent().build_request_payload(profile, grammar, "full_body")
    rows = [row for slots in payload["phase_candidates"].values() for row in slots]

    assert any(row.get("liked") for row in rows), "hinge 类动作应被标 liked"
    assert any(row.get("disliked") for row in rows), "core 类动作应被标 disliked"
    # 标记只是标签，不改变候选池大小
    assert len(rows) == sum(len(grammar.phase_allowed_ids(p)) for p in payload["phase_candidates"])


def test_query_alone_triggers_state_llm(db) -> None:
    """只有一句需求、没有结构化伤情时，仍要调模型 —— 那正是它唯一能救的场景。"""
    calls: list = []

    def fake(payload):
        calls.append(payload)
        return {}

    clean = {
        "user_id": "q",
        "basic_info": {"age": 30, "gender": "male"},
        "fitness_level": "beginner",
        "medical_history": [],
    }

    agent = StateRiskAgent(db, llm_enhance_fn=fake)
    profile = agent.analyze(clean, None, query="今天只有三十分钟")
    assert len(calls) == 1
    assert profile.llm_status == "empty"  # 调用了，但没给出额外约束

    # 什么都不说的用户 → 完全跳过调用，省一次请求
    agent2 = StateRiskAgent(db, llm_enhance_fn=fake)
    profile2 = agent2.analyze({**clean, "user_id": "q2"}, None)
    assert len(calls) == 1
    assert profile2.llm_status == "empty"


# ── 4. 上下文不进 hash ─────────────────────────────────────────────────────
def test_user_context_does_not_change_profile_hash(db) -> None:
    agent = StateRiskAgent(db)
    strength = agent.analyze({**BASE, "fitness_goal": "strength"}, None)
    cut = agent.analyze({**BASE, "fitness_goal": "fat_loss"}, None)

    assert strength.profile_hash == cut.profile_hash
    assert strength.user_context["fitness_goal"] == "strength"
    assert cut.user_context["fitness_goal"] == "fat_loss"
    # 上下文仍然要出现在序列化结果里，供审计与前端使用
    assert strength.to_dict()["user_context"]["fitness_goal"] == "strength"


# ── 5. workout_type 必须真的决定练哪里 ─────────────────────────────────────
LOWER_MUSCLES = {
    "Quadriceps", "Gluteus Maximus", "Hamstrings",
    "Gastrocnemius", "Soleus", "Adductors", "Abductors", "Calves",
}
CORE_MUSCLES = {"Rectus Abdominis", "Obliques", "Erector Spinae", "Transverse Abdominis"}
UPPER_MUSCLES = {
    "Pectorals", "Deltoids", "Rear Deltoids", "Latissimus Dorsi", "Rhomboids",
    "Trapezius", "Triceps Brachii", "Biceps Brachii", "Brachialis", "Forearm Flexors",
}
# 热身与放松按设计豁免部位过滤：全身升温与放松本来就不分部位
EXEMPT_PHASES = {"warm_up", "cool_down"}


def _draft_with(db, workout_type, equipment=None, history=None):
    from agents.pipeline import run_pipeline

    profile = {
        "user_id": f"focus_{workout_type}",
        "basic_info": {"age": 34, "gender": "male"},
        "fitness_level": "intermediate",
        "available_equipment": equipment if equipment is not None else ["bodyweight", "dumbbell", "barbell"],
        "medical_history": history if history is not None else [],
    }
    result = run_pipeline(db, profile, None, workout_type=workout_type)
    return result, {int(ex["id"]): ex for ex in db}


def test_lower_body_contains_no_upper_body_work(db) -> None:
    result, index = _draft_with(db, "lower_body")
    for phase, slots in result.draft.phases.items():
        if phase in EXEMPT_PHASES:
            continue
        for slot in slots:
            muscle = str(index[slot.exercise_id].get("target_muscle") or "")
            pattern = str(index[slot.exercise_id].get("motion_pattern") or "")
            assert muscle in LOWER_MUSCLES | CORE_MUSCLES or pattern in {"core", "stability", "mobility"}, (
                phase,
                index[slot.exercise_id].get("name_zh"),
                muscle,
            )


def test_upper_body_contains_no_lower_body_work(db) -> None:
    result, index = _draft_with(db, "upper_body")
    for phase, slots in result.draft.phases.items():
        if phase in EXEMPT_PHASES:
            continue
        for slot in slots:
            muscle = str(index[slot.exercise_id].get("target_muscle") or "")
            pattern = str(index[slot.exercise_id].get("motion_pattern") or "")
            assert muscle in UPPER_MUSCLES | CORE_MUSCLES or pattern in {"core", "stability", "mobility"}, (
                phase,
                index[slot.exercise_id].get("name_zh"),
                muscle,
            )


def test_lower_body_still_has_main_lifts(db) -> None:
    """哑铃+自重 + 膝伤 high 的组合下，下肢日必须有可用的主项。"""
    result, _ = _draft_with(
        db,
        "lower_body",
        equipment=["bodyweight", "dumbbell"],
        history=[{"location": "knee", "condition": "meniscus_tear", "severity": "high"}],
    )
    assert result.draft.phases["main_lifts"], "下肢日不应没有主项"
    assert result.report.passed is True


def test_full_body_is_unrestricted(db) -> None:
    from agents.focus import resolve_focus

    index = {int(ex["id"]): ex for ex in db}
    assert resolve_focus("full_body", index) is None
    # 未知取值按全身处理，而不是把所有动作都过滤掉
    assert resolve_focus("something_else", index) is None


def test_focus_cannot_bypass_forbidden(db) -> None:
    """部位定向只能收窄范围，永不能把禁忌动作带回来。"""
    from agents.grammar import build_exercise_index, compile_risk_grammar

    history = [{"location": "knee", "condition": "meniscus_tear", "severity": "high"}]
    profile = StateRiskAgent(db).analyze(
        {**BASE, "medical_history": history}, None, workout_type="lower_body"
    )
    grammar = compile_risk_grammar(profile, build_exercise_index(db))
    forbidden = set(profile.forbidden_reasons)
    for phase in ("warm_up", "activation", "main_lifts", "accessories", "cool_down"):
        assert not (set(grammar.phase_allowed_ids(phase)) & forbidden)


def test_disliked_exercise_is_dropped_when_pool_is_large_enough(db) -> None:
    """偏好生效于「候选充足」的分支：明确不想做的动作直接不出现。"""
    from agents.pipeline import run_pipeline

    base = {
        "user_id": "pref",
        "basic_info": {"age": 34, "gender": "male"},
        "fitness_level": "intermediate",
        "available_equipment": ["bodyweight", "dumbbell"],
        "medical_history": [{"location": "knee", "condition": "meniscus_tear", "severity": "high"}],
    }
    index = {int(ex["id"]): ex for ex in db}

    plain = run_pipeline(db, base, None, workout_type="lower_body")
    plain_names = {index[s.exercise_id]["name_zh"] for s in plain.draft.phases["accessories"]}
    assert "提踵" in plain_names, "基线里应有提踵，否则这条测试不成立"

    picky = run_pipeline(
        db,
        {**base, "preferences": {"disliked_exercises": ["提踵"]}},
        None,
        workout_type="lower_body",
    )
    picky_names = {index[s.exercise_id]["name_zh"] for s in picky.draft.phases["accessories"]}
    assert "提踵" not in picky_names
    # 少一个动作而不是把阶段清空
    assert picky.draft.phases["accessories"]
