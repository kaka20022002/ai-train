"""Coach prompt 结构与安全边界的回归测试。

prompt 本身就是系统的核心逻辑，所以它需要和代码一样被测试锁住：
  - 安全边界不能被误删或削弱
  - 用户上下文必须进 system，不能混进 user 轮次（避免被当作指令执行）
  - 历史顺序与最后一轮提问不能被破坏
"""
from __future__ import annotations

from coach_agent import (
    COACH_PROMPT_VERSION,
    COACH_SYSTEM_PROMPT,
    CoachAgent,
    CoachContext,
    CoachResponse,
)


def _ctx() -> CoachContext:
    return CoachContext(
        user_id="u_test",
        user_profile={
            "user_id": "u_test",
            "basic_info": {"age": 28, "gender": "male"},
            "fitness_level": "beginner",
            "medical_history": [
                {"location": "knee", "condition": "meniscus_tear", "severity": "high"}
            ],
        },
        forbidden_summary="🚫 禁止动作清单（1 项）：Barbell Back Squat",
        history_summary_text="📊 训练历史：暂无训练记录。",
    )


def test_safety_boundary_present() -> None:
    assert "安全边界" in COACH_SYSTEM_PROMPT
    for kw in ("不做医学诊断", "禁止动作清单", "就医", "不承诺"):
        assert kw in COACH_SYSTEM_PROMPT, f"系统提示缺少安全关键词: {kw}"


def test_forbidden_list_not_negotiable() -> None:
    # 防回归：不能给「只做一次/轻重量试试」留让步口子
    assert "一律拒绝" in COACH_SYSTEM_PROMPT


def test_context_goes_into_system_not_user() -> None:
    msgs = CoachAgent().build_messages(_ctx(), [], "今天练什么")

    assert msgs[0]["role"] == "system"
    system = msgs[0]["content"]
    assert "<context>" in system and "</context>" in system
    assert "Barbell Back Squat" in system

    # 除最后一条用户提问外，不允许再有 user 轮次
    user_turns = [m for m in msgs[1:] if m["role"] == "user"]
    assert len(user_turns) == 1
    assert user_turns[0]["content"] == "今天练什么"


def test_history_order_and_terminator() -> None:
    history = [
        {"role": "user", "content": "第一句"},
        {"role": "assistant", "content": "第一答"},
    ]
    msgs = CoachAgent().build_messages(_ctx(), history, "第二句")

    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[1]["content"] == "第一句"
    assert msgs[2]["content"] == "第一答"
    assert msgs[-1]["content"] == "第二句"


def test_prompt_version_exposed() -> None:
    assert COACH_PROMPT_VERSION
    assert CoachResponse(content="x").prompt_version == COACH_PROMPT_VERSION
