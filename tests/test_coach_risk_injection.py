"""教练侧的对话风险注入。

背景：三 Agent 只服务 `/generate_plan`。用户在教练页说「半月板撕裂」时，
这句话不会写进 user_profile，禁动作清单永远是空的，教练给的动作建议
此前完全靠 prompt 自觉。这一层负责在命中伤病信号时补一次 `state_risk`。

锁四件事：

    1. 什么时候该跑（说了伤 + 档案里没有），什么时候不该跑（闲聊 / 档案已有）；
    2. 只认模型真的给出了报告（`llm_status == "applied"`）——规则基线在
       空档案上算不出约束，注进去反而骗模型「没伤」；
    3. 没有 key / 未开 USE_REAL_LLM 时整条逻辑静默关闭，对话行为不变；
    4. 渲染出来的文本要能直接约束模型：必须含「不要做」「可以做」。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from coach_agent import (
    CoachContext,
    build_risk_context,
    needs_risk_analysis,
    render_risk_brief,
)

EMPTY_PROFILE = {"user_id": "usr_demo", "basic_info": {"age": 30}, "medical_history": []}

KNEE_IN_PROFILE = {
    "user_id": "usr_knee",
    "medical_history": [
        {"location": "knee", "condition": "meniscus_tear", "severity": "high"}
    ],
}


def _profile(**over):
    base = {
        "llm_status": "applied",
        "risk_report": {
            "source": "agent",
            "overall": {
                "risk_level": "high",
                "clearance": "conditional",
                "summary": "下肢只做髋主导与低冲击，负荷不超过50%，时长不超过30分钟",
            },
            "injuries": [
                {
                    "location": "knee",
                    "condition": "meniscus_tear（术后两年）",
                    "functional_impact": "蹲到底膝内侧刺痛",
                    "contraindications": ["深屈膝闭合链负荷", "跳跃与落地缓冲"],
                    "safe_substitutes": ["髋主导铰链", "低冲击核心"],
                }
            ],
            "dose_guidance": {"session_minutes": 30},
            "watch_items": ["训练中膝痛加重立即停止"],
        },
    }
    base.update(over)
    return SimpleNamespace(**base)


# ── 1. 触发条件 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "message",
    [
        "我以前膝盖受伤了，半月板撕裂，想做下肢恢复训练",
        "半月板撕裂",
        "最近练完膝盖疼",
    ],
)
def test_injury_message_triggers_analysis(message: str) -> None:
    assert needs_risk_analysis(message, EMPTY_PROFILE)


@pytest.mark.parametrize(
    "message",
    [
        "今天练什么？",
        "今天时间有点紧，能快点吗",  # 「紧」是感受词，但没提部位，不该触发
        "帮我生成下周的计划",
    ],
)
def test_small_talk_does_not_trigger(message: str) -> None:
    assert not needs_risk_analysis(message, EMPTY_PROFILE)


def test_existing_injury_in_profile_does_not_retrigger() -> None:
    """档案里已有膝关节伤情 —— 建档时禁动作清单就算过了，不必每轮重跑。"""

    assert not needs_risk_analysis("我今天膝盖有点不舒服", KNEE_IN_PROFILE)


def test_new_joint_triggers_even_if_profile_has_other_injury() -> None:
    """档案里只有膝，用户现在说肩 —— 这是新伤情，必须重算。"""

    assert needs_risk_analysis("最近肩膀推举的时候有点夹", KNEE_IN_PROFILE)


# ── 2. 只认模型报告 ─────────────────────────────────────────────────────────
def test_render_requires_applied_status() -> None:
    assert render_risk_brief(_profile(llm_status="skipped")) is None
    assert render_risk_brief(_profile(llm_status="error")) is None
    assert render_risk_brief(None) is None


def test_render_contains_actionable_constraints() -> None:
    text = render_risk_brief(_profile())

    assert text is not None
    assert "不要做" in text and "可以做" in text
    assert "深屈膝闭合链负荷" in text
    assert "髋主导铰链" in text
    assert "高风险" not in text  # 等级已中文化
    assert "风险等级：高" in text


def test_render_skips_empty_report() -> None:
    empty = _profile(risk_report={"overall": {}, "injuries": []})
    assert render_risk_brief(empty) is None


# ── 3. 没有模型时静默关闭 ───────────────────────────────────────────────────
def test_no_llm_means_no_injection(monkeypatch) -> None:
    monkeypatch.setenv("USE_REAL_LLM", "false")
    assert build_risk_context(EMPTY_PROFILE, "我半月板撕裂了") is None


def test_missing_key_means_no_injection(monkeypatch) -> None:
    monkeypatch.setenv("USE_REAL_LLM", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert build_risk_context(EMPTY_PROFILE, "我半月板撕裂了") is None


# ── 4. 注入位置 ─────────────────────────────────────────────────────────────
def test_context_render_puts_risk_report_before_forbidden_list() -> None:
    ctx = CoachContext(
        user_id="usr_demo",
        user_profile=EMPTY_PROFILE,
        risk_report_text="🩺 本轮风险报告：…",
        forbidden_summary="🚫 禁止动作清单：…",
    )
    rendered = ctx.render()

    assert "本轮风险报告" in rendered
    assert rendered.index("本轮风险报告") < rendered.index("禁止动作清单")
