"""意图路由：决定这一轮跑几个 Agent。"""
from __future__ import annotations

import pytest

from agents.intent import (
    AGENTS_FOR_INTENT,
    INTENT_ASK,
    INTENT_GENERATE,
    INTENT_REVISE,
    classify_intent,
)


class TestGenerate:
    @pytest.mark.parametrize(
        "message",
        [
            "我以前膝盖受伤了，半月板撕裂。现在我想做一下下肢的恢复训练，请你给我训练计划",
            "帮我制定一个下个月的增肌计划",
            "给我一份训练方案",
            "能不能给我排个课表",
            "我想要一份全身训练菜单",
            "计划重新生成一下",
            "明天该练什么",
        ],
    )
    def test_generate_signals(self, message: str) -> None:
        assert classify_intent(message, has_plan=False).intent == INTENT_GENERATE

    def test_generate_wins_over_plan_context(self) -> None:
        """已有计划时说「重新给我出一份」—— 这是重新生成，不是修改。"""
        r = classify_intent("重新给我出一份计划", has_plan=True)
        assert r.intent == INTENT_GENERATE

    def test_workout_hint(self) -> None:
        r = classify_intent("给我一份下肢训练计划")
        assert r.workout_hint == "lower_body"


class TestRevise:
    @pytest.mark.parametrize(
        "message",
        [
            "把深蹲去掉",
            "组数减少一点，太累了",
            "能不能减到30分钟",
            "换一个动作吧，这个膝盖不舒服",
            "负荷调低一些",
            "这个计划太长了，压缩到 40 分钟",
        ],
    )
    def test_revise_needs_existing_plan(self, message: str) -> None:
        assert classify_intent(message, has_plan=True).intent == INTENT_REVISE

    def test_revise_requires_plan(self) -> None:
        """没有可改的稿子时，「去掉深蹲」只能当咨询回答。"""
        assert classify_intent("把深蹲去掉", has_plan=False).intent == INTENT_ASK

    def test_explicit_revise_plan_wording(self) -> None:
        assert classify_intent("帮我改一下计划", has_plan=True).intent == INTENT_REVISE


class TestAsk:
    @pytest.mark.parametrize(
        "message",
        [
            "深蹲和硬拉有什么区别",
            "我只做深蹲可以吗",
            "时间有点紧",
            "谢谢",
            "为什么训练后要拉伸",
            "这个动作练哪里",
            # 含「调整」但是在问原理 —— 不该拿它去改用户的计划稿
            "膝盖有点紧，深蹲怎么调整？",
            "练完如何放松拉伸？",
            "今天状态一般，训练要减量吗？",
        ],
    )
    def test_questions_stay_light(self, message: str) -> None:
        assert classify_intent(message, has_plan=True).intent == INTENT_ASK

    def test_empty_message(self) -> None:
        assert classify_intent("   ").intent == INTENT_ASK


class TestAgentContract:
    def test_generate_runs_all_three(self) -> None:
        assert AGENTS_FOR_INTENT[INTENT_GENERATE] == (
            "state_risk",
            "plan_gen",
            "safety_eval",
        )

    def test_revise_runs_risk_and_review(self) -> None:
        assert AGENTS_FOR_INTENT[INTENT_REVISE] == ("state_risk", "safety_eval")
        assert "plan_gen" not in AGENTS_FOR_INTENT[INTENT_REVISE]

    def test_ask_runs_only_risk(self) -> None:
        assert AGENTS_FOR_INTENT[INTENT_ASK] == ("state_risk",)

    @pytest.mark.parametrize("message,has_plan", [
        ("给我一份计划", False),
        ("把深蹲去掉", True),
        ("深蹲伤膝盖吗", False),
    ])
    def test_result_exposes_agent_list(self, message: str, has_plan: bool) -> None:
        r = classify_intent(message, has_plan=has_plan)
        assert list(r.agents) == list(AGENTS_FOR_INTENT[r.intent])
        assert r.needs_safety_review is (r.intent != INTENT_ASK)
