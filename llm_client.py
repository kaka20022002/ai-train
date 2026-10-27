"""LLM Client integration for workout plan generation.

This module wraps calls to a real LLM (e.g., OpenAI GPT models or
MiniMax) so that the rest of the system can request a workout plan
in a structured JSON format.

The client is intentionally provider-agnostic at the interface level
and currently supports three providers via environment configuration:

- ``LLM_PROVIDER=openai``  (默认，使用 OpenAI SDK)
    - ``OPENAI_API_KEY``: API key (必需)
    - ``OPENAI_MODEL``:   模型名 (可选，默认 "gpt-4.1")
    - ``OPENAI_BASE_URL``: 自定义网关地址 (可选)

- ``LLM_PROVIDER=minimax``  (MiniMax HTTP/OpenAI 兼容接口)
    - ``MINIMAX_API_KEY``: API key (必需)
    - ``MINIMAX_MODEL``:   模型名，例如 "abab6.5-chat" 等 (必需)
    - ``MINIMAX_API_URL``: 完整的聊天接口 URL (必需，按官方文档填写)

- ``LLM_PROVIDER=minimax_anthropic``  (MiniMax Anthropic SDK 接口)
    - ``MINIMAX_API_KEY``:  API key (必需)
    - ``MINIMAX_MODEL``:    模型名，例如 "MiniMax-M2.7" (必需)
    - ``MINIMAX_BASE_URL``: Anthropic 兼容端点 URL (可选；不填则使用
                            Anthropic 默认端点)

Usage
-----

    from llm_client import LLMClient

    client = LLMClient()
    plan_dict = client.generate_workout_plan(...)

The returned plan_dict matches the structure produced by
PlanGeneratorMock.export_plan_as_json, so it can be converted back
into a WorkoutPlan instance using PlanGeneratorMock._plan_from_json.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, Generator, List

import httpx

from risk_engine import ForbiddenExercise, RiskConstraint


# Sentinel for "call this provider as plain text, do NOT send response_format".
# ``None`` keeps the historical default (json_object), so a distinct value is
# needed to opt out explicitly.
NO_RESPONSE_FORMAT = "__no_response_format__"

# Providers that reject ``response_format`` (or accept it only under extra
# prompt conditions) answer with a 400 whose body mentions one of these.
_FORMAT_REJECTION_MARKERS = (
    "response_format",
    "json_object",
    "must contain the word 'json'",
    "unsupported parameter",
)


def _is_format_rejection(err: str) -> bool:
    """True when *err* looks like a 400 caused by ``response_format``."""

    low = err.lower()
    if "400" not in low and "badrequest" not in low:
        return False
    return any(marker in low for marker in _FORMAT_REJECTION_MARKERS)


# Chinese labels for the canonical equipment taxonomy (Sprint 3).
_EQUIPMENT_CN = {
    "bodyweight": "自重",
    "barbell": "杠铃",
    "dumbbell": "哑铃",
    "machine": "固定器械",
    "cable": "龙门/绳索",
    "kettlebell": "壶铃",
    "resistance_band": "弹力带",
    "bench": "卧推凳",
    "pull_up_bar": "单杠/引体架",
    "squat_rack": "深蹲架",
}


def _equipment_block(user_profile: Dict[str, Any]) -> str:
    """
    Build an equipment-constraint prompt block.

    The safe-exercise list is already equipment-filtered upstream, so this block
    mainly steers the LLM's freely-chosen warm-up/activation/cool-down picks to
    bodyweight or available-gear movements.
    """
    equipment = user_profile.get("available_equipment")
    if not equipment:
        return ""
    labels = "、".join(_EQUIPMENT_CN.get(e, e) for e in equipment)
    return (
        "【可用器材】用户仅有以下器材：" + labels + "（外加自重）。\n"
        "所有动作（含热身、激活、放松）必须只使用上述器材或纯自重，"
        "禁止安排需要其他器材的动作。\n\n"
    )


def _extract_json_object(text: str) -> Dict[str, Any]:
    """Recover a single JSON object from a model reply.

    Handles the three shapes actually observed in practice:

    1. a clean JSON object;
    2. a ```` ```json ... ``` ```` fenced block;
    3. a leading sentence followed by the object ("好的，以下是结果：{...}").

    Only a JSON *object* is accepted — an array or a bare scalar means the
    caller's prompt was not followed, and guessing a mapping out of it would
    hide the failure.
    """
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json|JSON)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()

    candidates: List[str] = [raw]
    lo, hi = raw.find("{"), raw.rfind("}")
    if lo != -1 and hi > lo:
        candidates.append(raw[lo : hi + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            return data

    raise ValueError(
        "Could not parse a JSON object from the LLM reply. "
        f"Raw content (first 300 chars): {text[:300]!r}"
    )


def _validate_plan_schema(plan_data: Dict[str, Any]) -> None:
    """Validate that an LLM-generated plan dict contains required fields.

    Raises:
        ValueError: If any required field is missing or structurally invalid,
            so the caller can safely fall back to the Mock generator rather
            than silently returning an empty/broken plan.
    """
    if not isinstance(plan_data, dict):
        raise ValueError(
            f"LLM plan must be a JSON object, got {type(plan_data).__name__}."
        )

    required_top = ("plan_id", "workout_type", "phases")
    missing_top = [k for k in required_top if k not in plan_data]
    if missing_top:
        raise ValueError(
            f"LLM plan is missing required top-level fields: {missing_top}. "
            f"Keys present: {list(plan_data.keys())}"
        )

    phases = plan_data["phases"]
    if not isinstance(phases, dict):
        raise ValueError(
            f"LLM plan 'phases' must be a JSON object, got {type(phases).__name__}."
        )

    required_phases = ("warm_up", "activation", "main_lifts", "accessories", "cool_down")
    missing_phases = [p for p in required_phases if p not in phases]
    if missing_phases:
        raise ValueError(
            f"LLM plan 'phases' is missing sections: {missing_phases}. "
            f"Sections present: {list(phases.keys())}"
        )

    if not phases.get("main_lifts"):
        raise ValueError(
            "LLM plan 'phases.main_lifts' is empty. "
            "The plan must contain at least one main lift exercise."
        )

    required_ex = ("name", "sets", "reps")
    for phase_key in required_phases:
        for idx, ex in enumerate(phases[phase_key]):
            if not isinstance(ex, dict):
                raise ValueError(
                    f"LLM plan phases.{phase_key}[{idx}] must be a JSON object."
                )
            missing_ex = [f for f in required_ex if f not in ex]
            if missing_ex:
                raise ValueError(
                    f"LLM plan phases.{phase_key}[{idx}] is missing fields "
                    f"{missing_ex}. Exercise data: {ex}"
                )


class LLMClient:
    """Simple wrapper around chat-completion style LLM APIs.

    This client focuses on a single capability: generating a structured
    workout plan JSON that respects safety constraints. It supports
    multiple providers, selected via the ``LLM_PROVIDER`` environment
    variable (``openai``, ``minimax``, ``minimax_anthropic``).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        # Determine provider first
        self.provider = os.getenv("LLM_PROVIDER", "openai").lower()

        if self.provider == "openai":
            # Resolve configuration from explicit args or environment
            self.api_key = api_key or os.getenv("OPENAI_API_KEY")
            if not self.api_key:
                raise ValueError(
                    "OPENAI_API_KEY is not set. Set it in the environment "
                    "to enable OpenAI LLM integration."
                )

            self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1")
            self.base_url = base_url or os.getenv("OPENAI_BASE_URL")

            # Initialize OpenAI client lazily to avoid hard dependency
            from openai import OpenAI  # type: ignore[import-not-found]

            if self.base_url:
                self._openai_client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            else:
                self._openai_client = OpenAI(api_key=self.api_key)

        elif self.provider == "minimax":
            # MiniMax 示例集成：通过 HTTP API 调用
            self.api_key = api_key or os.getenv("MINIMAX_API_KEY")
            if not self.api_key:
                raise ValueError(
                    "MINIMAX_API_KEY is not set. Set it in the environment "
                    "to enable MiniMax LLM integration."
                )

            # 模型名和接口 URL 需要根据 MiniMax 官方文档配置
            self.model = model or os.getenv("MINIMAX_MODEL")
            if not self.model:
                raise ValueError("MINIMAX_MODEL is not set.")

            # 完整的聊天接口 URL，例如 "https://api.minimax.chat/v1/chat/completions"
            self.base_url = base_url or os.getenv("MINIMAX_API_URL")
            if not self.base_url:
                raise ValueError("MINIMAX_API_URL is not set.")

        elif self.provider == "minimax_anthropic":
            # MiniMax via Anthropic SDK
            # 官方文档：https://platform.minimaxi.com/docs/llms
            # 推荐使用标准 Anthropic 环境变量（SDK 自动读取）：
            #   ANTHROPIC_API_KEY  = 你的 MiniMax API Key
            #   ANTHROPIC_BASE_URL = https://api.minimaxi.com/anthropic
            # 也兼容 MINIMAX_API_KEY / MINIMAX_BASE_URL（优先级更低）
            self.api_key = (
                api_key
                or os.getenv("ANTHROPIC_API_KEY")
                or os.getenv("MINIMAX_API_KEY")
            )
            if not self.api_key:
                raise ValueError(
                    "API key not set. Please set ANTHROPIC_API_KEY "
                    "(or MINIMAX_API_KEY) to enable MiniMax integration."
                )

            self.model = model or os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")

            # MiniMax Anthropic 兼容端点（官方默认）
            _default_base_url = "https://api.minimaxi.com/anthropic"
            self.base_url = (
                base_url
                or os.getenv("ANTHROPIC_BASE_URL")
                or os.getenv("MINIMAX_BASE_URL")
                or _default_base_url
            )

            from anthropic import Anthropic  # type: ignore[import-not-found]

            # 显式传入 key/base_url，并临时屏蔽环境里的 ANTHROPIC_AUTH_TOKEN，
            # 防止本机 DeepSeek 等全局配置劫持本次请求。
            _saved_auth_token = os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)
            try:
                self._anthropic_client = Anthropic(
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
            finally:
                if _saved_auth_token is not None:
                    os.environ["ANTHROPIC_AUTH_TOKEN"] = _saved_auth_token

            print(
                f"✅ LLMClient ready: provider={self.provider} "
                f"model={self.model} base_url={self.base_url}"
            )

        else:
            raise ValueError(f"Unsupported LLM_PROVIDER: {self.provider}")

    def generate_workout_plan(
        self,
        constraints_text: str,
        user_profile: Dict[str, Any],
        workout_type: str,
        safe_exercises: List[str],
        forbidden_exercises: List[ForbiddenExercise],
        constraints: List[RiskConstraint],
        history_context: str = "",
    ) -> Dict[str, Any]:
        """Call the LLM to generate a workout plan.

        The LLM is instructed to return a single JSON object with the
        following structure (keys are required unless noted):

        {
          "plan_id": "string",
          "user_id": "string",
          "date": "YYYY-MM-DD",
          "workout_type": "full_body" | "upper_body" | ...,
          "estimated_duration_minutes": 45,
          "phases": {
            "warm_up": [Exercise],
            "activation": [Exercise],
            "main_lifts": [Exercise],
            "accessories": [Exercise],
            "cool_down": [Exercise]
          },
          "safety_notes": ["..."]
        }

        Each Exercise item is:

        {
          "name": "string",
          "sets": 3,
          "reps": "8-12" 或 "30 seconds",
          "rest_seconds": 90,
          "notes": "optional string or null",
          "target_muscle": "optional string or null"
        }
        """

        forbidden_summary = [
            {
                "name": ex.name,
                "reason": ex.reason,
                "risk_level": ex.risk_level,
                "involved_joints": ex.involved_joints,
                "substitution": ex.substitution,
            }
            for ex in forbidden_exercises
        ]

        constraints_summary = [
            {
                "type": c.constraint_type,
                "priority": c.priority,
                "description": c.description,
                "affected_joints": c.affected_joints,
            }
            for c in constraints
        ]

        system_prompt = (
            "你是一名资深 NSCA-CSCS 认证的力量与体能教练，同时也是一个"
            "以安全为首要原则的训练计划生成器。你生成的计划必须：\n"
            "1. 严格遵守所有安全约束、禁止动作和受影响关节；\n"
            "2. 真实可用：给出具体的组数、次数、组间休息、强度（自觉强度 1–10 或 %一次最大重量），"
            "并包含关键技术要点（动作要领、呼吸节奏、注意事项）；\n"
            "3. 结构科学：遵循热身→激活→主项→辅助→放松的五阶段结构；\n"
            "4. 适配用户水平：初级重学习动作、中级平衡量与强度、高级追求进步。\n"
            "5. 面向用户的字段（notes、safety_notes、intensity_note 等）一律使用简体中文，"
            "用「自觉强度」描述用力感，用「一次最大重量」描述 %1RM。\n"
            "你只返回 JSON，不输出任何其他文字。"
        )

        history_block = (
            "\n【历史训练分析（AI教练上下文）】\n" + history_context + "\n\n"
            if history_context.strip() else ""
        )

        user_content = (
            "请为下一次训练生成一份完整、可执行的训练计划。\n\n"
            + history_block
            + "【安全约束文本】\n" + constraints_text + "\n\n"
            "【用户档案】\n"
            + json.dumps(user_profile, ensure_ascii=False) + "\n\n"
            "【训练类型】 " + workout_type + "\n\n"
            + _equipment_block(user_profile)
            + "【可用动作列表】（主项与辅助必须从该列表选择，英文名称保持原样）\n"
            + json.dumps(safe_exercises, ensure_ascii=False) + "\n\n"
            "【禁止动作】\n"
            + json.dumps(forbidden_summary, ensure_ascii=False) + "\n\n"
            "【动态约束】\n"
            + json.dumps(constraints_summary, ensure_ascii=False) + "\n\n"
            "【内容要求】\n"
            "- `name`：主项/辅助动作名称使用与【可用动作列表】中完全一致的"
            "英文名（便于系统识别）；热身/激活/放松动作可自行选择合适动作，"
            "直接使用英文名。\n"
            "- `sets`：整数，2-5。\n"
            "- `reps`：字符串，例如 \"8-10\"、\"12\"、\"30 seconds\"、"
            "\"15 each side\"。\n"
            "- `rest_seconds`：整数秒。主项 90-180s，辅助 45-90s，"
            "热身/放松 0-30s。\n"
            "- `notes`：**必填**，使用中文，100 字以内，包含：\n"
            "    · 强度指引（自觉强度 6–8 或 %一次最大重量，或「轻重量学习动作」）\n"
            "    · 1-2 条动作要领（如 '下蹲时膝盖对准脚尖，保持脊柱中立'）\n"
            "    · 如有伤病相关禁忌，显式提醒。\n"
            "- `target_muscle`：主要目标肌群英文名（例如 Pectorals、Quadriceps）。\n"
            "- `safety_notes`：3-6 条中文安全提示，针对本次用户档案与反馈量身定制。\n"
            "- `estimated_duration_minutes`：合理估算总时长（分钟）。\n\n"
            "【输出格式要求（极其重要）】\n"
            "- 仅输出一个 JSON 对象，不要 Markdown、不要代码块、不要任何多余文字。\n"
            "- JSON 结构必须严格如下：\n"
            "  {\n"
            "    \"plan_id\": string,\n"
            "    \"user_id\": string,\n"
            "    \"date\": string (YYYY-MM-DD),\n"
            "    \"workout_type\": string,\n"
            "    \"estimated_duration_minutes\": integer,\n"
            "    \"phases\": {\n"
            "      \"warm_up\":     [Exercise, ...] (3-5 个),\n"
            "      \"activation\":  [Exercise, ...] (2-4 个),\n"
            "      \"main_lifts\":  [Exercise, ...] (2-3 个),\n"
            "      \"accessories\": [Exercise, ...] (3-4 个),\n"
            "      \"cool_down\":   [Exercise, ...] (3-5 个)\n"
            "    },\n"
            "    \"safety_notes\": [中文字符串, ...]\n"
            "  }\n\n"
            "Exercise 对象结构：\n"
            "  {\n"
            "    \"name\": string (英文动作名),\n"
            "    \"sets\": integer,\n"
            "    \"reps\": string,\n"
            "    \"rest_seconds\": integer,\n"
            "    \"notes\": string (中文、含强度+要领),\n"
            "    \"target_muscle\": string (英文肌群名)\n"
            "  }\n"
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        max_attempts = 3  # initial attempt + up to 2 retries
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            content = self._call_provider(messages)

            try:
                plan_data = json.loads(content)
            except json.JSONDecodeError as exc:
                last_error = ValueError(
                    f"LLM did not return valid JSON (attempt {attempt}). "
                    f"Raw content: {content!r}"
                )
                if attempt < max_attempts:
                    # Ask the model to fix its output in the next turn
                    messages = messages + [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                "Your previous response was not valid JSON. "
                                "Please respond with ONLY a valid JSON object "
                                "that matches the schema described earlier. "
                                "Do not include any Markdown or extra text."
                            ),
                        },
                    ]
                continue

            try:
                _validate_plan_schema(plan_data)
            except ValueError as exc:
                last_error = exc
                if attempt < max_attempts:
                    messages = messages + [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": (
                                f"Your previous response failed schema validation: "
                                f"{exc}. Please fix and return a complete JSON "
                                "object matching the required schema."
                            ),
                        },
                    ]
                continue

            # Success
            return plan_data

        raise ValueError(
            f"LLM failed to produce a valid plan after {max_attempts} attempts. "
            f"Last error: {last_error}"
        )

    def _call_provider(
        self,
        messages: List[Dict[str, str]],
        response_format: Dict[str, Any] | str | None = None,
    ) -> str:
        """Send *messages* to the configured provider and return raw content.

        Automatically retries on transient server errors (HTTP 429 / 529)
        with exponential back-off.

        ``response_format`` semantics:
          * ``None``                 → historical default, ``{"type": "json_object"}``
          * a dict                   → sent as-is
          * ``NO_RESPONSE_FORMAT``   → omitted entirely (plain text call)

        If the provider rejects the requested format with a 400 (some gateways
        don't implement ``json_object``, and DeepSeek additionally requires the
        prompt itself to contain the word "json"), the call is retried once
        without ``response_format`` instead of failing the whole request.
        """
        # Retry schedule for transient errors (529 overloaded / 429 rate limit):
        # wait 15s, 30s, 60s, 120s between attempts → max 5 attempts total.
        retry_waits = [15, 30, 60, 120]

        for attempt in range(len(retry_waits) + 1):
            try:
                return self._call_provider_once(messages, response_format=response_format)
            except Exception as exc:
                err_str = str(exc)

                # 400 caused by response_format → downgrade to plain text once.
                if response_format is not NO_RESPONSE_FORMAT and _is_format_rejection(
                    err_str
                ):
                    print(
                        "   ⚠️ Provider rejected response_format, "
                        "retrying as plain text..."
                    )
                    return self._call_provider(
                        messages, response_format=NO_RESPONSE_FORMAT
                    )

                is_transient = (
                    "529" in err_str
                    or "overloaded" in err_str.lower()
                    or "429" in err_str
                    or "rate_limit" in err_str.lower()
                    or "timed out" in err_str.lower()
                    or "timeout" in err_str.lower()
                    or "interrupted" in err_str.lower()
                    or "RateLimitError" in type(exc).__name__
                    or "OverloadedError" in type(exc).__name__
                    or "APITimeoutError" in type(exc).__name__
                    or "Timeout" in type(exc).__name__
                )
                if is_transient and attempt < len(retry_waits):
                    wait = retry_waits[attempt]
                    print(
                        f"   ⏳ Provider overloaded/rate-limited "
                        f"(attempt {attempt + 1}/{len(retry_waits) + 1}). "
                        f"Retrying in {wait}s..."
                    )
                    time.sleep(wait)
                else:
                    raise

        raise RuntimeError("Unreachable")  # pragma: no cover

    def _call_provider_once(
        self,
        messages: List[Dict[str, str]],
        response_format: Dict[str, Any] | str | None = None,
    ) -> str:
        """Single attempt to call the provider (no retry logic here)."""

        if self.provider == "openai":
            kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
            }
            # 默认沿用历史上的 json_object 模式（generate_workout_plan 依赖它）；
            # 显式传入 response_format 时以调用方为准；传 NO_RESPONSE_FORMAT
            # 表示纯文本调用，完全不带该参数。
            if response_format is not NO_RESPONSE_FORMAT:
                kwargs["response_format"] = (
                    response_format
                    if response_format is not None
                    else {"type": "json_object"}
                )
            completion = self._openai_client.chat.completions.create(**kwargs)
            return completion.choices[0].message.content

        if self.provider == "minimax":
            # MiniMax HTTP API 调用示例
            # 具体字段名称可能会随官方版本略有不同，请根据官方
            # 文档调整 payload / 响应解析逻辑。
            payload: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
            }
            if response_format is not None:
                payload["response_format"] = response_format
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            resp = httpx.post(self.base_url, json=payload, headers=headers, timeout=60.0)
            resp.raise_for_status()
            resp_data = resp.json()

            # 尝试按 OpenAI 风格解析；若你的 MiniMax 返回格式不同，
            # 可以在这里根据实际字段名做定制。
            try:
                return resp_data["choices"][0]["message"]["content"]
            except Exception as exc:  # noqa: BLE001
                raise ValueError(
                    "Unexpected MiniMax response format. Please adjust "
                    "llm_client.py to match the actual API schema. "
                    f"Raw response: {resp_data!r}"
                ) from exc

        if self.provider == "minimax_anthropic":
            # MiniMax via Anthropic SDK
            # messages 中第一条 system 消息需要单独传给 system= 参数；
            # 其余消息按 Anthropic 格式传入 messages=。
            system_content = ""
            anthropic_messages: List[Dict[str, Any]] = []

            for msg in messages:
                if msg["role"] == "system":
                    system_content = msg["content"]
                else:
                    anthropic_messages.append(
                        {
                            "role": msg["role"],
                            "content": [{"type": "text", "text": msg["content"]}],
                        }
                    )

            response = self._anthropic_client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_content,
                messages=anthropic_messages,  # type: ignore[arg-type]
                timeout=180.0,  # 3 minutes: M2.7 can be slow for long plans
            )

            # 收集所有 text 块内容（跳过 thinking 块）
            text_parts: List[str] = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)

            if not text_parts:
                raise ValueError(
                    "MiniMax Anthropic response contained no text content. "
                    f"Block types received: {[b.type for b in response.content]}"
                )

            return "".join(text_parts)

        # 理论上不会到达这里，因为 __init__ 已经校验
        raise RuntimeError(f"Unsupported provider at runtime: {self.provider}")

    # =========================================================================
    # Phase 3 — Multi-week program generation
    # =========================================================================

    def generate_training_program(
        self,
        user_profile: Dict[str, Any],
        goal: str,
        total_weeks: int,
        sessions_per_week: int,
        split_type: str,
        safe_exercises: List[str],
        forbidden_exercises: List[ForbiddenExercise],
        history_context: str = "",
    ) -> Dict[str, Any]:
        """
        Ask the LLM to generate a complete multi-week training program.

        Returns a program dict matching the TrainingProgram JSON schema
        (same shape as ProgramGeneratorService._mock_generate output).
        Falls back gracefully — callers should catch ValueError.
        """
        forbidden_summary = [
            {"name": ex.name, "reason": ex.reason, "substitution": ex.substitution}
            for ex in forbidden_exercises
        ]
        goal_cn = {
            "strength": "最大力量", "hypertrophy": "肌肉增长", "general_fitness": "综合体能"
        }.get(goal, goal)
        split_cn = {
            "full_body": "全身训练", "upper_lower": "上下肢分化",
            "push_pull_legs": "推拉腿分化",
        }.get(split_type, split_type)

        history_block = (
            "\n【历史训练分析】\n" + history_context + "\n\n"
            if history_context.strip() else ""
        )

        system_prompt = (
            "你是一名资深 NSCA-CSCS 认证的力量与体能教练，专门设计系统化周期训练计划。"
            "你生成的计划必须：\n"
            "1. 严格遵守所有伤病约束和禁止动作；\n"
            "2. 基于科学周期化原则（线性/分块进阶）安排周次结构；\n"
            "3. 每个训练日包含 3-5 个主要动作，有组数、次数、组间休息和强度指引；\n"
            "4. 最后一周或每 4 周设置减量周；\n"
            "5. 仅输出 JSON，不输出任何其他文字。"
        )

        user_content = (
            f"请为以下用户生成一份 {total_weeks} 周的{goal_cn}训练计划。\n\n"
            + history_block
            + "【用户档案】\n"
            + json.dumps(user_profile, ensure_ascii=False) + "\n\n"
            + f"【训练目标】{goal_cn}（{total_weeks} 周，每周 {sessions_per_week} 次，{split_cn}）\n\n"
            + _equipment_block(user_profile)
            + "【可用动作列表】（主项必须从此列表选取）\n"
            + json.dumps(safe_exercises[:30], ensure_ascii=False) + "\n\n"
            + "【禁止动作】\n"
            + json.dumps(forbidden_summary, ensure_ascii=False) + "\n\n"
            + "【输出 JSON 格式（严格遵守）】\n"
            + "{\n"
            + '  "name": "计划名称（中文）",\n'
            + '  "description": "计划简介（中文，2-3句话）",\n'
            + '  "total_weeks": ' + str(total_weeks) + ',\n'
            + '  "split_type": "' + split_type + '",\n'
            + '  "goal": "' + goal + '",\n'
            + '  "sessions_per_week": ' + str(sessions_per_week) + ',\n'
            + '  "periodization_model": "linear" | "block",\n'
            + '  "weeks": [\n'
            + '    {\n'
            + '      "week_number": 1,\n'
            + '      "week_type": "base" | "progression" | "peak" | "deload",\n'
            + '      "label": "第1周 — 适应期",\n'
            + '      "volume_modifier": 1.0,\n'
            + '      "intensity_note": "重量说明（中文）",\n'
            + '      "sessions": [\n'
            + '        {\n'
            + '          "session_number": 1,\n'
            + '          "workout_type": "upper_body"|"lower_body"|"full_body"|"push"|"pull",\n'
            + '          "label": "上肢日A",\n'
            + '          "estimated_duration_minutes": 60,\n'
            + '          "key_exercises": [\n'
            + '            {\n'
            + '              "name": "动作英文名（必须来自可用动作列表）",\n'
            + '              "sets": 3,\n'
            + '              "reps": "8-10",\n'
            + '              "rest_seconds": 120,\n'
            + '              "intensity_note": "自觉强度 7 / 约65% 一次最大重量",\n'
            + '              "target_muscle": "目标肌群英文名"\n'
            + '            }\n'
            + '          ],\n'
            + '          "notes": "训练重点（中文）"\n'
            + '        }\n'
            + '      ],\n'
            + '      "adaptation_notes": []\n'
            + '    }\n'
            + '  ]\n'
            + '}\n'
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ]

        max_attempts = 3
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            content = self._call_provider(messages)
            try:
                program_data = json.loads(content)
            except json.JSONDecodeError as exc:
                last_error = ValueError(
                    f"LLM did not return valid JSON (attempt {attempt}). "
                    f"Raw: {content[:200]!r}"
                )
                if attempt < max_attempts:
                    messages = messages + [
                        {"role": "assistant", "content": content},
                        {"role": "user", "content":
                            "Your response was not valid JSON. "
                            "Return ONLY a valid JSON object matching the schema above."},
                    ]
                continue

            try:
                _validate_program_schema(program_data)
            except ValueError as exc:
                last_error = exc
                if attempt < max_attempts:
                    messages = messages + [
                        {"role": "assistant", "content": content},
                        {"role": "user", "content":
                            f"Schema validation failed: {exc}. "
                            "Fix and return the complete corrected JSON."},
                    ]
                continue

            # Inject required fields not included in LLM output
            program_data.setdefault("status", "active")
            program_data.setdefault("current_week", 1)
            program_data.setdefault("adaptation_notes", [])

            return program_data

        raise ValueError(
            f"LLM failed to produce a valid program after {max_attempts} attempts. "
            f"Last error: {last_error}"
        )

    # =========================================================================
    # Phase 4 — Chat completion (sync + streaming)
    # =========================================================================

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """
        Run a single non-streaming chat completion against the configured provider.
        Returns the assistant's full text response.

        Differs from generate_workout_plan / generate_training_program in that
        it does NOT enforce a JSON schema or a specific output format —
        it's a free-form chat call used by CoachAgent.
        """
        if self.provider == "openai":
            completion = self._openai_client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return completion.choices[0].message.content or ""

        if self.provider == "minimax":
            payload: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            resp = httpx.post(self.base_url, json=payload, headers=headers, timeout=90.0)
            resp.raise_for_status()
            data = resp.json()
            try:
                return data["choices"][0]["message"]["content"]
            except Exception as exc:
                raise ValueError(f"Unexpected MiniMax response: {data!r}") from exc

        if self.provider == "minimax_anthropic":
            system_content, anthropic_messages = self._split_anthropic_messages(messages)
            response = self._anthropic_client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_content,
                messages=anthropic_messages,  # type: ignore[arg-type]
                timeout=120.0,
            )
            return "".join(b.text for b in response.content if b.type == "text")

        raise RuntimeError(f"Unsupported provider: {self.provider}")

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        """Run a single completion and parse the reply as a JSON object.

        This is the entry point used by the three plan-pipeline agents
        (``agents/llm_bridge.py``). It differs from ``chat_completion`` in two
        ways that matter for agent use:

        1. It requests JSON output mode from providers that support it.
        2. It tolerates the two failure modes seen with smaller models —
           ```json fences and a leading sentence before the object — instead
           of bubbling a ``JSONDecodeError`` up into the request handler.

        Temperature defaults low because every agent prompt here asks for a
        structured decision rather than creative text.

        Raises:
            ValueError: if no JSON object can be recovered from the reply.
        """
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        # DeepSeek 硬性要求：用 json_object 模式时 prompt 里必须出现 "json"
        # 这个词，否则直接 400。这里的兜底只在 prompt 漏写时补一句，正常
        # 三份 Agent prompt 都自带该要求，不会触发。
        if "json" not in f"{system_prompt}\n{user_prompt}".lower():
            messages[0]["content"] = (
                system_prompt.rstrip() + "\n\n只输出一个 JSON 对象，不要任何解释文字。"
            )
        content = self._call_provider(messages, response_format={"type": "json_object"})
        if not content or not content.strip():
            raise ValueError("LLM returned an empty response.")
        return _extract_json_object(content)

    def stream_chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> Generator[str, None, None]:
        """
        Stream a chat response chunk-by-chunk.

        Yields raw text deltas (strings). Caller is responsible for assembling
        the full response if it needs to (CoachAgent.stream_respond does this).

        Falls back to a single chunk if the provider doesn't support streaming.
        """
        if self.provider == "openai":
            stream = self._openai_client.chat.completions.create(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            for chunk in stream:
                try:
                    delta = chunk.choices[0].delta.content
                except (AttributeError, IndexError):
                    delta = None
                if delta:
                    yield delta
            return

        if self.provider == "minimax_anthropic":
            system_content, anthropic_messages = self._split_anthropic_messages(messages)
            with self._anthropic_client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_content,
                messages=anthropic_messages,  # type: ignore[arg-type]
            ) as stream:
                for text in stream.text_stream:
                    if text:
                        yield text
            return

        # Fallback: provider has no streaming → return the full response as one chunk
        full = self.chat_completion(messages, temperature=temperature, max_tokens=max_tokens)
        if full:
            yield full

    @staticmethod
    def _split_anthropic_messages(
        messages: List[Dict[str, str]],
    ) -> "tuple[str, List[Dict[str, Any]]]":
        """
        The Anthropic API takes the system prompt as a separate parameter and
        expects user/assistant content as a list of typed blocks.
        """
        system_content = ""
        anthropic_messages: List[Dict[str, Any]] = []
        for msg in messages:
            if msg["role"] == "system":
                # If multiple system messages exist, concatenate them
                system_content = (system_content + "\n\n" + msg["content"]).strip() \
                    if system_content else msg["content"]
            else:
                anthropic_messages.append({
                    "role": msg["role"],
                    "content": [{"type": "text", "text": msg["content"]}],
                })
        return system_content, anthropic_messages


def _validate_program_schema(data: Dict[str, Any]) -> None:
    """Validate the top-level structure of an LLM-generated program JSON."""
    if not isinstance(data, dict):
        raise ValueError(f"Program must be a JSON object, got {type(data).__name__}")

    required = ("total_weeks", "split_type", "goal", "sessions_per_week", "weeks")
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"Program missing required fields: {missing}")

    weeks = data["weeks"]
    if not isinstance(weeks, list) or len(weeks) == 0:
        raise ValueError("Program 'weeks' must be a non-empty list")

    for i, week in enumerate(weeks):
        if not isinstance(week, dict):
            raise ValueError(f"weeks[{i}] must be a JSON object")
        if "sessions" not in week or not isinstance(week["sessions"], list):
            raise ValueError(f"weeks[{i}] missing 'sessions' list")
        for j, sess in enumerate(week["sessions"]):
            if not isinstance(sess, dict):
                raise ValueError(f"weeks[{i}].sessions[{j}] must be a JSON object")
            if "key_exercises" not in sess or not sess["key_exercises"]:
                raise ValueError(
                    f"weeks[{i}].sessions[{j}] must have non-empty 'key_exercises'"
                )
