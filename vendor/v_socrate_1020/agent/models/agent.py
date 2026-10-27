"""
TAKA ReAct Agent (Phase 2)
==========================
基于 ToolRegistry（Search / Similar / Extract / Crop / Reflect）的选帧 Agent。

核心组件：
  AgentMemory  — 管理多轮对话历史，实现视觉上下文剪枝（策略 B）
  TAKAAgent    — ReAct 主循环；观察图为逐帧缩小图（保持宽高比，各带 Frame id 标签）

依赖：
  tools/agent_tools.py — ToolRegistry, CropStore, VideoIndex
  models/llm.py        — LLMofAgent
  selector.py          — Selector planning prompt
  reflector.py         — Reflector answering prompt
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
from datetime import datetime, timezone

import numpy as np
from typing import Any, Dict, List, Optional, Tuple

from ..tools.tool_schema import env_int   # all configuration comes from configs/common_env.sh


IMAGE_MAX_SIDE = env_int("TAKA_IMAGE_MAX_SIDE")        # Reflector frames (default view)
ENHANCE_MAX_SIDE = env_int("TAKA_ENHANCE_MAX_SIDE")    # Reflector Enhance (whole frames)
OBS_MAX_SIDE = env_int("TAKA_OBS_MAX_SIDE")            # Selector observation frames
CROP_MAX_SIDE = env_int("TAKA_CROP_MAX_SIDE")          # crops (Selector and Reflector)
REFLECT_MAX_FRAMES = env_int("TAKA_REFLECT_MAX_FRAMES")  # frames per Reflect submission
REFLECTOR_MAX_TOOL_CALLS = env_int("TAKA_REFLECTOR_MAX_TOOL_CALLS")  # Crop/Enhance calls per Reflect
LEAD_MAX_SIDE = env_int("TAKA_LEAD_MAX_SIDE")           # Search / Similar previews
MAX_REQUEST_IMAGES = env_int("TAKA_OBS_MAX_IMAGES")      # = vLLM --limit-mm-per-prompt image
CONTEXT_LIMIT = env_int("TAKA_CONTEXT_LIMIT")        # served max-model-len
CONTEXT_RESERVE = env_int("TAKA_CONTEXT_RESERVE")     # room kept for the next turn

# Hand-off (as in MMDR-PLANNER): on the last step, or when the next turn might not fit the
# context, a search call is not executed; this tool message answers it and the Selector
# gets one more turn that may only call Reflect. The Reflector can still REJECT.
STEP_BUDGET_TEXT = (
    "Step budget exhausted: this call was not executed. Do not call any more search tools. "
    "Call Reflect now with the frames from earlier observations that best support an answer."
)
CONTEXT_BUDGET_TEXT = (
    "Context budget nearly exhausted: this call was not executed. Do not call any more search "
    "tools. Call Reflect now with the frames from earlier observations that best support an answer."
)


def _downscale_for_vlm(img, max_side: Optional[int] = None):
    """Cap an image's long side (aspect ratio kept) before encoding, to bound prompt
    tokens. Qwen3-VL spends ~1 token per 32x32 pixels: a 1280x720 frame is ~900
    tokens, 640x360 ~220, 448x252 ~110. 0 = no scaling."""
    if max_side is None:
        max_side = IMAGE_MAX_SIDE
    if max_side and max_side > 0:
        w, h = img.size
        scale = min(max_side / max(w, h), 1.0)
        if scale < 1.0:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    return img

from PIL import Image


def _image_part(img: Image.Image, max_side: int, quality: int) -> Dict[str, Any]:
    """One OpenAI image_url content part: downscaled (aspect kept) JPEG."""
    buf = io.BytesIO()
    _downscale_for_vlm(img.convert("RGB"), max_side).save(buf, format="JPEG", quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode()
    return {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}


from .llm import LLMofAgent
from ...prompt.reflector import (
    format_reflector_prompt,
    get_reflector_crop_section,
    get_reflector_duration_section,
)
from ...prompt.selector import (
    REACT_SYSTEM_PROMPT, REJECT_RECOVERY_SECTION,
    get_frame_budget_section,
    get_coverage_precision_section,
    get_exploration_strategy_section, get_start_broad_rule,
    get_label_strategy_section,
    scrub_disabled_tool_guidance, get_disabled_tools_notice,
)
from ..tools.agent_tools import CropStore, InputDataError, ToolFeedback, ToolRegistry, ToolResult, VideoIndex
from ..tools.tool_schema import ENHANCE_MAX_FRAMES, get_reflector_openai_tools


# ────────────────────────────────────────────────────────────────
#  Failure handling
# ────────────────────────────────────────────────────────────────
# Per-question failures never fall back silently: the runner records
# status="failed" + failed_type, and --resume re-runs those questions.
LLM_MAX_ATTEMPTS = env_int("TAKA_LLM_MAX_ATTEMPTS")
AGENT_MAX_TOKENS = env_int("AGENT_MAX_TOKENS")

# failed_type values (the runner adds video_not_found / preprocess_error /
# no_frames_selected / exception).
FAILED_AGENT_LLM = "agent_llm_failed"            # agent call failed (Timeout/Error) on every attempt
FAILED_AGENT_TOOL_CALL = "agent_invalid_tool_call"  # no single valid native call after retries
FAILED_AGENT_TRUNCATED = "agent_truncated"        # every agent attempt hit AGENT_MAX_TOKENS
FAILED_REFLECTOR = "reflector_failed"            # reflector Timeout/Error/unparsable on every attempt
FAILED_REFLECTOR_TRUNCATED = "reflector_truncated"  # every reflector attempt hit REFLECT_MAX_TOKENS
FAILED_REFLECT_EMPTY = "reflect_no_valid_frames"  # Reflect received no valid frame id
FAILED_STEP_BUDGET = "step_budget_exhausted"      # no confirmed Reflect after the hand-off turn
FAILED_REFLECT_REJECT_LIMIT = "reflect_reject_limit"  # max REJECT count reached without an answer
FAILED_REFLECT_TOO_MANY = "reflect_too_many_frames"   # Reflect submitted more than TAKA_REFLECT_MAX_FRAMES
FAILED_REPEATED_CALL = "repeated_tool_call"           # the same tool call (same arguments) made LOOP_FAIL_AT times
FAILED_TOOL_ERRORS = "repeated_tool_errors"           # LOOP_FAIL_AT tool errors in a row

# Loop control (as the "Do not loop" rule in the prompt): an identical call or a run of
# tool errors gets a warning appended to its tool result from the LOOP_WARN_AT-th time
# and fails the question at the LOOP_FAIL_AT-th.
LOOP_WARN_AT = env_int("TAKA_LOOP_WARN_AT")
LOOP_FAIL_AT = env_int("TAKA_LOOP_FAIL_AT")


class QuestionFailed(Exception):
    """This question cannot produce a valid frame set -> runner marks status=failed."""

    def __init__(
        self,
        failed_type: str,
        conversation: Optional[List[Dict[str, Any]]] = None,
        reflection_history: Optional[List[Dict[str, Any]]] = None,
        submitted_frame_ids: Optional[List[int]] = None,
    ):
        super().__init__(failed_type)
        self.failed_type = failed_type
        self.conversation = conversation or []
        self.reflection_history = reflection_history or []
        self.submitted_frame_ids = submitted_frame_ids or []


class FatalFrameDecodeError(RuntimeError):
    """A frame that the pipeline relies on cannot be decoded -> the runner aborts the
    whole program (instead of silently confirming / dropping frames)."""


def _is_timeout(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    return "timeout" in name or "timed out" in str(exc).lower()


def _log(qid, msg: str) -> None:
    print(f"[TAKA][qid={qid}] {msg}", flush=True)


def _duration_bucket(duration_sec: Optional[float]) -> Optional[str]:
    if duration_sec is None:
        return None
    if duration_sec <= 60:
        return "short"
    if duration_sec <= 600:
        return "medium"
    return "long"


def _chat_once_logged(
    llm,
    messages,
    who: str,
    qid,
    attempt: int,
    *,
    frame_count: int = 0,
    duration_sec: Optional[float] = None,
    usage_out: Optional[Dict[str, Any]] = None,
    calls_out: Optional[List[Dict[str, Any]]] = None,
    **chat_kwargs,
) -> Optional[Any]:
    """One chat call with latency/token/frame metrics (usage copied into usage_out).

    calls_out (trajectory, as MMDR-PLANNER's `calls`): one record per API call is appended;
    the caller then sets its disposition (accepted -> message_index, or discarded ->
    invalid_reason) with _settle_call()."""
    get_usage = getattr(llm, "pop_last_usage", None)
    if callable(get_usage):
        get_usage()  # clear any stale usage from a previous call on this thread
    started = time.perf_counter()
    resp = None
    error: Optional[BaseException] = None
    try:
        resp = llm.chat(messages, **chat_kwargs)
    except Exception as exc:  # noqa: BLE001
        error = exc
        kind = "Timeout" if _is_timeout(exc) else "Error"
        _log(qid, f"[{who}] {kind} (attempt {attempt}/{LLM_MAX_ATTEMPTS}): "
                  f"{type(exc).__name__}: {str(exc)[:200]}")
    elapsed = time.perf_counter() - started
    usage = get_usage() if callable(get_usage) else {}
    if usage_out is not None:
        usage_out.clear()
        usage_out.update(usage or {})
    if calls_out is not None:
        tools = chat_kwargs.get("tools") or []
        cfg = getattr(llm, "config", None) or {}
        calls_out.append({
            "call": len(calls_out),
            "speaker": who,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "request": {
                "temperature": chat_kwargs.get("temperature", cfg.get("temperature")),
                "top_p": (chat_kwargs.get("top_p") if chat_kwargs.get("override_top_p")
                          else cfg.get("top_p")),
                "max_tokens": chat_kwargs.get("max_tokens", cfg.get("max_tokens")),
                "top_k": int(os.environ["LLM_TOP_K"]),
                "presence_penalty": float(os.environ["LLM_PRESENCE_PENALTY"]),
                "tool_choice": chat_kwargs.get("tool_choice"),
                "tools": [t.get("function", {}).get("name") for t in tools],
                "n_messages": len(messages),
                "n_images": int(frame_count),
            },
            "disposition": "error" if error is not None else "pending",
            "message_index": None,
            "invalid_reason": None,
            "error": f"{type(error).__name__}: {str(error)[:300]}" if error is not None else None,
            "finish_reason": (usage or {}).get("finish_reason"),
            "usage": {k: (usage or {}).get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
            "elapsed_sec": round(elapsed, 4),
        })
        if (usage or {}).get("finish_reason") == "length":
            # A truncated reply never enters the trajectory; keep its text here so we can
            # see what the model was writing when it ran into max_tokens.
            if isinstance(resp, dict):
                text = resp.get("reasoning") or ""
                if resp.get("content") and resp["content"] != text:
                    text += "\n[content]\n" + resp["content"]
            else:
                text = str(resp or "")
            calls_out[-1]["truncated_output"] = {
                "chars": len(text), "head": text[:3000], "tail": text[-6000:]}
    metric = {
        "kind": "llm",
        "qid": qid,
        "name": who,
        "attempt": attempt,
        "elapsed_sec": round(elapsed, 4),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "frame_count": int(frame_count),
        "duration_sec": round(float(duration_sec), 3) if duration_sec is not None else None,
        "duration_bucket": _duration_bucket(duration_sec),
        "success": error is None,
        "error_type": type(error).__name__ if error is not None else None,
    }
    print(f"[TAKA_METRIC] {json.dumps(metric, ensure_ascii=False, sort_keys=True)}", flush=True)
    if error is not None:
        return None
    if isinstance(resp, dict):
        return resp
    return re.sub(r"<think>.*?</think>", "", resp or "", flags=re.DOTALL).strip()


def _settle_call(calls: List[Dict[str, Any]], *, message_index: Optional[int] = None,
                 invalid_reason: Optional[str] = None) -> Optional[int]:
    """Mark the latest call record accepted (its reply is messages[message_index]) or
    discarded (invalid_reason; the reply was not written to the trajectory)."""
    if not calls:
        return None
    rec = calls[-1]
    if rec["disposition"] == "pending":
        rec["disposition"] = "discarded" if invalid_reason else "accepted"
        rec["message_index"] = message_index
        rec["invalid_reason"] = invalid_reason
    return rec["call"]


_TOOL_CALL_RETRY_REMINDER = (
    "Your previous reply did not contain exactly one valid tool call. Call exactly one "
    "function from the provided tools. Put your compact evidence reasoning before the call."
)
# Sent with the resample of a reply that was cut at max_tokens (not a format error).
_TRUNCATED_REMINDER = (
    "Your previous reply was cut off at the output token limit before it finished. Think "
    "briefly: state only the decisive observations and the next step, then {action}."
)


# ────────────────────────────────────────────────────────────────
#  策略 B：视觉上下文管理器（AgentMemory）
# ────────────────────────────────────────────────────────────────

class AgentMemory:
    """
    策略 B：Visual Context Pruning（视觉上下文阅后即焚）。

    每当 Agent 产生新的视觉 Observation，将上一轮 tool 消息中的图像替换为
    纯文本占位符，只保留 Thought 文字结论，防止上下文 Token 爆炸。
    """

    def __init__(self) -> None:
        self._messages: List[Dict[str, Any]] = []
        # One entry per message (as MMDR-PLANNER's message_meta): source "model" (a sampled
        # reply; `call` indexes the calls record) or "env" (harness-written; `reason` says why).
        self.meta: List[Dict[str, Any]] = []
        self._last_visual_msg_idx: int = -1   # 上一条含图像的 tool 消息下标
        self._last_visual_frame_count: int = 0

    # ── 添加消息 ────────────────────────────────────────────────

    def _append(self, message: Dict[str, Any], source: str = "env", call: Optional[int] = None,
                reason: Optional[str] = None) -> int:
        self._messages.append(message)
        self.meta.append({"source": source, "call": call, "reason": reason})
        return len(self._messages) - 1

    def add_system(self, text: str) -> None:
        self._append({"role": "system", "content": text})

    def add_user_text(self, text: str) -> None:
        self._append({"role": "user", "content": text})

    def add_native_assistant_tool_call(self, message: Dict[str, Any], call: Optional[int] = None) -> int:
        """Persist a model-native tool call without regenerating its envelope."""
        return self._append({
            "content": message.get("content") or "",
            "role": "assistant",
            "tool_calls": message["tool_calls"],
            "reasoning": message.get("reasoning") or "",
        }, source="model", call=call)

    def add_tool_text(self, *, tool_call_id: str, name: str, text: str, reason: Optional[str] = None) -> None:
        self._append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": text,
        }, reason=reason)

    def add_tool_visual(
        self,
        *,
        tool_call_id: str,
        name: str,
        images: List[Tuple[str, Image.Image, int]],
        obs_text: str,
    ) -> None:
        """
        添加带图像的 tool 返回（images: [(label, image, max_side)]，每张图前一行标签），
        并将上一条视觉 tool 返回中的图像剪枝（只保留其 observation 文本）。
        """
        # ① 剪枝上一条视觉消息
        if self._last_visual_msg_idx >= 0:
            prev = self._messages[self._last_visual_msg_idx]
            if isinstance(prev.get("content"), list):
                pruned = prev["content"][0]["text"]
                pruned += "\n[Visual evidence analyzed in previous step]"
                self._messages[self._last_visual_msg_idx]["content"] = pruned

        # ② 逐帧编码（缩小、保持宽高比）
        content: List[Dict[str, Any]] = [{"type": "text", "text": obs_text}]
        for label, img, max_side in images:
            content.append({"type": "text", "text": label})
            content.append(_image_part(img, max_side, quality=85))
        self._last_visual_msg_idx = self._append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": content,
        })
        self._last_visual_frame_count = len(images)

    @property
    def prompt_frame_count(self) -> int:
        """Number of images in the one unpruned visual observation."""
        return self._last_visual_frame_count if self._last_visual_msg_idx >= 0 else 0

    def add_final_answer(
        self,
        *,
        evidence_frame_ids: List[int],
        answer: Dict[str, str],
        reasoning: str,
    ) -> str:
        final_output = (
            f"\n\n<evidence_frame>{json.dumps(evidence_frame_ids, ensure_ascii=False)}</evidence_frame>"
            f"\n<answer>{json.dumps(answer, ensure_ascii=False)}</answer>"
        )
        self._append({
            "content": final_output,
            "role": "assistant",
            "reasoning": reasoning,
        }, reason="final_output")
        return final_output

    # ── 读取 ─────────────────────────────────────────────────────

    def get_messages(self) -> List[Dict[str, Any]]:
        return self._messages


# ────────────────────────────────────────────────────────────────
#  ReAct Agent 主体
# ────────────────────────────────────────────────────────────────

class TAKAAgent:
    """
    Phase 2 选帧 Agent（ReAct 框架）。

    接受 VideoIndex + ToolRegistry + LLMofAgent，
    通过 Think → Act → Observe 循环自主调用工具，
    最终提交黄金帧序列。

    Usage::

        from models.clip import CLIPTool
        from .llm import LLMofAgent
        from ..tools.agent_tools import VideoPreprocessor, ToolRegistry

        clip = CLIPTool()
        preprocessor = VideoPreprocessor(clip)
        video_index = preprocessor.process("video.mp4")

        registry = ToolRegistry(video_index, clip)
        llm = LLMofAgent(config={...})
        agent = TAKAAgent(registry, llm, video_index)

        frame_ids, messages = agent.run(
            question="What does the man do after picking up the phone?",
        )
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm: LLMofAgent,
        video_index: VideoIndex,
        verbose: bool = True,
    ) -> None:
        self.registry = tool_registry
        self.llm = llm
        self.vi = video_index
        self.verbose = verbose
        # Selector and Reflector crops share one store, so Selector crop ids can be submitted.
        self.crops = getattr(tool_registry, "crop_store", None) or CropStore(video_index)

    def run(
        self,
        question: str,
        candidates: list = None,
        task_prior: Dict[str, Any] = None,
        max_steps: int = 8,
        max_reflect_rejects: int = 2,
        out_dir: Optional[str] = None,
        step_callback: Optional[Any] = None,
        use_long_video_section: Optional[bool] = None,
        react_video_section: Optional[str] = None,
        react_task_section: Optional[str] = None,
        qid: Optional[str] = None,
        duration_guidance: bool = True,
        reflect_temperature: float = 0.0,
        reflect_top_p: Optional[float] = None,
        reflect_max_tokens: int = 1024,
    ) -> Tuple[List[int], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
        """
        运行 ReAct 循环（含 Phase 3 Visual Self-Reflection）。

        Args:
            question:    VQA 问题文本
            candidates:  候选答案列表（如 ["option A", "option B", ...]）
            task_prior:  Meta-Planner 输出（可选，当前未使用）
            max_steps:   最大工具调用轮数
            out_dir:     若非 None，将提交帧保存到该目录
        Returns:
            (submitted_frame_ids, conversation_messages, final_reflection, reflection_history)
        """
        memory = AgentMemory()
        self._qid = qid
        selector_calls: List[Dict[str, Any]] = []
        # Trajectory (MMDR-PLANNER style); the runner saves export_trace() for every question.
        self._memory = memory
        self.trace = {"selector": {"message_meta": memory.meta, "calls": selector_calls},
                      "reflector": []}
        set_trace_context = getattr(self.registry, "set_trace_context", None)
        if callable(set_trace_context):
            set_trace_context(qid=qid)

        # ── Duration routing 组件 ──
        # duration_guidance=False (--enable-duration-routing 关闭, 即消融): 去掉所有按视频长度
        # 注入的引导 —— Selector 端本视频所属档（short/medium/long）的那一段（含分档帧数范围），
        # 以及 Reflector 的时长段。
        # 预处理(1fps 采样 + 场景分割)与工具调用本身不受影响; 出口整形(fill/cap)是独立组件。
        if not duration_guidance:
            use_long_video_section, react_video_section = False, None
        if use_long_video_section is None:
            use_long_video_section = (self.vi.total_duration > 30)

        # ── 构建 System Prompt ──────────────────────────────────
        # 格式化 candidates 文本
        if candidates:
            candidates_text = "\n".join(f"  {chr(65+i)}. {c}" for i, c in enumerate(candidates))
        else:
            candidates_text = "  (No candidates provided)"

        system_text = REACT_SYSTEM_PROMPT.format(
            question=question,
            candidates=candidates_text,
            tools_schema=ToolRegistry.get_tools_description(),
            frame_budget_section=get_frame_budget_section(),
            label_strategy_section=get_label_strategy_section(),
            coverage_precision_section=get_coverage_precision_section(),
            exploration_strategy_section=get_exploration_strategy_section(),
            start_broad_rule=get_start_broad_rule(),
            max_steps=max_steps,
            video_duration=self.vi.total_duration,
            total_frames=len(self.vi.frames),
            duration_section=(react_video_section or ""),
            task_specific_section=(react_task_section or ""),
            # Reflector component: the "after REJECT" guidance only exists when the
            # Reflector can reject (max_reflect_rejects > 0).
            reject_recovery_section=(REJECT_RECOVERY_SECTION if max_reflect_rejects > 0 else ""),
        )
        # Tool ablation: drop guidance that names a disabled tool (no-op when
        # TAKA_DISABLE_TOOLS is unset, so the full model's prompt is unchanged).
        _notice = get_disabled_tools_notice()
        if _notice:
            system_text = scrub_disabled_tool_guidance(system_text) + "\n" + _notice
        memory.add_system(system_text)
        memory.add_user_text(f"Question: {question}")

        selected_frame_ids: List[int] = []
        final_reflection: Dict[str, Any] = {}
        reflection_history: List[Dict[str, Any]] = []
        last_reflected_ids: List[int] = []
        reflect_rejects = 0
        reflect_count = 0
        judged_submissions: Dict[tuple, Dict[str, Any]] = {}   # (frame ids, crop ids) -> REJECT record
        native_tools = ToolRegistry.get_openai_tools()

        if self.verbose:
            print("=" * 60)
            print(f"[TAKAAgent] question: {question[:80]}")
            print(f"[TAKAAgent] candidates: {len(candidates) if candidates else 0} options")
            print("=" * 60)

        # Budget: only the Selector's search calls (every tool except Reflect) use steps;
        # Reflect submissions are bounded by max_reflect_rejects instead.
        handoff_text: Optional[str] = None   # set -> the next turn may only call Reflect
        handoff_done = False
        steps_used = 0
        consecutive_errors = 0
        call_counts: Dict[str, int] = {}
        agent_usage: Dict[str, Any] = {}
        reflect_choice = {"type": "function", "function": {"name": "Reflect"}}
        turn = 0

        def tool_error(call_id: str, name: str, text: str) -> None:
            """Return a tool error; 3 in a row adds a warning, LOOP_FAIL_AT in a row fails."""
            nonlocal consecutive_errors
            consecutive_errors += 1
            if consecutive_errors >= LOOP_FAIL_AT:
                memory.add_tool_text(tool_call_id=call_id, name=name, text=text, reason="tool_error")
                raise QuestionFailed(FAILED_TOOL_ERRORS, memory.get_messages(),
                                     reflection_history, last_reflected_ids)
            if consecutive_errors >= LOOP_WARN_AT:
                text += (f"\n\nWarning: {consecutive_errors} tool errors in a row. Read the error "
                         f"message and change the call; {LOOP_FAIL_AT} errors in a row fail the question.")
            memory.add_tool_text(tool_call_id=call_id, name=name, reason="tool_error",
                                 text=text + self._budget_note(steps_used, max_steps))

        while not handoff_done:
            turn += 1
            if handoff_text is not None:
                handoff_done = True
            if step_callback is not None:
                try:
                    step_callback(steps_used + 1, max_steps, "RUNNING")
                except Exception:
                    pass
            if self.verbose:
                print(f"\n--- Turn {turn} (search steps used {steps_used}/{max_steps}) ---")

            # ── LLM 推理 ──────────────────────────────────────
            # A failed call (Timeout/Error) or a reply without a parsable tool call is
            # retried up to LLM_MAX_ATTEMPTS times; retries are NOT written to the
            # trajectory (a format reminder is appended to the request only). All attempts
            # failing -> QuestionFailed.
            resp, action_json, calls = None, None, []
            remind = None   # reminder for the resample after an invalid or truncated reply
            truncations = 0
            for attempt in range(1, LLM_MAX_ATTEMPTS + 1):
                msgs = memory.get_messages()
                if remind:
                    msgs = list(msgs) + [{"role": "user", "content": remind}]
                resp = _chat_once_logged(
                    self.llm,
                    msgs,
                    "agent",
                    qid,
                    attempt,
                    frame_count=memory.prompt_frame_count,
                    duration_sec=self.vi.total_duration,
                    usage_out=agent_usage,
                    calls_out=selector_calls,
                    tools=native_tools,
                    tool_choice=reflect_choice if handoff_done else "auto",
                )
                if resp is None:
                    continue
                if agent_usage.get("finish_reason") == "length":
                    # A reply cut at max_tokens is discarded and resampled (as MMDR), with a
                    # one-line request to think more briefly.
                    truncations += 1
                    remind = _TRUNCATED_REMINDER.format(action="call exactly one tool")
                    _settle_call(selector_calls, invalid_reason="truncated")
                    _log(qid, f"[agent] Truncated at max_tokens (attempt {attempt}/{LLM_MAX_ATTEMPTS})")
                    continue
                calls = self._parse_native_tool_calls(resp) if isinstance(resp, dict) else []
                if calls:
                    action_json = calls[0]
                    break
                remind = _TOOL_CALL_RETRY_REMINDER
                _settle_call(selector_calls, invalid_reason="no_valid_tool_call")
                _log(
                    qid,
                    f"[agent] InvalidToolCall (attempt {attempt}/{LLM_MAX_ATTEMPTS}): "
                    f"{str(resp)[:160]!r}",
                )
                if step_callback is not None:
                    try:
                        step_callback(steps_used + 1, max_steps, "PARSE_ERROR")
                    except Exception:
                        pass
            if not action_json:
                if resp is None:
                    failed = FAILED_AGENT_LLM
                elif truncations == LLM_MAX_ATTEMPTS:
                    failed = FAILED_AGENT_TRUNCATED
                else:
                    failed = FAILED_AGENT_TOOL_CALL
                raise QuestionFailed(failed, memory.get_messages())
            msg_idx = memory.add_native_assistant_tool_call(resp, call=selector_calls[-1]["call"])
            _settle_call(selector_calls, message_index=msg_idx)
            if self.verbose:
                print(f"  LLM: {str(resp)[:300]}")

            # ── Several tool calls in one turn: none is executed, each gets a tool error ──
            if len(calls) > 1:
                names = [c["action"] for c in calls]
                text = (f"Tool error: {len(calls)} tool calls in one turn ({', '.join(names)}); none "
                        f"was executed. Call exactly one tool per turn; one call can batch several "
                        f"queries, intervals, or crop regions.")
                for call in calls[:-1]:
                    memory.add_tool_text(tool_call_id=call["call_id"], name=call["action"], text=text,
                                         reason="tool_error")
                if any(n != "Reflect" for n in names) and not handoff_done:
                    steps_used += 1
                tool_error(calls[-1]["call_id"], calls[-1]["action"], text)
                if handoff_done:
                    raise QuestionFailed(FAILED_STEP_BUDGET, memory.get_messages(),
                                         reflection_history, last_reflected_ids)
                continue

            thought = action_json.get("thought", "")
            tool_name = action_json.get("action", "").strip()
            params: Dict[str, Any] = action_json.get("params") or {}
            tool_call_id = action_json["call_id"]

            if step_callback is not None:
                try:
                    step_callback(steps_used + 1, max_steps, tool_name or "EMPTY_ACTION")
                except Exception:
                    pass

            if self.verbose:
                print(f"  Thought: {thought}")
                print(f"  Action : {tool_name}({params})")

            # ── Repeated identical call (any tool, Reflect included): warn from the 3rd, fail at the 5th ──
            key_params = params
            if tool_name == "Reflect":   # the same frame set in another order is the same submission
                key_params = {k: (sorted(set(map(str, v))) if isinstance(v, list) else v)
                              for k, v in params.items()}
            call_key = f"{tool_name}:{json.dumps(key_params, sort_keys=True)}"
            call_counts[call_key] = call_counts.get(call_key, 0) + 1
            repeats = call_counts[call_key]
            loop_warning = ""
            if repeats >= LOOP_FAIL_AT:
                memory.add_tool_text(
                    tool_call_id=tool_call_id, name=tool_name, reason="repeated_call",
                    text=f"Not executed: this exact call was made {repeats} times.")
                raise QuestionFailed(FAILED_REPEATED_CALL, memory.get_messages(),
                                     reflection_history, last_reflected_ids)
            if repeats >= LOOP_WARN_AT:
                hint = ("Submit a different frame set that addresses the missing evidence, or search for it."
                        if tool_name == "Reflect" else
                        "If your searches stopped adding evidence, call Reflect now with your best frames: "
                        "Reflect uses no search steps and a REJECT tells you what is missing. Otherwise "
                        "change the query, interval, or tool.")
                loop_warning = (
                    f"\n\nWarning: LOOP. You have made this exact {tool_name} call {repeats} times "
                    f"and it returns the same result. Do not repeat it. {hint} "
                    f"The {LOOP_FAIL_AT}th identical call fails the question.")
                _log(qid, f"[agent] loop warning: {tool_name} repeated {repeats}x")

            if tool_name != "Reflect":
                # ── Hand-off: no more search after the step / context budget ──
                if handoff_done:      # the hand-off turn did not call Reflect
                    memory.add_tool_text(tool_call_id=tool_call_id, name=tool_name, reason="handoff_violation",
                                         text="Not executed: only Reflect was allowed in this turn.")
                    raise QuestionFailed(FAILED_STEP_BUDGET, memory.get_messages(),
                                         reflection_history, last_reflected_ids)
                used = (agent_usage.get("prompt_tokens") or 0) + (agent_usage.get("completion_tokens") or 0)
                context_full = used > 0 and used + AGENT_MAX_TOKENS + CONTEXT_RESERVE > CONTEXT_LIMIT
                if steps_used >= max_steps or context_full:
                    handoff_text = CONTEXT_BUDGET_TEXT if context_full else STEP_BUDGET_TEXT
                    memory.add_tool_text(tool_call_id=tool_call_id, name=tool_name, text=handoff_text,
                                         reason="context_budget" if context_full else "step_budget")
                    _log(qid, f"[agent] hand-off: {'context' if context_full else 'step'} budget exhausted")
                    continue
                steps_used += 1

            # ── 执行工具 ──────────────────────────────────────
            result: ToolResult = self.registry.execute(tool_name, params)

            if not result.success:
                tool_error(tool_call_id, tool_name,
                           scrub_disabled_tool_guidance(f"Tool error: {result.text_summary}") + loop_warning)
                continue

            # ── Reflect：same-endpoint visual answering ────────
            if result.terminal:
                # Reflect hands frames to the answerer. Before it starts, check the
                # ids: every id must be an integer frame id returned by an earlier tool call.
                # Invalid ids -> tool error to the agent, nothing is dropped silently.
                # No minimum frame count. An empty list -> question failed.
                submitted_ids, invalid = self._check_submission(
                    result.data.get("reflected_frame_ids")
                )
                if invalid is not None:
                    tool_error(tool_call_id, tool_name, (
                        f"Tool error: Reflect: invalid frame_ids {invalid}: use only the integer frame ids "
                        f"listed in previous tool observations. Nothing was sent to the Reflector."))
                    if handoff_done:
                        break
                    continue
                if len(submitted_ids) > REFLECT_MAX_FRAMES:
                    # Over the frame cap: the question fails (not returned to the Selector).
                    memory.add_tool_text(
                        tool_call_id=tool_call_id,
                        name=tool_name,
                        text=(f"Reflect failed: {len(submitted_ids)} frames submitted; at most "
                              f"{REFLECT_MAX_FRAMES} are accepted."),
                    )
                    raise QuestionFailed(FAILED_REFLECT_TOO_MANY, memory.get_messages(),
                                         reflection_history, submitted_ids)
                crop_ids, crop_error = self._check_crop_ids(
                    result.data.get("crop_ids"), submitted_ids
                )
                if crop_error:
                    tool_error(tool_call_id, tool_name,
                               f"Tool error: Reflect: {crop_error} Nothing was sent to the Reflector.")
                    if handoff_done:
                        break
                    continue
                if not submitted_ids:
                    memory.add_tool_text(
                        tool_call_id=tool_call_id,
                        name=tool_name,
                        text="Reflect failed: no valid frame IDs were provided.",
                    )
                    raise QuestionFailed(FAILED_REFLECT_EMPTY, memory.get_messages())
                # A frame set (any order) + crops already judged is not sent again: the
                # Reflector would see the same pixels. The earlier verdict is returned instead;
                # it uses no step and no REJECT, and LOOP_FAIL_AT identical calls fail (above).
                submission_key = (tuple(submitted_ids), tuple(sorted(crop_ids)))
                if submission_key in judged_submissions:
                    prev = judged_submissions[submission_key]
                    memory.add_tool_text(
                        tool_call_id=tool_call_id, name=tool_name, reason="repeated_call",
                        text=(f"Not executed: the Reflector already judged exactly this frame set "
                              f"(Reflect attempt {prev['attempt']}) and would see the same pixels. Its "
                              f"verdict was REJECT: {prev['reason']} Missing: "
                              f"{'; '.join(prev['missing_evidence'])}. Find new frames that show the "
                              f"missing fact before calling Reflect again." + loop_warning))
                    _log(qid, f"[agent] Reflect resubmitted an already judged frame set; not executed")
                    continue
                consecutive_errors = 0
                last_reflected_ids = list(submitted_ids)

                # ── Same model endpoint, fresh Reflector prompt + downscaled frames ──
                reflect_count += 1
                try:
                    reflect_decision, reflector_tools = self._visual_self_reflect(
                        submitted_ids, question, self.llm,
                        crop_ids=crop_ids,
                        selector_tool_call_id=tool_call_id,
                        candidates=candidates,
                        allow_best_guess=reflect_rejects > 0,
                        use_long_video_section=use_long_video_section,
                        reflect_temperature=reflect_temperature,
                        reflect_top_p=reflect_top_p,
                        reflect_max_tokens=reflect_max_tokens,
                    )
                except QuestionFailed as exc:
                    memory.add_tool_text(
                        tool_call_id=tool_call_id,
                        name=tool_name,
                        text=f"Reflect failed while running the answerer: {exc.failed_type}.",
                    )
                    exc.conversation = memory.get_messages()
                    exc.reflection_history = list(reflection_history)
                    exc.submitted_frame_ids = list(submitted_ids)
                    raise

                reflection_record = {
                    "attempt": reflect_count,
                    "submitted_frame_ids": list(submitted_ids),
                    "submitted_crop_ids": list(crop_ids),
                    "selector_tool_call_id": tool_call_id,
                    "reflector_tool_calls": reflector_tools,
                    **reflect_decision,
                }
                reflection_history.append(reflection_record)
                reflect_tool_payload = {
                    **reflect_decision,
                    "reflected_frame_ids": list(submitted_ids),
                }
                reflect_tool_content = json.dumps(reflect_tool_payload, ensure_ascii=False)

                if reflect_decision["status"] in (
                    "CONFIRM",
                    "BEST_GUESS",
                    "UNASSESSABLE",
                ):
                    selected_frame_ids = submitted_ids
                    memory.add_tool_text(
                        tool_call_id=tool_call_id,
                        name=tool_name,
                        text=reflect_tool_content,
                        reason="reflect_confirm",
                    )
                    final_reflection = self._parse_reflect_tool_content(
                        reflect_tool_content
                    )
                    final_output = memory.add_final_answer(
                        evidence_frame_ids=final_reflection["evidence_frame_ids"],
                        answer=final_reflection["answer"],
                        reasoning=final_reflection["reason"],
                    )
                    final_reflection = dict(final_reflection)
                    final_reflection["final_output"] = final_output
                    if self.verbose:
                        print(f"  → Reflect CONFIRM. answer={final_reflection['answer']['choice']} "
                              f"evidence={final_reflection['evidence_frame_ids']}")
                    break
                else:
                    # REJECT: return only the gap to the Selector; it chooses its own next tool.
                    reflect_rejects += 1
                    judged_submissions[submission_key] = reflection_record
                    memory.add_tool_text(
                        tool_call_id=tool_call_id,
                        name=tool_name,
                        text=reflect_tool_content + loop_warning + self._budget_note(steps_used, max_steps),
                        reason="reflect_reject",
                    )
                    if self.verbose:
                        print(f"  → Reflect REJECT ({reflect_rejects}/{max_reflect_rejects}): "
                              f"{reflect_decision['reason']}")
                    if reflect_rejects >= max_reflect_rejects:
                        raise QuestionFailed(
                            FAILED_REFLECT_REJECT_LIMIT,
                            memory.get_messages(),
                            reflection_history,
                            submitted_ids,
                        )
                    continue

            consecutive_errors = 0

            # ── 构建 Observation：逐帧缩小图，每张带 Frame id 标签 ─────────
            obs_text = (f"Observation (search step {steps_used}/{max_steps}):\n{result.text_summary}"
                        + loop_warning + self._budget_note(steps_used, max_steps))
            if result.images or result.crops:
                side = result.max_side or (LEAD_MAX_SIDE if result.lead else OBS_MAX_SIDE)
                images = [(f"Frame {fid} @ {self.vi.frame_time(fid):.1f}s:", img, side)
                          for fid, img in result.images]
                images += [(f"Crop {cid}:", img, CROP_MAX_SIDE) for cid, img in result.crops]
                memory.add_tool_visual(
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    images=images,
                    obs_text=obs_text,
                )
            else:
                memory.add_tool_text(
                    tool_call_id=tool_call_id,
                    name=tool_name,
                    text=obs_text,
                )

        # 循环耗尽但未得到确认的 Reflect: 该题失败(不再用累积帧兜底)
        if not selected_frame_ids:
            raise QuestionFailed(
                FAILED_STEP_BUDGET,
                memory.get_messages(),
                reflection_history,
                last_reflected_ids,
            )

        if out_dir and selected_frame_ids:
            self._save_frames(selected_frame_ids, out_dir)

        _conversation = memory.get_messages()

        if self.verbose:
            print(f"\n[TAKAAgent] Done. {len(selected_frame_ids)} frames selected.")
        return selected_frame_ids, _conversation, final_reflection, reflection_history

    def _check_submission(self, raw) -> Tuple[List[int], Optional[list]]:
        """Pre-Reflector check. Returns (ids, None) when every id is an integer
        frame id returned by an earlier tool call (sorted into temporal order,
        duplicates removed), else (ids_so_far, invalid_ids)."""
        if not isinstance(raw, list):
            return [], [raw]
        returned = self.registry.returned_ids
        ids, bad = set(), []
        for x in raw:
            if isinstance(x, bool) or not isinstance(x, int) or x not in returned:
                bad.append(x)
            else:
                ids.add(x)
        return sorted(ids), (bad or None)

    def _check_crop_ids(self, raw, submitted_ids: List[int]) -> Tuple[List[str], str]:
        """Selector crop ids for Reflect: each must exist and crop a submitted frame."""
        if raw is None or raw == []:
            return [], ""
        if not isinstance(raw, list):
            return [], f"crop_ids={raw!r} must be a list of crop ids returned by Crop."
        ids: List[str] = []
        for cid in raw:
            info = self.crops.get(cid)
            if info is None:
                return [], f"unknown crop id {cid!r}; use crop ids returned by Crop."
            if info["frame_id"] not in submitted_ids:
                return [], (f"crop {cid} is a crop of frame {info['frame_id']}, which is not in "
                            f"frame_ids; submit the frame together with its crop.")
            if cid not in ids:
                ids.append(cid)
        if len(submitted_ids) + len(ids) > MAX_REQUEST_IMAGES:
            return [], (f"{len(submitted_ids)} frames + {len(ids)} crops exceed the "
                        f"{MAX_REQUEST_IMAGES} images one Reflector request can hold; submit fewer crops.")
        return ids, ""

    @staticmethod
    def _budget_note(steps_used: int, max_steps: int) -> str:
        """Search-step reminder appended to every Selector-facing tool result. Reflect does
        not use steps; once the steps are used up, only Reflect can be called."""
        remaining = max_steps - steps_used
        note = f"\n\n[Search steps: {steps_used}/{max_steps} used, {remaining} left.]"
        if remaining <= 0:
            note += " No search steps left: your next call must be Reflect."
        elif remaining <= 3:
            note += " Call Reflect soon."
        return note

    # ── Phase 3: Visual Self-Reflection ─────────────────────────────

    def _visual_self_reflect(
        self,
        frame_ids: List[int],
        question: str,
        model: LLMofAgent,
        crop_ids: Optional[List[str]] = None,
        candidates: list = None,
        use_long_video_section: bool = False,
        reflect_temperature: float = 0.0,
        reflect_top_p: Optional[float] = None,
        reflect_max_tokens: int = 1024,
        selector_tool_call_id: Optional[str] = None,
        allow_best_guess: bool = False,
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Run the same endpoint with a fresh Reflector prompt to solve the question from
        the submitted frames (temporal order, long side TAKA_IMAGE_MAX_SIDE) plus any Selector
        crops. Before its verdict the Reflector may call Crop (regions at native resolution)
        and Enhance (whole frames at TAKA_ENHANCE_MAX_SIDE) on submitted frames, at most
        TAKA_REFLECTOR_MAX_TOOL_CALLS times.

        The whole exchange is kept in self.trace["reflector"] (messages, message_meta,
        calls), linked to the Selector's Reflect call by selector_tool_call_id.
        Returns (validated CONFIRM/REJECT decision, the Reflector's tool-call records).
        """
        # 收集帧图像: 任一提交帧无法解码 -> 致命错误, 终止程序(不再默认 CONFIRM)
        try:
            pairs = self.vi.get_frames(frame_ids)
        except InputDataError as exc:
            raise FatalFrameDecodeError(
                f"Reflector cannot decode submitted frames {frame_ids} "
                f"(video={getattr(self.vi, 'video_path', None)}): {exc}")
        if not pairs:
            raise FatalFrameDecodeError(f"Reflector received no frames to review: {frame_ids}")
        crop_ids = list(crop_ids or [])

        if candidates:
            candidates_text = "\n".join(f"  {chr(65+i)}. {c}" for i, c in enumerate(candidates))
        else:
            candidates_text = "  (No candidates provided)"

        # System prompt holds only per-question constants, and the frame images come
        # first in the user turn (temporal order): a resubmission after REJECT that keeps
        # the earliest frames reuses their prefill from the vLLM prefix cache.
        reflect_prompt = format_reflector_prompt(
            question=question,
            candidates=candidates_text,
            long_video_section=(
                get_reflector_duration_section(self.vi.total_duration)
                if use_long_video_section
                else ""
            ),
            crop_section=get_reflector_crop_section(REFLECTOR_MAX_TOOL_CALLS),
            allow_best_guess=allow_best_guess,
            open_ended=not bool(candidates),
        )
        content: List[Dict[str, Any]] = []
        for fid, img in pairs:
            content.append({"type": "text", "text": f"Frame {fid} @ {self.vi.frame_time(fid):.1f}s:"})
            content.append(_image_part(img, IMAGE_MAX_SIDE, quality=90))
        for cid in crop_ids:
            info = self.crops.get(cid)
            content.append({"type": "text", "text": (
                f"Crop {cid} of Frame {info['frame_id']} (box {info['box']} in 0-1000 coordinates):")})
            content.append(_image_part(info["image"], CROP_MAX_SIDE, quality=90))
        listing = ", ".join(f"{fid} @ {self.vi.frame_time(fid):.1f}s" for fid, _ in pairs)
        content.append({"type": "text", "text": (
            f"Submitted frames ({len(pairs)}, temporal order): {listing}."
            + (f" Selector crops: {', '.join(crop_ids)}." if crop_ids else "")
            + " Review them and give your verdict.")})
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": reflect_prompt},
            {"role": "user", "content": content},
        ]
        trace: Dict[str, Any] = {
            "attempt": len(self.trace["reflector"]) + 1,
            "selector_tool_call_id": selector_tool_call_id,
            "messages": messages,
            "message_meta": [{"source": "env", "call": None, "reason": None}] * 2,
            "calls": [],
        }
        self.trace["reflector"].append(trace)

        def add(message: Dict[str, Any], source: str = "env", call: Optional[int] = None,
                reason: Optional[str] = None) -> int:
            messages.append(message)
            trace["message_meta"].append({"source": source, "call": call, "reason": reason})
            return len(messages) - 1

        # Each reply is either one tool call (executed and appended; at most
        # REFLECTOR_MAX_TOOL_CALLS per Reflect, then tools are no longer offered) or the
        # verdict JSON. Timeout/Error, a malformed tool call, or an unparsable verdict counts
        # as one failed attempt: recorded in calls as discarded, not appended, retried with a
        # note saying what was wrong. LLM_MAX_ATTEMPTS failures -> QuestionFailed.
        qid = getattr(self, "_qid", None)
        tool_records: List[Dict[str, Any]] = []
        images = len(pairs) + len(crop_ids)
        tool_turns = 0
        failures = 0
        truncated = 0   # failures that were replies cut at reflect_max_tokens
        usage: Dict[str, Any] = {}
        retry_note: Optional[str] = None
        while failures < LLM_MAX_ATTEMPTS:
            room = MAX_REQUEST_IMAGES - images
            tools = (get_reflector_openai_tools()
                     if tool_turns < REFLECTOR_MAX_TOOL_CALLS and room > 0 else None)
            resp = _chat_once_logged(
                model,
                messages + ([{"role": "user", "content": retry_note}] if retry_note else []),
                "reflector",
                qid,
                failures + 1,
                frame_count=images,
                duration_sec=self.vi.total_duration,
                usage_out=usage,
                calls_out=trace["calls"],
                temperature=reflect_temperature,
                top_p=reflect_top_p,
                max_tokens=reflect_max_tokens,
                override_top_p=True,
                **({"tools": tools, "tool_choice": "auto"} if tools else {}),
            )
            if resp is None:
                failures += 1
                continue
            if usage.get("finish_reason") == "length":
                # A reply cut at max_tokens is discarded and resampled (as MMDR), with a
                # one-line request to think more briefly; nothing enters the trajectory.
                failures += 1
                truncated += 1
                retry_note = _TRUNCATED_REMINDER.format(
                    action="call one tool or output your JSON verdict")
                _settle_call(trace["calls"], invalid_reason="truncated")
                _log(qid, f"[reflector] Truncated at max_tokens={reflect_max_tokens} "
                          f"(attempt {failures}/{LLM_MAX_ATTEMPTS})")
                continue
            if isinstance(resp, dict) and resp.get("tool_calls"):
                calls = self._parse_native_tool_calls(resp)
                if not calls:
                    failures += 1
                    _settle_call(trace["calls"], invalid_reason="malformed_tool_call")
                    retry_note = ("Your previous reply contained a malformed tool call. Call one tool "
                                  "with valid JSON arguments, or output your JSON verdict.")
                    _log(qid, f"[reflector] InvalidToolCall (attempt {failures}/{LLM_MAX_ATTEMPTS}): "
                              f"malformed tool call {str(resp.get('tool_calls'))[:160]!r}")
                    continue
                retry_note = None
                tool_turns += 1
                idx = add({"role": "assistant", "content": resp.get("content") or "",
                           "tool_calls": resp["tool_calls"], "reasoning": resp.get("reasoning") or ""},
                          source="model", call=trace["calls"][-1]["call"])
                _settle_call(trace["calls"], message_index=idx)
                if len(calls) > 1:
                    text = (f"Tool error: {len(calls)} tool calls in one turn; none was executed. "
                            f"Call one tool per turn; one call can take several regions or frames.")
                    results = [(text, {"status": "error", "error": "multiple_tool_calls"})] * len(calls)
                elif calls[0]["action"] == "Crop":
                    results = [self._reflector_crop(calls[0]["params"].get("regions"), frame_ids, room)]
                elif calls[0]["action"] == "Enhance":
                    results = [self._reflector_enhance(calls[0]["params"].get("frame_ids"), frame_ids, room)]
                else:
                    results = [(f"Tool error: unknown tool {calls[0]['action']!r}; available: Crop, Enhance.",
                                {"status": "error", "error": "unknown_tool"})]
                left = REFLECTOR_MAX_TOOL_CALLS - tool_turns
                note = (f"{left} tool call(s) left." if left > 0
                        else "No tool calls left: output your JSON verdict now.")
                for call, (tool_content, record) in zip(calls, results):
                    images += record.get("n_images", 0)
                    tool_records.append({"tool_call_id": call["call_id"], "tool": call["action"],
                                         "args": call["params"], **record})
                    if isinstance(tool_content, list):
                        tool_content = tool_content + [{"type": "text", "text": note}]
                    else:
                        tool_content = f"{tool_content} {note}"
                    add({"role": "tool", "tool_call_id": call["call_id"], "name": call["action"],
                         "content": tool_content},
                        reason="tool_error" if record["status"] == "error" else None)
                continue
            text = resp.get("content", "") if isinstance(resp, dict) else resp
            text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()
            if self.verbose:
                print(f"  [Reflect] VLM response: {text[:200]}")
            obj = self._parse_reflect_json(text)
            normalized, error = self._validate_reflect_decision(
                obj, frame_ids, candidates or [], allow_best_guess=allow_best_guess)
            if normalized:
                idx = add({"role": "assistant", "content": text, "reasoning": usage.get("reasoning") or ""},
                          source="model", call=trace["calls"][-1]["call"])
                _settle_call(trace["calls"], message_index=idx)
                return normalized, tool_records
            failures += 1
            _settle_call(trace["calls"], invalid_reason=f"invalid_verdict: {error}")
            allowed_statuses = (
                "CONFIRM, UNASSESSABLE, or REJECT"
                if not candidates
                else "CONFIRM, BEST_GUESS (when offered), or REJECT"
            )
            retry_note = (f"Your previous reply was not a valid verdict ({error}). Output exactly one "
                          f"JSON object as specified in the Output Protocol: valid JSON (double quotes, "
                          f"no comments, no trailing text), status {allowed_statuses} with exactly the "
                          f"listed fields.")
            _log(qid, f"[reflector] InvalidVerdict (attempt {failures}/{LLM_MAX_ATTEMPTS}): "
                      f"{error}; response={text[:400]!r}")
        raise QuestionFailed(FAILED_REFLECTOR_TRUNCATED if truncated == failures else FAILED_REFLECTOR)

    def _reflector_crop(self, regions: Any, frame_ids: List[int], room: int) -> Tuple[Any, Dict[str, Any]]:
        """One Reflector Crop call -> (tool message content, record)."""
        try:
            if isinstance(regions, list) and len(regions) > room:
                raise ToolFeedback(f"{len(regions)} regions requested but this request has room for "
                                   f"only {room} more image(s)")
            crops = self.crops.make_many(regions, set(frame_ids), "one of the submitted frames")
        except ToolFeedback as exc:
            return f"Tool error: Crop: {exc}", {"status": "error", "error": str(exc)}
        content: List[Dict[str, Any]] = []
        for crop_id, crop in crops:
            info = self.crops.get(crop_id)
            content.append({"type": "text", "text": (
                f"Crop {crop_id} of Frame {info['frame_id']}, box {info['box']}:")})
            content.append(_image_part(crop, CROP_MAX_SIDE, quality=90))
        return content, {"status": "ok", "crop_ids": [cid for cid, _ in crops], "n_images": len(crops)}

    def _reflector_enhance(self, ids: Any, frame_ids: List[int], room: int) -> Tuple[Any, Dict[str, Any]]:
        """One Reflector Enhance call -> (tool message content, record)."""
        try:
            if (not isinstance(ids, list) or not ids
                    or any(isinstance(x, bool) or not isinstance(x, int) for x in ids)):
                raise ToolFeedback(f"frame_ids={ids!r} must be a non-empty list of submitted frame ids")
            wanted = sorted(set(ids))
            if len(wanted) > ENHANCE_MAX_FRAMES:
                raise ToolFeedback(f"at most {ENHANCE_MAX_FRAMES} frames per Enhance call")
            unknown = [x for x in wanted if x not in frame_ids]
            if unknown:
                raise ToolFeedback(f"frames {unknown} were not submitted")
            if len(wanted) > room:
                raise ToolFeedback(f"this request has room for only {room} more image(s)")
            frames = self.vi.get_frames(wanted)
        except ToolFeedback as exc:
            return f"Tool error: Enhance: {exc}", {"status": "error", "error": str(exc)}
        content: List[Dict[str, Any]] = []
        for fid, img in frames:
            content.append({"type": "text", "text": f"Frame {fid} @ {self.vi.frame_time(fid):.1f}s, enhanced:"})
            content.append(_image_part(img, ENHANCE_MAX_SIDE, quality=90))
        return content, {"status": "ok", "frame_ids": wanted, "n_images": len(frames)}

    def export_trace(self) -> Dict[str, Any]:
        """Trajectory of the last run (MMDR-PLANNER style): the Selector's message_meta,
        calls and tool_stats (its messages are the saved `conversation`), and every
        Reflector exchange with its messages, message_meta and calls."""
        trace = getattr(self, "trace", None) or {"selector": {}, "reflector": []}
        memory = getattr(self, "_memory", None)
        stats: Dict[str, Dict[str, Any]] = {}
        if memory is not None:
            for msg, meta in zip(memory.get_messages(), memory.meta):
                if msg.get("role") != "tool":
                    continue
                s = stats.setdefault(msg.get("name") or "?", {"calls": 0, "ok": 0, "failed": 0,
                                                              "not_executed": 0, "failure_reasons": {}})
                s["calls"] += 1
                reason = meta.get("reason")
                if reason in ("step_budget", "context_budget", "repeated_call", "handoff_violation"):
                    s["not_executed"] += 1
                    s["failure_reasons"][reason] = s["failure_reasons"].get(reason, 0) + 1
                elif reason == "tool_error":
                    s["failed"] += 1
                    text = msg["content"] if isinstance(msg["content"], str) else ""
                    key = text.split(":", 2)[1].strip()[:40] if text.count(":") >= 2 else "error"
                    s["failure_reasons"][key] = s["failure_reasons"].get(key, 0) + 1
                else:
                    s["ok"] += 1
        return {"selector": {**trace.get("selector", {}), "tool_stats": {"by_tool": stats}},
                "reflector": trace.get("reflector", [])}

    # ── 内部工具 ─────────────────────────────────────────────────

    @staticmethod
    def _parse_reflect_json(text: str) -> Dict[str, Any]:
        """
        从 Reflect VLM 输出中提取包含 status 字段的 JSON。
        Reflector 的结论以文本 JSON 给出（Crop 是唯一的 tool call），因此单独解析其严格的 CONFIRM/REJECT JSON。
        """
        idx = 0
        while idx < len(text):
            s = text.find("{", idx)
            if s < 0:
                break
            depth = 0
            for i in range(s, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(text[s : i + 1])
                            if "status" in obj:
                                return obj
                        except json.JSONDecodeError:
                            pass
                        idx = i + 1
                        break
            else:
                break
        return {}

    @staticmethod
    def _validate_reflect_decision(
        obj: Dict[str, Any],
        submitted_ids: List[int],
        candidates: List[Any],
        allow_best_guess: bool = False,
    ) -> Tuple[Dict[str, Any], str]:
        if not isinstance(obj, dict):
            return {}, "verdict is not an object"
        status = obj.get("status")
        if status == "UNASSESSABLE":
            if candidates:
                return {}, "UNASSESSABLE is available only for open-ended safety analysis"
            decision, error = TAKAAgent._validate_reflect_decision(
                {**obj, "status": "CONFIRM"},
                submitted_ids,
                candidates,
                allow_best_guess=allow_best_guess,
            )
            return (
                {**decision, "status": "UNASSESSABLE"} if decision else {},
                error.replace("CONFIRM", "UNASSESSABLE"),
            )
        if status == "BEST_GUESS":
            # Same fields as CONFIRM; ends the task with the best-supported answer when the
            # missing fact cannot be visible in the frames (offered only after a REJECT).
            if not allow_best_guess:
                return {}, "BEST_GUESS is not available in this review; use CONFIRM or REJECT"
            if not candidates:
                return {}, "BEST_GUESS is not available for open-ended safety analysis"
            decision, error = TAKAAgent._validate_reflect_decision(
                {**obj, "status": "CONFIRM"}, submitted_ids, candidates)
            return ({**decision, "status": "BEST_GUESS"} if decision else {}), error.replace(
                "CONFIRM", "BEST_GUESS")
        if status == "REJECT":
            if set(obj) != {"status", "reason", "missing_evidence", "suggestion"}:
                return {}, (
                    "REJECT must contain only "
                    "status/reason/missing_evidence/suggestion"
                )
            reason = obj.get("reason")
            missing = obj.get("missing_evidence")
            suggestion = obj.get("suggestion")
            if not isinstance(reason, str) or not reason.strip():
                return {}, "REJECT reason is empty"
            if (not isinstance(missing, list) or not missing
                    or any(not isinstance(x, str) or not x.strip() for x in missing)):
                return {}, "REJECT missing_evidence must be a non-empty string list"
            if not isinstance(suggestion, str) or not suggestion.strip():
                return {}, "REJECT suggestion is empty"
            return {
                "status": "REJECT",
                "reason": reason.strip(),
                "missing_evidence": [x.strip() for x in missing],
                "suggestion": suggestion.strip(),
            }, ""

        if status == "CONFIRM":
            if set(obj) != {"status", "answer", "reason", "evidence_frame_ids"}:
                return {}, "CONFIRM must contain only status/answer/reason/evidence_frame_ids"
            answer = obj.get("answer")
            reason = obj.get("reason")
            raw_evidence = obj.get("evidence_frame_ids")
            if not isinstance(answer, dict):
                return {}, "CONFIRM answer is not an object"
            if set(answer) != {"choice", "text"}:
                return {}, "CONFIRM answer must contain only choice/text"
            # The answer is kept exactly as the Reflector wrote it (e.g. "B" or "B. Orange.");
            # mapping it to a candidate is the evaluation's job, not a reason to resample.
            if not isinstance(answer.get("choice"), str):
                return {}, "CONFIRM answer.choice must be a string"
            if candidates and not answer["choice"].strip():
                return {}, "CONFIRM answer.choice must be a non-empty string"
            if not isinstance(answer.get("text"), str) or not answer["text"].strip():
                return {}, "CONFIRM answer.text must be a non-empty string"
            if not isinstance(reason, str) or not reason.strip():
                return {}, "CONFIRM reason is empty"
            if not isinstance(raw_evidence, list) or not raw_evidence:
                return {}, "CONFIRM evidence_frame_ids must be non-empty"
            evidence: List[int] = []
            submitted = set(submitted_ids)
            for fid in raw_evidence:
                if isinstance(fid, bool) or not isinstance(fid, int):
                    return {}, f"invalid evidence frame id {fid!r}"
                if fid not in submitted:
                    return {}, f"evidence frame {fid} was not submitted"
                if fid not in evidence:
                    evidence.append(fid)
            return {
                "status": "CONFIRM",
                "answer": {"choice": answer["choice"].strip(), "text": answer["text"].strip()},
                "reason": reason.strip(),
                "evidence_frame_ids": evidence,
            }, ""

        return {}, f"unknown status {status!r}"

    @staticmethod
    def _parse_reflect_tool_content(content: str) -> Dict[str, Any]:
        """Parse the authoritative answer out of a confirmed Reflect tool result."""
        obj = json.loads(content)
        if not isinstance(obj, dict):
            raise ValueError("Reflect tool content is not an object")
        if not isinstance(obj.get("reflected_frame_ids"), list):
            raise ValueError("Reflect tool content does not contain reflected_frame_ids")
        if obj.get("status") not in ("CONFIRM", "BEST_GUESS", "UNASSESSABLE"):
            raise ValueError("Reflect tool content is not a final answer")
        return {key: value for key, value in obj.items() if key != "reflected_frame_ids"}

    @staticmethod
    def _parse_native_tool_calls(message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Validate the native function call(s) of one reply. Returns one entry per call
        ({thought, action, params, call_id}), or [] when there is no call or any call is
        malformed (that reply is then resampled)."""
        calls = message.get("tool_calls")
        if not isinstance(calls, list) or not calls:
            return []
        reasoning = message.get("reasoning") or message.get("content") or ""
        reasoning = re.sub(r"<think>.*?</think>", "", str(reasoning), flags=re.DOTALL).strip()
        parsed = []
        for call in calls:
            function = call.get("function") if isinstance(call, dict) else None
            if not isinstance(function, dict) or not isinstance(function.get("name"), str):
                return []
            raw_arguments = function.get("arguments", "{}")
            if isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError:
                    return []
            elif isinstance(raw_arguments, dict):
                arguments = raw_arguments
            else:
                return []
            if not isinstance(arguments, dict):
                return []
            parsed.append({"thought": reasoning, "action": function["name"],
                           "params": arguments, "call_id": call.get("id")})
        return parsed

    def _save_frames(self, frame_ids: List[int], out_dir: str) -> None:
        os.makedirs(out_dir, exist_ok=True)
        for i, fid in enumerate(sorted(frame_ids)):
            img = self.vi.get_frame(fid)
            if img is None:
                continue
            path = os.path.join(out_dir, f"frame_{i:04d}_idx{fid:06d}.jpg")
            img.save(path)
            print(f"   Saved {path}")
