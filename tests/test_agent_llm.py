"""三 Agent 共用同一个 LLM 客户端、各用一份 prompt —— 行为回归测试。

这套测试锁的不是「模型答得好不好」（那要靠真实 API 的评测集），
而是**无论模型答什么，约束都不会被放松**：

    1. 三个 Agent 各自拿到不同的 system prompt（职责隔离）
    2. 状态分析 Agent 只能追加约束，不能删除或放宽规则算出的约束
    3. 安全评估 Agent 与规则判定取合取：它能加严，不能放宽
    4. 任一 LLM 通道故障时，管线退回规则后端而不是放行
    5. 生成 Agent 的越界 ID 在解析处被挡回

只要这几条成立，换 provider、换模型、改 prompt 都不会动摇安全命题。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.grammar import build_exercise_index, compile_risk_grammar
from agents.llm_bridge import AgentBridges, build_bridges
from agents.pipeline import run_pipeline
from agents.plan_agent import PlanAgent
from agents.prompts import (
    PLAN_GEN_PROMPT_VERSION,
    SAFETY_EVAL_PROMPT_VERSION,
    STATE_RISK_PROMPT_VERSION,
)
from agents.contracts import PHASES, PlanDraft, Slot
from agents.safety_agent import SafetyEvalAgent
from agents.state_agent import StateRiskAgent

DB_PATH = Path(__file__).resolve().parent.parent / "exercise_db.json"

KNEE_HIGH = {
    "user_id": "t_llm_knee",
    "basic_info": {"age": 30, "gender": "male"},
    "fitness_level": "beginner",
    "medical_history": [
        {
            "location": "knee",
            "condition": "meniscus_tear",
            "severity": "high",
            "pain_trigger": "deep_flexion",
            "notes": "术后两年，深屈膝仍有钝痛，不敢做全蹲",
        }
    ],
}

PAIN_FEEDBACK = {
    "pain_feedback": {"has_pain": True, "locations": ["knee"]},
    "rpe": 8,
}


@pytest.fixture(scope="module")
def exercise_db():
    return json.loads(DB_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rule_profile(exercise_db):
    """纯规则后端算出的基线档案，后续测试都以它作为「不可退让的下限」。"""
    return StateRiskAgent(exercise_db).analyze(KNEE_HIGH, PAIN_FEEDBACK)


def _knee_allowed_ids(exercise_db, profile):
    """当前允许、且涉及膝关节的动作 —— 这正是 LLM 可以追加禁忌的对象。"""
    return [
        int(ex["id"])
        for ex in exercise_db
        if int(ex["id"]) in set(profile.allowed_ids)
        and "knee" in {str(j).lower() for j in ex.get("involved_joints", [])}
    ]


# ── 1. 一个 client，三份 prompt ─────────────────────────────────────────────
class RecordingClient:
    """记录每次调用的 system prompt，并返回一个最小合法结构。"""

    def __init__(self) -> None:
        self.systems: list[str] = []
        self.users: list[str] = []

    def chat_json(self, system_prompt: str, user_prompt: str):
        self.systems.append(system_prompt)
        self.users.append(user_prompt)
        return {}


def test_bridges_reuse_one_client_with_three_prompts() -> None:
    client = RecordingClient()
    bridges = build_bridges(client)

    assert isinstance(bridges, AgentBridges)
    assert bridges.enabled

    bridges.state_fn({"probe": "state"})
    bridges.plan_fn({"probe": "plan"}, {"name": "draft"})
    bridges.safety_fn({"probe": "safety"})

    # 同一个 client 被调用三次，但三份 system prompt 互不相同
    assert len(client.systems) == 3
    assert len(set(client.systems)) == 3
    # 每份 prompt 都足够长（不是占位符），且都要求只输出 JSON
    for system in client.systems:
        assert len(system) > 200
        assert "JSON" in system


def test_prompt_versions_are_independent() -> None:
    versions = {
        STATE_RISK_PROMPT_VERSION,
        PLAN_GEN_PROMPT_VERSION,
        SAFETY_EVAL_PROMPT_VERSION,
    }
    assert len(versions) == 3
    assert all(v.count("/") == 1 for v in versions)


def test_bridges_can_be_partially_disabled() -> None:
    """只接 plan_gen 时另外两个保持 None —— 装配层要支持这种半开状态。"""
    bridges = AgentBridges(plan_fn=lambda payload, schema: {})
    assert bridges.enabled
    assert bridges.state_fn is None
    assert bridges.safety_fn is None


# ── 2. 状态分析：只能追加 ──────────────────────────────────────────────────
def test_state_agent_appends_forbidden_by_llm(exercise_db, rule_profile) -> None:
    targets = _knee_allowed_ids(exercise_db, rule_profile)
    assert targets, "测试前提：应当存在涉膝但仍在允许集内的动作"
    target = targets[0]

    def enhance(payload):
        # 顺带断言：发给模型的动作全部与受伤关节相关
        for row in payload["allowed_exercises"]:
            assert "knee" in row["involved_joints"]
        return {
            "additional_forbidden": [
                {"exercise_id": target, "reason": "病历记录深屈膝疼痛，该动作全程深屈膝"}
            ],
            "additional_joint_caps": {},
            "impact_ceiling_override": None,
            "load_pct_cap_override": None,
            "rationale": "病历原文提到深屈膝钝痛",
        }

    enhanced = StateRiskAgent(exercise_db, llm_enhance_fn=enhance).analyze(
        KNEE_HIGH, PAIN_FEEDBACK
    )

    assert enhanced.llm_status == "applied"
    assert target not in enhanced.allowed_ids
    assert target in enhanced.forbidden_reasons
    assert target in enhanced.llm_forbidden
    # 规则原本禁的动作一个都不能少
    assert set(rule_profile.forbidden_reasons) <= set(enhanced.forbidden_reasons)
    # 约束变了，指纹必须跟着变，否则下游 STALE_PROFILE 检查失效
    assert enhanced.profile_hash != rule_profile.profile_hash


def test_state_agent_cannot_loosen_rule_constraints(exercise_db, rule_profile) -> None:
    """模型提议解禁 + 放宽上限，必须全部被丢弃。"""
    forbidden_ids = sorted(rule_profile.forbidden_reasons)
    assert forbidden_ids

    def enhance(payload):
        return {
            "additional_forbidden": [
                {"exercise_id": eid, "reason": "我觉得可以练"} for eid in forbidden_ids
            ],
            "additional_joint_caps": {j: 5 for j in rule_profile.joint_caps},
            "impact_ceiling_override": 5,
            "load_pct_cap_override": 100,
            "rationale": "试图放宽",
        }

    enhanced = StateRiskAgent(exercise_db, llm_enhance_fn=enhance).analyze(
        KNEE_HIGH, PAIN_FEEDBACK
    )

    # 禁忌集不变（不能移除），关节上限不变（不能调高）
    assert set(enhanced.forbidden_reasons) == set(rule_profile.forbidden_reasons)
    assert enhanced.joint_caps == rule_profile.joint_caps
    # 规则已因 feedback 压到 3 和 60，模型的 5 / 100 不得生效
    assert enhanced.impact_ceiling == rule_profile.impact_ceiling == 3
    assert enhanced.load_pct_cap == rule_profile.load_pct_cap == 60
    assert enhanced.allowed_ids == rule_profile.allowed_ids
    assert enhanced.llm_status == "empty"


def test_state_agent_accepts_tighter_caps_only(exercise_db, rule_profile) -> None:
    def enhance(payload):
        return {
            "additional_forbidden": [],
            "additional_joint_caps": {"knee": 1},
            "impact_ceiling_override": 2,
            "load_pct_cap_override": 40,
            "rationale": "术后早期，整体保守",
        }

    enhanced = StateRiskAgent(exercise_db, llm_enhance_fn=enhance).analyze(
        KNEE_HIGH, PAIN_FEEDBACK
    )

    assert enhanced.llm_status == "applied"
    assert enhanced.joint_caps["knee"] == 1
    assert enhanced.impact_ceiling == 2
    assert enhanced.load_pct_cap == 40


def test_state_agent_error_falls_back_to_rules(exercise_db, rule_profile) -> None:
    def explode(payload):
        raise RuntimeError("provider timeout")

    fallback = StateRiskAgent(exercise_db, llm_enhance_fn=explode).analyze(
        KNEE_HIGH, PAIN_FEEDBACK
    )

    assert fallback.llm_status == "error"
    assert fallback.allowed_ids == rule_profile.allowed_ids
    assert fallback.forbidden_reasons == rule_profile.forbidden_reasons


# ── 3. 安全评估：合取，只能加严 ─────────────────────────────────────────────
def _grammar(exercise_db, profile):
    return compile_risk_grammar(profile, build_exercise_index(exercise_db))


def test_safety_llm_fail_blocks_rule_pass(exercise_db, rule_profile) -> None:
    grammar = _grammar(exercise_db, rule_profile)
    clean = run_pipeline(
        exercise_db, KNEE_HIGH, PAIN_FEEDBACK
    )  # 规则后端生成，天然合规
    assert clean.report.passed

    draft = clean.draft
    judge = lambda payload: {
        "verdict": "fail",
        "violations": [
            {
                "code": "SEQUENCE",
                "exercise_id": 0,
                "phase": "warm_up",
                "reason": "热身段负荷偏高，未充分升温",
            }
        ],
        "rationale": "阶段安排不合理",
    }
    report = SafetyEvalAgent(llm_judge_fn=judge).evaluate(draft, rule_profile, grammar)

    assert report.llm_verdict == "fail"
    assert report.passed is False          # 规则 pass，但合取后整体 fail
    assert report.llm_disagreed is True
    assert any(v.code == "SEQUENCE" for v in report.violations)


def test_safety_llm_pass_cannot_override_rule_fail(exercise_db, rule_profile) -> None:
    grammar = _grammar(exercise_db, rule_profile)
    forbidden_id = sorted(rule_profile.forbidden_reasons)[0]

    # 手工注入一个禁忌槽位 —— 模拟「生成 Agent 被替换成恶意实现」
    draft = PlanDraft(
        plan_id="draft_injected",
        user_id=rule_profile.user_id,
        workout_type="full_body",
        phases={p: [] for p in PHASES} | {"main_lifts": [Slot(forbidden_id, 4, "6", 80, 5)]},
        generator="injected",
        grammar_version=grammar.version,
        profile_hash=rule_profile.profile_hash,
    )

    report = SafetyEvalAgent(
        llm_judge_fn=lambda payload: {
            "verdict": "pass",
            "violations": [],
            "rationale": "看起来没问题",
        }
    ).evaluate(draft, rule_profile, grammar)

    assert report.llm_verdict == "pass"
    assert report.passed is False          # 规则 fail 不会被 LLM 的 pass 推翻
    assert report.llm_disagreed is True
    assert any(v.code == "FORBIDDEN_ID" for v in report.violations)


def test_safety_llm_bare_fail_is_downgraded_to_error(exercise_db, rule_profile) -> None:
    """只说 fail 却不给合法违规码 → 不采信，退回规则结论（防 DoS）。"""
    grammar = _grammar(exercise_db, rule_profile)
    draft = run_pipeline(exercise_db, KNEE_HIGH, PAIN_FEEDBACK).draft

    report = SafetyEvalAgent(
        llm_judge_fn=lambda payload: {"verdict": "fail", "violations": []}
    ).evaluate(draft, rule_profile, grammar)

    assert report.llm_verdict == "error"
    assert report.passed is True           # 规则说 pass，无有效反证


def test_safety_llm_unknown_code_is_ignored(exercise_db, rule_profile) -> None:
    grammar = _grammar(exercise_db, rule_profile)
    draft = run_pipeline(exercise_db, KNEE_HIGH, PAIN_FEEDBACK).draft

    report = SafetyEvalAgent(
        llm_judge_fn=lambda payload: {
            "verdict": "fail",
            "violations": [
                {"code": "I_DONT_LIKE_IT", "exercise_id": 1, "phase": "main_lifts"}
            ],
            "rationale": "自由文本理由",
        }
    ).evaluate(draft, rule_profile, grammar)

    assert report.llm_verdict == "error"
    assert report.passed is True
    assert all(v.code != "I_DONT_LIKE_IT" for v in report.violations)


def test_safety_llm_error_falls_back(exercise_db, rule_profile) -> None:
    grammar = _grammar(exercise_db, rule_profile)
    draft = run_pipeline(exercise_db, KNEE_HIGH, PAIN_FEEDBACK).draft

    def explode(payload):
        raise TimeoutError("upstream 529")

    report = SafetyEvalAgent(llm_judge_fn=explode).evaluate(draft, rule_profile, grammar)

    assert report.llm_verdict == "error"
    assert report.passed is True
    assert "退回规则结论" in report.llm_rationale


# ── 4. 计划生成：越界 ID 在解析处被挡回 ────────────────────────────────────
def test_plan_agent_rejects_forbidden_id_from_llm(exercise_db, rule_profile) -> None:
    grammar = _grammar(exercise_db, rule_profile)
    forbidden_id = sorted(rule_profile.forbidden_reasons)[0]
    valid_id = grammar.candidates("main_lifts")[0]

    def llm(payload, schema):
        phases = {p: [{"exercise_id": valid_id}] for p in PHASES}
        phases["main_lifts"] = [{"exercise_id": forbidden_id}]
        return phases

    draft = PlanAgent(llm_plan_fn=llm).generate(rule_profile, grammar)

    assert draft.generator == "llm"
    assert draft.prompt_version == PLAN_GEN_PROMPT_VERSION
    assert forbidden_id in draft.rejected_ids
    assert forbidden_id not in draft.all_ids()


def test_plan_agent_falls_back_when_llm_raises(exercise_db, rule_profile) -> None:
    grammar = _grammar(exercise_db, rule_profile)

    def llm(payload, schema):
        raise RuntimeError("boom")

    draft = PlanAgent(llm_plan_fn=llm).generate(rule_profile, grammar)

    assert draft.generator == "deterministic"
    assert draft.slot_count() > 0
    assert set(draft.all_ids()) <= set(rule_profile.allowed_ids)


# ── 5. 全链路：三个 Agent 都走 LLM，审计留痕，合规性不变 ────────────────────
def test_pipeline_with_all_three_llm_agents(exercise_db) -> None:
    calls = {"state": 0, "plan": 0, "safety": 0}

    def state_fn(payload):
        calls["state"] += 1
        return {"additional_forbidden": [], "rationale": "规则已覆盖可见风险"}

    def plan_fn(payload, schema):
        calls["plan"] += 1
        return {
            phase: [{"exercise_id": ids[0]}]
            for phase, ids in payload["phase_candidates"].items()
            if ids
        }

    def safety_fn(payload):
        calls["safety"] += 1
        return {"verdict": "pass", "violations": [], "rationale": "未发现违规"}

    result = run_pipeline(
        exercise_db,
        KNEE_HIGH,
        PAIN_FEEDBACK,
        state_agent=StateRiskAgent(exercise_db, llm_enhance_fn=state_fn),
        plan_agent=PlanAgent(llm_plan_fn=plan_fn),
        safety_agent=SafetyEvalAgent(llm_judge_fn=safety_fn),
    )

    assert calls == {"state": 1, "plan": 1, "safety": 1}
    assert result.draft.generator == "llm"
    assert result.report.llm_verdict == "pass"
    assert result.report.passed

    # 核心不变量：计划动作与禁忌集仍然互斥
    assert set(result.draft.all_ids()) & set(result.profile.forbidden_reasons) == set()

    # 三个阶段的审计记录都带 LLM 痕迹
    entries = {e["stage"]: e for e in result.audit.to_dict()["entries"]}
    assert entries["state_risk"]["out"]["llm"]["status"] == "empty"
    assert entries["state_risk"]["out"]["llm"]["prompt_version"] == STATE_RISK_PROMPT_VERSION
    assert entries["plan_gen"]["out"]["generator"] == "llm"
    assert entries["plan_gen"]["out"]["prompt_version"] == PLAN_GEN_PROMPT_VERSION
    assert entries["safety_eval"]["out"]["llm_verdict"] == "pass"
    assert (
        entries["safety_eval"]["out"]["llm_prompt_version"]
        == SAFETY_EVAL_PROMPT_VERSION
    )


def test_pipeline_without_llm_marks_everything_skipped(exercise_db) -> None:
    """未配 key 时的降级路径：三个 Agent 全部规则后端，字段必须是 skipped。"""
    result = run_pipeline(exercise_db, KNEE_HIGH, PAIN_FEEDBACK)

    assert result.profile.llm_status == "skipped"
    assert result.draft.generator == "deterministic"
    assert result.report.llm_verdict == "skipped"
    assert result.report.passed
    assert result.report.llm_disagreed is False


# ── 6. JSON 解析容错 ────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw",
    [
        '{"verdict": "pass"}',
        '```json\n{"verdict": "pass"}\n```',
        '好的，审查结果如下：\n{"verdict": "pass"}\n以上。',
    ],
)
def test_extract_json_object_tolerates_wrapping(raw: str) -> None:
    from llm_client import _extract_json_object

    assert _extract_json_object(raw) == {"verdict": "pass"}


def test_extract_json_object_rejects_non_object() -> None:
    from llm_client import _extract_json_object

    with pytest.raises(ValueError):
        _extract_json_object('["a", "b"]')
