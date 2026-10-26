"""把同一个 LLM 客户端切成三个不同职责的 Agent 调用入口。

这里只做一件事：**结构化 payload → prompt 文本 → 结构化 dict**。
业务校验一概不在此处发生 —— 越界过滤、单向约束合并、合取判定都在
各自的 Agent 里做，这样换掉 provider 或换掉 prompt 都不会让校验逻辑消失。

为什么共用一份 client：
    同一 provider、同一个 key、同一个 base_url，三个 Agent 的差别只在
    system prompt 和输入契约上。多 Agent 指的是**职责与上下文隔离**，
    不是指要多把钥匙或多套连接。

三个 fn 的签名刻意不一致，因为它们的契约本身不同：
    state_fn(payload)              → 单向增强用的追加建议
    plan_fn(payload, schema)       → 只有 ID 的草稿
    safety_fn(payload)             → pass/fail + 枚举违规码
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Protocol

from agents.prompts import (
    PLAN_GEN_PROMPT_VERSION,
    PLAN_GEN_SYSTEM_PROMPT,
    SAFETY_EVAL_PROMPT_VERSION,
    SAFETY_EVAL_SYSTEM_PROMPT,
    STATE_RISK_PROMPT_VERSION,
    STATE_RISK_SYSTEM_PROMPT,
)

StateFn = Callable[[Dict[str, Any]], Dict[str, Any]]
PlanFn = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
SafetyFn = Callable[[Dict[str, Any]], Dict[str, Any]]


class _JsonClient(Protocol):
    """只依赖 ``chat_json``，便于测试时替换成假的 client。"""

    def chat_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]: ...


def _render_user_prompt(task: str, payload: Dict[str, Any]) -> str:
    """把结构化 payload 原样交给模型。

    刻意不做自然语言改写：Agent 之间传的本来就是结构化字段，
    在这里「润色成一段话」会让模型有机会重新解释字段含义，
    反而破坏契约。

    也不做 ``indent`` 缩进：候选表有七十多行，缩进会让 payload 膨胀近一倍，
    而模型解析紧凑 JSON 与缩进 JSON 的能力没有差别。
    """
    return (
        f"【任务】{task}\n\n"
        "【输入数据】\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\n\n请严格按下述 schema 返回一个 JSON 对象。"
    )


# ── Agent 1：状态与风险分析（单向增强通道）────────────────────────────────
def make_state_llm_fn(client: _JsonClient) -> StateFn:
    def state_fn(payload: Dict[str, Any]) -> Dict[str, Any]:
        return client.chat_json(
            STATE_RISK_SYSTEM_PROMPT,
            _render_user_prompt(
                "审查用户病历与训练反馈，给出**追加型**约束建议。"
                "只追加风险，不得移除或放宽规则引擎已算出的约束。",
                payload,
            ),
        )

    return state_fn


# ── Agent 2：计划生成 ─────────────────────────────────────────────────────
def make_plan_llm_fn(client: _JsonClient) -> PlanFn:
    def plan_fn(payload: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
        # schema 目前只能作为形状提示写进 prompt：DeepSeek 与多数兼容网关
        # 只支持 json_object 模式，不支持把 JSON Schema 下发到解码器做 enum
        # mask。因此 enum 约束仍由 PlanAgent 在解析处兑现。
        enriched = dict(payload)
        enriched["output_schema"] = schema
        return client.chat_json(
            PLAN_GEN_SYSTEM_PROMPT,
            _render_user_prompt(
                "从各阶段候选动作中挑选本课动作。只返回 exercise_id，"
                "不要给出组数、次数或负荷。",
                enriched,
            ),
        )

    return plan_fn


# ── Agent 3：安全评估 ─────────────────────────────────────────────────────
def make_safety_llm_fn(client: _JsonClient) -> SafetyFn:
    def safety_fn(payload: Dict[str, Any]) -> Dict[str, Any]:
        return client.chat_json(
            SAFETY_EVAL_SYSTEM_PROMPT,
            _render_user_prompt(
                "审查这份训练计划是否违反给定的风险约束，"
                "返回 verdict 与违规清单（使用枚举码）。",
                payload,
            ),
        )

    return safety_fn


@dataclass
class AgentBridges:
    """三个 Agent 的 LLM 入口 + 各自的 prompt 版本，供审计记录引用。"""

    state_fn: Optional[StateFn] = None
    plan_fn: Optional[PlanFn] = None
    safety_fn: Optional[SafetyFn] = None
    state_prompt_version: str = STATE_RISK_PROMPT_VERSION
    plan_prompt_version: str = PLAN_GEN_PROMPT_VERSION
    safety_prompt_version: str = SAFETY_EVAL_PROMPT_VERSION

    @property
    def enabled(self) -> bool:
        return any(fn is not None for fn in (self.state_fn, self.plan_fn, self.safety_fn))

    def versions(self) -> Dict[str, str]:
        return {
            "state_risk": self.state_prompt_version,
            "plan_gen": self.plan_prompt_version,
            "safety_eval": self.safety_prompt_version,
        }


def build_bridges(client: _JsonClient) -> AgentBridges:
    """一个 client → 三个 Agent 入口。"""
    return AgentBridges(
        state_fn=make_state_llm_fn(client),
        plan_fn=make_plan_llm_fn(client),
        safety_fn=make_safety_llm_fn(client),
    )


__all__ = [
    "AgentBridges",
    "build_bridges",
    "make_state_llm_fn",
    "make_plan_llm_fn",
    "make_safety_llm_fn",
    "StateFn",
    "PlanFn",
    "SafetyFn",
]
