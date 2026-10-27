"""对话意图路由 —— 决定这一轮要跑几个 Agent。

需求（2026-10-27）：用户在**对话里**提出生成计划，就必须走完整的三个 Agent；
后续的修改或问答可以只过一部分。

    generate_plan   1 → 2 → 3   状态分析 + 计划生成 + 安全会审（一个都不能少）
    revise_plan     1 → 3       风险按需重算 + 改完的稿子必须过审
    ask             1           只做状态分析（命中伤病时），其余交给教练回答

为什么用规则而不是让模型分类：
    分类结果直接决定「跑不跑审查 Agent」。如果把这一步交给模型，模型误判成
    ``ask`` 就等于**静默跳过安全审查** —— 而这正是要修的漏洞。规则可以穷举、
    可以测试、可以断言，误判方向也能自己控制（拿不准就升级到更严的一条）。

判定顺序刻意是「生成 > 修改 > 问答」：越严的路径优先级越高，宁可多跑一个
Agent，也不能因为一句话说得含糊就把审查省掉。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

INTENT_GENERATE = "generate_plan"
INTENT_REVISE = "revise_plan"
INTENT_ASK = "ask"

#: 每条意图需要跑哪些 Agent —— 对外暴露，便于调用方与测试直接核对
AGENTS_FOR_INTENT = {
    INTENT_GENERATE: ("state_risk", "plan_gen", "safety_eval"),
    INTENT_REVISE: ("state_risk", "safety_eval"),
    INTENT_ASK: ("state_risk",),
}


@dataclass(frozen=True)
class IntentResult:
    intent: str
    reason: str
    #: 用户这次想要练的部位/类型（若能识别），供生成端使用
    workout_hint: Optional[str] = None

    @property
    def agents(self) -> Sequence[str]:
        return AGENTS_FOR_INTENT.get(self.intent, ("state_risk",))

    @property
    def needs_generation(self) -> bool:
        return self.intent == INTENT_GENERATE

    @property
    def needs_safety_review(self) -> bool:
        return self.intent in (INTENT_GENERATE, INTENT_REVISE)


# ── 词表 ────────────────────────────────────────────────────────────────────
# 「计划」类名词：没有它们就不是在要方案
_PLAN_NOUN = r"(?:训练计划|健身计划|恢复计划|计划|方案|课表|训练安排|菜单|routine)"

# 生成动词（正向语序：动词 … 名词）
_GEN_VERB_FWD = (
    r"(?:生成|制定|定制|设计|安排|规划|编排|重新出|出一?份|做一?份|来一?份|"
    r"给一?份|给我|帮我|帮忙|想要|需要|要)"
)
# 生成动词（反向语序：名词 … 动词）
_GEN_VERB_BACK = r"(?:生成|做|出|安排|制定|设计|来)"

_GENERATE_FWD = re.compile(
    rf"{_GEN_VERB_FWD}[^。！？?；\n]{{0,12}}{_PLAN_NOUN}"
)
_GENERATE_BACK = re.compile(
    rf"{_PLAN_NOUN}[^。！？?；\n]{{0,8}}{_GEN_VERB_BACK}"
)
# 「练什么 / 怎么练 / 该做哪些动作」—— 没出现「计划」二字，但语义就是要方案
_GENERATE_IMPLICIT = re.compile(
    r"(?:今天|这几天|现在|接下来|本周)?[^。！？?；\n]{0,6}"
    r"(?:练什么|怎么练|如何练|练点啥|做什么动作|该做哪些动作|给我一?个?训练)"
)

# 修改动词：只在「已经有计划」时才成立
_REVISE_VERB = re.compile(
    r"(?:改|换掉?|替换|调整|删掉?|去掉|取消|加上?|增加|减少|减到|减至|降到|降至|"
    r"提到|调低|调高|缩短|延长|精简|压缩到|压缩|压到|缩到|控制在|"
    r"太多了|太少了|太累|太重|太轻|太短|太长|太久|不行|不满意|"
    r"换一个|改成|改到|减一?点|多一?点|少一?点)"
)
# 明确的「改计划」措辞，即使没有活跃计划也按修改处理
_REVISE_PLAN_WORD = re.compile(
    rf"(?:改|调整|修改|重做|重排|换)[^。！？?；\n]{{0,6}}{_PLAN_NOUN}"
)

# 求解释的问法。「膝盖有点紧，深蹲怎么调整？」是在问原理，不是让你直接改稿
_EXPLAIN = re.compile(
    r"(怎么|如何|为什么|为何|是什么|区别|原理|要不要|该不该|需要注意|对不对)"
)
# 强祈使 —— 出现这些就不再算「只是想问问」
_IMPERATIVE = re.compile(
    r"(帮我改|改一下|修改一下|去掉|删掉|换成|调整成|改成|重新排)"
)

# 部位/类型提示（仅用于给生成端一点上下文，识别不到也无所谓）
_WORKOUT_HINTS = (
    ("下肢", "lower_body"),
    ("腿", "lower_body"),
    ("上肢", "upper_body"),
    ("胸", "upper_body"),
    ("背", "upper_body"),
    ("核心", "core"),
    ("腹", "core"),
    ("全身", "full_body"),
    ("恢复", "lower_body"),
    ("康复", "lower_body"),
)


def _workout_hint(text: str) -> Optional[str]:
    for word, tag in _WORKOUT_HINTS:
        if word in text:
            return tag
    return None


def classify_intent(
    message: str,
    *,
    has_plan: bool = False,
    history: Optional[Sequence[str]] = None,
) -> IntentResult:
    """把一条用户消息分到三条链路之一。

    ``has_plan`` 表示当前用户/会话是否已有一份可修改的计划（决定「改一下」
    能不能算修改意图）。``history`` 只用于在消息本身过于简短时补齐上下文
    （例如用户只回一句「重来」）。
    """

    text = (message or "").strip()
    if not text:
        return IntentResult(INTENT_ASK, "空消息，按问答处理")

    hint = _workout_hint(text)

    # ① 明确在改现有计划 —— 先判，否则「帮我改一下计划」会被「帮我…计划」
    #    这条宽松的生成规则吃掉，多跑一次完整生成。
    if has_plan and _REVISE_PLAN_WORD.search(text):
        return IntentResult(INTENT_REVISE, "命中「改 + 计划」，且有现存计划", hint)

    # ② 生成计划 —— 误判代价最小（多跑一个 Agent 而已）
    if _GENERATE_FWD.search(text) or _GENERATE_BACK.search(text):
        return IntentResult(INTENT_GENERATE, "命中「生成动词 + 计划名词」", hint)

    # ③ 求解释的问法 —— 别因为「调整」二字就去改用户的计划稿
    if _EXPLAIN.search(text) and not _IMPERATIVE.search(text):
        return IntentResult(INTENT_ASK, "含「怎么/如何/为什么」等求解释用语", hint)

    # ④ 修改计划 —— 需要确实有可改的稿子
    if has_plan and _REVISE_VERB.search(text):
        return IntentResult(INTENT_REVISE, "命中修改动词，且有现存计划", hint)

    # ③ 没提计划二字、但明显在要方案
    if _GENERATE_IMPLICIT.search(text):
        return IntentResult(INTENT_GENERATE, "命中「练什么 / 怎么练」类表述", hint)

    # ④ 追问上一轮的计划（「那第二天的呢」「这个能天天做吗」）
    if has_plan and history is not None and len(text) <= 12:
        return IntentResult(INTENT_ASK, "短追问，沿用上文的计划上下文", hint)

    return IntentResult(INTENT_ASK, "未命中生成或修改信号，按问答处理", hint)


__all__ = [
    "INTENT_GENERATE",
    "INTENT_REVISE",
    "INTENT_ASK",
    "AGENTS_FOR_INTENT",
    "IntentResult",
    "classify_intent",
]
