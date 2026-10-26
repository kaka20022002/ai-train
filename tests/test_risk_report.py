"""阶段一的产物：风险报告。

三阶段语义下，阶段一交出去的不是「一张禁忌表」，而是**一份判断**：

    overall        整体风险等级 + 能否开练 + 一句话结论
    injuries[]     每条伤情的功能影响、具体禁忌、可替代方向、上限
    dose_guidance  剂量口径（规则算不出来，只能由模型给）
    watch_items    训练中要盯的信号

约束集是同一判断的机器投影，两者不能分裂。这套测试锁四件事：

    1. 没有模型时报告照样成立（source=baseline），下游不必判空
    2. 模型改写报告时，越乐观的结论会被拉回到约束允许的范围
    3. 报告能到阶段二（选动作）和阶段三（验收）
    4. 阶段三能用 REPORT_BREACH 判「不适合这位用户」
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.catalog import ExerciseCatalog
from agents.contracts import PHASES, PlanDraft, Slot
from agents.plan_agent import PlanAgent
from agents.safety_agent import SafetyEvalAgent
from agents.state_agent import StateRiskAgent

DB_PATH = Path(__file__).resolve().parent.parent / "exercise_db.json"

KNEE_HIGH = {
    "user_id": "t_report_knee",
    "basic_info": {"age": 32, "gender": "male"},
    "fitness_level": "beginner",
    "fitness_goal": "strength",
    "available_equipment": ["bodyweight", "dumbbell"],
    "medical_history": [
        {
            "location": "knee",
            "condition": "meniscus_tear",
            "severity": "high",
            "notes": "蹲到底膝内侧刺痛，术后两年仍不敢深蹲",
        }
    ],
}

CLEAN = {
    "user_id": "t_report_clean",
    "basic_info": {"age": 30, "gender": "female"},
    "fitness_level": "beginner",
    "medical_history": [],
}


@pytest.fixture(scope="module")
def exercise_db():
    with open(DB_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture()
def catalog(exercise_db):
    return ExerciseCatalog(exercise_db)


# ── 1. 没有模型：基线报告也是完整形状 ────────────────────────────────────────
def test_baseline_report_has_full_shape(exercise_db) -> None:
    profile = StateRiskAgent(exercise_db).analyze(KNEE_HIGH, None)

    report = profile.risk_report
    assert report["source"] == "baseline"
    assert report["overall"]["risk_level"] == "high"
    assert report["overall"]["clearance"] == "conditional"
    assert report["overall"]["summary"]

    assert len(report["injuries"]) == 1
    injury = report["injuries"][0]
    assert injury["location"] == "knee"
    assert injury["impact_cap"] == profile.joint_caps["knee"]
    # 规则读不懂叙述，但至少把病历原话带出来，而不是编一个结论
    assert "蹲到底" in injury["functional_impact"]
    assert injury["contraindications"] == []

    assert report["dose_guidance"] == {}          # 规则给不出口径，就留空
    assert report["watch_items"]                  # 但"疼就停"这类是确定的

    # 报告不进 hash：同输入重跑不会让下游误判 STALE_PROFILE
    again = StateRiskAgent(exercise_db).analyze(KNEE_HIGH, None)
    assert again.profile_hash == profile.profile_hash


def test_clean_user_is_cleared(exercise_db) -> None:
    profile = StateRiskAgent(exercise_db).analyze(CLEAN, None)
    assert profile.risk_report["overall"]["clearance"] == "cleared"
    assert profile.risk_report["overall"]["risk_level"] == "low"
    assert profile.risk_report["injuries"] == []


# ── 2. 模型改写报告 ─────────────────────────────────────────────────────────
def test_llm_report_replaces_narrative_fields(exercise_db) -> None:
    def enhance(payload):
        return {
            "overall": {
                "risk_level": "very_high",
                "clearance": "conditional",
                "summary": "下肢只能做无痛幅度内的髋主导动作，闭链深屈膝全部回避",
            },
            "injuries": [
                {
                    "location": "knee",
                    "condition": "meniscus_tear",
                    "severity": "high",
                    "functional_impact": "屈膝超过 90° 出现内侧刺痛，闭链屈膝耐受差",
                    "contraindications": ["深屈膝闭合链负荷", "跳跃落地缓冲"],
                    "safe_substitutes": ["髋主导", "低冲击"],
                    "impact_cap": 2,
                    "load_pct_ceiling": 55,
                }
            ],
            "dose_guidance": {
                "volume": "单次不超过 12 个工作组",
                "intensity": "主项不高于 55% 1RM",
                "rest": "组间 90 秒以上",
                "progression": "两周内只加次数不加负荷",
            },
            "watch_items": ["膝内侧出现刺痛立即停止该动作"],
            "rationale": "notes 明确写了深屈膝刺痛",
        }

    profile = StateRiskAgent(exercise_db, llm_enhance_fn=enhance).analyze(KNEE_HIGH, None)

    report = profile.risk_report
    assert profile.llm_status == "applied"
    assert report["source"] == "agent"
    assert report["overall"]["risk_level"] == "very_high"
    assert "髋主导" in report["overall"]["summary"]
    assert report["injuries"][0]["contraindications"] == [
        "深屈膝闭合链负荷",
        "跳跃落地缓冲",
    ]
    assert report["dose_guidance"]["intensity"] == "主项不高于 55% 1RM"
    assert report["watch_items"] == ["膝内侧出现刺痛立即停止该动作"]


def test_llm_report_cannot_be_more_optimistic_than_constraints(exercise_db) -> None:
    """模型说「这个人可以随便练」，报告仍按更保守的一侧写。"""

    def enhance(payload):
        return {
            "overall": {
                "risk_level": "low",          # 基线是 high
                "clearance": "cleared",       # 基线是 conditional
                "summary": "没什么问题",
            },
        }

    profile = StateRiskAgent(exercise_db, llm_enhance_fn=enhance).analyze(KNEE_HIGH, None)

    # 约束没被放松，报告也不能比约束乐观
    assert profile.joint_caps["knee"] == 2
    assert profile.risk_report["overall"]["risk_level"] == "high"
    assert profile.risk_report["overall"]["clearance"] == "conditional"
    # 摘要属于叙述，模型说了算
    assert profile.risk_report["overall"]["summary"] == "没什么问题"


def test_invalid_enum_falls_back_to_baseline(exercise_db) -> None:
    def enhance(payload):
        return {
            "overall": {"risk_level": "超级危险", "clearance": "maybe", "summary": "x"},
        }

    profile = StateRiskAgent(exercise_db, llm_enhance_fn=enhance).analyze(KNEE_HIGH, None)
    assert profile.risk_report["overall"]["risk_level"] == "high"
    assert profile.risk_report["overall"]["clearance"] == "conditional"


def test_report_and_constraints_are_split(exercise_db) -> None:
    """一个响应里既有报告也有约束：两者合并自同一个判断。"""

    def enhance(payload):
        return {
            "overall": {"risk_level": "very_high", "clearance": "conditional", "summary": "保守"},
            "constraints": {
                "avoid_patterns": ["squat", "lunge"],
                "session_cap_minutes": 30,
                "impact_ceiling_override": 2,
            },
            "rationale": "深屈膝全部回避",
        }

    profile = StateRiskAgent(exercise_db, llm_enhance_fn=enhance).analyze(KNEE_HIGH, None)

    assert profile.avoid_patterns == ("lunge", "squat")
    assert profile.session_cap_minutes == 30
    assert profile.impact_ceiling == 2
    assert profile.risk_report["source"] == "agent"
    assert profile.risk_report["overall"]["risk_level"] == "very_high"


# ── 3. 报告进阶段二 ─────────────────────────────────────────────────────────
def test_plan_payload_carries_risk_report(exercise_db, catalog) -> None:
    def enhance(payload):
        return {
            "overall": {"risk_level": "high", "clearance": "conditional", "summary": "只能髋主导"},
            "dose_guidance": {"volume": "单次不超过 12 组"},
        }

    profile = StateRiskAgent(exercise_db, llm_enhance_fn=enhance).analyze(KNEE_HIGH, None)
    payload = PlanAgent().build_request_payload(profile, catalog, "lower_body")

    assert payload["risk_report"]["overall"]["summary"] == "只能髋主导"
    assert payload["risk_report"]["dose_guidance"]["volume"] == "单次不超过 12 组"
    # 报告的机器投影同时在场，两者不矛盾
    assert payload["baseline"]["joint_caps"]["knee"] == 2


def test_plan_payload_without_llm_still_has_report(exercise_db, catalog) -> None:
    profile = StateRiskAgent(exercise_db).analyze(KNEE_HIGH, None)
    payload = PlanAgent().build_request_payload(profile, catalog, "lower_body")
    assert payload["risk_report"]["source"] == "baseline"
    assert payload["risk_report"]["injuries"]


# ── 4. 报告进阶段三，并成为验收标准 ─────────────────────────────────────────
def test_judge_payload_carries_risk_report(exercise_db, catalog) -> None:
    profile = StateRiskAgent(exercise_db).analyze(KNEE_HIGH, None)
    draft = PlanDraft(
        plan_id="d",
        user_id=profile.user_id,
        workout_type="lower_body",
        phases={p: [] for p in PHASES},
        generator="llm",
        grammar_version=catalog.version,
        profile_hash=profile.profile_hash,
    )
    payload = SafetyEvalAgent().build_judge_payload(draft, profile, catalog)
    assert payload["risk_report"]["overall"]["clearance"] == "conditional"


def test_baseline_flags_catch_avoided_pattern(exercise_db, catalog) -> None:
    """报告要求回避的动作模式出现在计划里 → 机械可判的 REPORT_BREACH。"""

    def enhance(payload):
        return {"constraints": {"avoid_patterns": ["squat"]}}

    profile = StateRiskAgent(exercise_db, llm_enhance_fn=enhance).analyze(KNEE_HIGH, None)
    assert profile.avoid_patterns == ("squat",)

    target = next(
        eid
        for eid in profile.allowed_ids
        if str(catalog.meta(eid).get("motion_pattern", "")).lower() == "squat"
    )
    draft = PlanDraft(
        plan_id="d",
        user_id=profile.user_id,
        workout_type="lower_body",
        phases={p: [] for p in PHASES} | {"main_lifts": [Slot(target, 3, "8")]},
        generator="llm",
        grammar_version=catalog.version,
        profile_hash=profile.profile_hash,
    )

    flags = SafetyEvalAgent._baseline_flags(draft, profile, catalog)
    assert any(f.code == "REPORT_BREACH" and f.exercise_id == target for f in flags)
    # 降级路径下它就是判决
    report = SafetyEvalAgent().evaluate(draft, profile, catalog)
    assert report.passed is False


def test_reviewer_judges_against_report(exercise_db, catalog) -> None:
    """审查员拿到报告，可以据此判 fail —— 理由是"不适合这位用户"。"""
    profile = StateRiskAgent(exercise_db).analyze(KNEE_HIGH, None)
    seen: dict = {}

    def judge(payload):
        seen["report"] = payload["risk_report"]
        return {
            "verdict": "fail",
            "violations": [
                {
                    "code": "REPORT_BREACH",
                    "exercise_id": 0,
                    "phase": "main_lifts",
                    "reason": "报告要求回避深屈膝闭合链负荷，主项仍是全幅度深蹲",
                }
            ],
            "rationale": "与阶段一报告的功能性禁忌冲突",
        }

    draft = PlanDraft(
        plan_id="d",
        user_id=profile.user_id,
        workout_type="lower_body",
        phases={p: [] for p in PHASES},
        generator="llm",
        grammar_version=catalog.version,
        profile_hash=profile.profile_hash,
    )
    report = SafetyEvalAgent(llm_judge_fn=judge).evaluate(draft, profile, catalog)

    assert seen["report"]["overall"]["clearance"] == "conditional"
    assert report.review_mode == "agent"
    assert report.passed is False
    assert report.violations[0].code == "REPORT_BREACH"
