"""
Chat Router — Phase 4: Conversational Coach API
=================================================

Endpoints
---------
  POST   /chat                                       — start new conversation OR continue
  GET    /users/{user_id}/conversations              — list user's conversations
  GET    /conversations/{cid}                        — full message history
  POST   /conversations/{cid}/messages               — send a follow-up (sync)
  POST   /conversations/{cid}/messages/stream        — SSE streaming reply
  PATCH  /conversations/{cid}/title                  — rename
  PATCH  /conversations/{cid}/archive                — archive

Design notes
------------
- The coach is *stateless*; conversation state lives entirely in the DB.
- For streaming we use FastAPI's StreamingResponse with text/event-stream MIME
  (server-sent events). Each event is a JSON object on a single ``data:`` line.
- All endpoints are graceful when the LLM is not configured — CoachAgent's
  fallback returns a deterministic helpful message instead of erroring out.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import crud
from agents.intent import (
    INTENT_GENERATE,
    INTENT_REVISE,
    IntentResult,
    classify_intent,
)
import chat_planning
from coach_agent import CoachAgent, build_context
from database import get_db

router = APIRouter(tags=["AI Coach Chat"])

# Single shared agent instance — stateless, safe for concurrent requests
_agent = CoachAgent()


# =============================================================================
# Pydantic schemas
# =============================================================================

class ActionRequestSchema(BaseModel):
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    rationale: Optional[str] = ""
    confirm_label: Optional[str] = ""


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    action_request: Optional[ActionRequestSchema] = None
    created_at: Optional[str] = None


class ConversationSummary(BaseModel):
    conversation_id: str
    user_id: str
    title: str
    status: str
    program_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    message_count: int = 0


class ConversationListResponse(BaseModel):
    user_id: str
    total: int
    limit: int
    offset: int
    conversations: List[ConversationSummary]


class ConversationDetail(ConversationSummary):
    messages: List[MessageResponse] = Field(default_factory=list)


class ChatRequest(BaseModel):
    """
    Send a message to the AI coach.

    - If `conversation_id` is omitted, a new conversation is created.
    - `user_id` is always required (the coach reads from this user's DB context).
    """
    user_id: str = Field(..., description="The user this conversation belongs to")
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: Optional[str] = Field(
        None,
        description="Continue an existing conversation. Omit to start a new one.",
    )
    title: Optional[str] = Field(
        None,
        description="Optional title for a new conversation (auto-derived from the first message if missing).",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "usr_001",
                "message": "我最近膝盖有点疼，下次训练需要调整吗？",
            }
        }


class ChatResponse(BaseModel):
    conversation_id: str
    user_message: MessageResponse
    assistant_message: MessageResponse
    action_request: Optional[ActionRequestSchema] = None
    # ── 这一轮若真的生成了计划，直接带结构化结果回来 ──────────────────────
    # 前端据此渲染计划卡片；为 None 表示这一轮只做了问答。
    plan: Optional[Dict[str, Any]] = None
    safety: Optional[Dict[str, Any]] = None
    #: 跑了哪几个 Agent、各阶段耗时 —— 让「到底过没过审查」可查
    agent_trace: Optional[Dict[str, Any]] = None
    #: 意图路由结果（generate_plan / revise_plan / ask）
    intent: Optional[str] = None


class TitleUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=256)


# =============================================================================
# Helpers
# =============================================================================

def _msg_to_response(m) -> MessageResponse:
    ar = m.action_request
    return MessageResponse(
        id=m.id,
        role=m.role,
        content=m.content,
        action_request=ActionRequestSchema(**ar) if ar else None,
        created_at=m.created_at.isoformat() if m.created_at else None,
    )


def _conv_to_summary(c, message_count: int = 0) -> ConversationSummary:
    return ConversationSummary(
        conversation_id=c.conversation_id,
        user_id=c.user_id,
        title=c.title or "新对话",
        status=c.status or "active",
        program_id=c.program_id,
        created_at=c.created_at.isoformat() if c.created_at else None,
        updated_at=c.updated_at.isoformat() if c.updated_at else None,
        message_count=message_count,
    )


def _derive_title(message: str) -> str:
    """Generate a short title from the first user message (first ~24 chars)."""
    text = message.strip().replace("\n", " ")
    return (text[:24] + "…") if len(text) > 24 else text


def _ensure_conversation(
    db: Session,
    user_id: str,
    conversation_id: Optional[str],
    fallback_title: str,
):
    """
    Resolve or create a conversation. Validates user ownership when given.
    """
    if conversation_id:
        conv = crud.get_conversation(db, conversation_id)
        if not conv:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Conversation '{conversation_id}' not found.",
            )
        if conv.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Conversation does not belong to this user.",
            )
        return conv

    return crud.create_conversation(db, user_id=user_id, title=fallback_title)


# =============================================================================
# Helpers — 计划生成/修改的意图分派
# =============================================================================
# 需求：对话里要生成计划，必须走完整三个 Agent；修改与问答可以只过一部分。
# 分类器在 agents.intent，这里只负责「按分类结果调管线 + 把结果拼进响应」。


def _get_bridges():
    """取三 Agent 的 LLM 装配。

    动态导入而非模块级 import：``main`` 会 import 本模块，写死在顶部会循环导入。
    运行时 ``main`` 已在 sys.modules 里，取到的是同一个对象，因此测试里
    ``monkeypatch.setattr(main, "AGENT_BRIDGES", ...)`` 依然生效。
    """
    try:
        import main as _main

        return getattr(_main, "AGENT_BRIDGES", None)
    except Exception:  # noqa: BLE001 - 拿不到就走降级后端
        return None


def _latest_feedback(db: Session, user_id: str) -> Optional[Dict[str, Any]]:
    """最近一次训练的反馈，作为动态约束喂给状态分析。"""
    try:
        session = crud.get_latest_session(db, user_id)
    except Exception:  # noqa: BLE001
        return None
    return crud.session_to_feedback_dict(session) if session else None


def _revisable_draft(db: Session, user_id: str):
    """取最近一份可修订的草稿；老计划没有 draft_data，只能重新生成。"""
    record = crud.get_latest_user_plan(db, user_id)
    return chat_planning.draft_from_record(record)


def _run_plan_turn(
    db: Session,
    *,
    user_id: str,
    message: str,
    intent: IntentResult,
    user_profile: Dict[str, Any],
    history: Optional[List[Dict[str, str]]] = None,
) -> Optional[chat_planning.PlanTurn]:
    """按意图跑管线。失败返回 None，调用方退回教练问答。"""
    from safety_sync import _get_engine

    exercise_db = _get_engine().exercise_db
    feedback = _latest_feedback(db, user_id)
    bridges = _get_bridges()

    record = crud.get_latest_user_plan(db, user_id)
    draft = (
        chat_planning.draft_from_record(record)
        if intent.intent == INTENT_REVISE
        else None
    )
    # 最近的用户原话：伤病常常只出现在对话里，档案是空的
    history_text = "\n".join(
        str(m.get("content") or "")
        for m in (history or [])
        if m.get("role") == "user"
    )

    try:
        if draft is not None:
            return chat_planning.run_revision_turn(
                exercise_db=exercise_db,
                user_profile=user_profile,
                feedback=feedback,
                instruction=message,
                draft=draft,
                prev_profile=chat_planning.profile_from_record(record),
                history_text=history_text,
                bridges=bridges,
            )
        return chat_planning.run_generation_turn(
            exercise_db=exercise_db,
            user_profile=user_profile,
            feedback=feedback,
            workout_type=intent.workout_hint or "full_body",
            query=message,
            bridges=bridges,
        )
    except Exception as exc:  # noqa: BLE001 - 生成失败不该让整轮对话报错
        print(f"   ⚠️  plan turn failed ({intent.intent}): {exc}")
        return None


def _plan_response_payload(turn: "chat_planning.PlanTurn") -> Dict[str, Any]:
    return {
        "plan": turn.plan,
        "safety": turn.safety,
        "agent_trace": {
            "agents": turn.agents_run,
            "elapsed_ms": turn.elapsed_ms,
            "stage_ms": turn.stage_ms,
            "review_rounds": turn.review_rounds,
            "revision_applied": turn.revision_applied,
        },
    }


def _persist_plan(db: Session, turn: "chat_planning.PlanTurn") -> None:
    """落库：下一轮用户说「把深蹲去掉」时，要靠 draft_data 才改得动；
    profile_data 则是修订时的安全地板（伤病可能只存在于对话里）。"""
    try:
        crud.save_generated_plan(
            db,
            turn.plan,
            generator_version=str(turn.plan.get("generator_version") or "unknown"),
            draft_data=turn.draft.to_dict() if turn.draft else None,
            profile_data=turn.profile.to_dict() if turn.profile else None,
        )
    except Exception as exc:  # noqa: BLE001 - 存不下来不影响这一轮交付
        print(f"   ⚠️  failed to persist plan: {exc}")


# =============================================================================
# Endpoints — conversation management
# =============================================================================

@router.get(
    "/users/{user_id}/conversations",
    response_model=ConversationListResponse,
    summary="List a user's chat conversations",
)
def list_conversations(
    user_id: str,
    conversation_status: Optional[str] = Query(
        None, description="Filter by status: active | archived"
    ),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    convs = crud.list_user_conversations(
        db, user_id, status=conversation_status, limit=limit, offset=offset
    )
    total = crud.count_user_conversations(db, user_id, status=conversation_status)

    summaries: List[ConversationSummary] = []
    for c in convs:
        n = len(crud.get_messages(db, c.conversation_id))
        summaries.append(_conv_to_summary(c, n))

    return ConversationListResponse(
        user_id=user_id,
        total=total,
        limit=limit,
        offset=offset,
        conversations=summaries,
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    summary="Get full conversation including all messages",
)
def get_conversation_detail(conversation_id: str, db: Session = Depends(get_db)):
    conv = crud.get_conversation(db, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found.")
    messages = crud.get_messages(db, conversation_id)
    summary = _conv_to_summary(conv, len(messages))
    return ConversationDetail(
        **summary.model_dump(),
        messages=[_msg_to_response(m) for m in messages],
    )


@router.patch(
    "/conversations/{conversation_id}/title",
    response_model=ConversationSummary,
    summary="Rename a conversation",
)
def rename_conversation(
    conversation_id: str,
    request: TitleUpdateRequest,
    db: Session = Depends(get_db),
):
    conv = crud.update_conversation_title(db, conversation_id, request.title)
    if not conv:
        raise HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found.")
    return _conv_to_summary(conv, len(crud.get_messages(db, conversation_id)))


@router.patch(
    "/conversations/{conversation_id}/archive",
    response_model=ConversationSummary,
    summary="Archive a conversation",
)
def archive_conversation(conversation_id: str, db: Session = Depends(get_db)):
    conv = crud.archive_conversation(db, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail=f"Conversation '{conversation_id}' not found.")
    return _conv_to_summary(conv, len(crud.get_messages(db, conversation_id)))


# =============================================================================
# Endpoints — sending messages (sync)
# =============================================================================

@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Send a message to the AI coach (creates a new conversation if needed)",
)
def chat(
    request: ChatRequest,
    history_window: int = Query(8, ge=1, le=30, description="Recent sessions to include in context"),
    db: Session = Depends(get_db),
):
    """
    Synchronous (non-streaming) chat with the AI coach.

    The coach automatically loads:
    - Your user profile (medical history, fitness level)
    - Recent training history analysis (RPE trends, pain patterns)
    - Active multi-week program (if any) and your next session

    For long-form responses prefer the streaming endpoint
    `/chat/stream` or `/conversations/{id}/messages/stream`.
    """
    conv = _ensure_conversation(
        db,
        user_id=request.user_id,
        conversation_id=request.conversation_id,
        fallback_title=request.title or _derive_title(request.message),
    )

    # Persist the user message first so the LLM sees consistent history if it
    # were to recurse (currently it doesn't, but this is the safe ordering).
    user_msg = crud.add_message(db, conv.conversation_id, "user", request.message)

    # Build context + load prior history (last 30 turns)
    prior_messages = crud.get_messages(db, conv.conversation_id, limit=30)
    history_dicts = crud.messages_to_history_dicts(prior_messages[:-1])  # exclude the just-added user message

    # ── 意图分派：要计划就跑三 Agent，问答才交给教练 ────────────────────
    user = crud.get_user(db, request.user_id)
    user_profile = (
        crud.user_to_profile_dict(user) if user else {"user_id": request.user_id}
    )
    has_plan = _revisable_draft(db, request.user_id) is not None
    intent = classify_intent(
        request.message,
        has_plan=has_plan,
        history=[str(m.get("content") or "") for m in history_dicts[-4:]],
    )

    if intent.intent in (INTENT_GENERATE, INTENT_REVISE):
        turn = _run_plan_turn(
            db,
            user_id=request.user_id,
            message=request.message,
            intent=intent,
            user_profile=user_profile,
            history=history_dicts,
        )
        if turn is not None:
            payload = _plan_response_payload(turn)
            asst_msg = crud.add_message(
                db,
                conv.conversation_id,
                role="assistant",
                content=turn.text,
                action_request={
                    "tool": "generated_plan",
                    "args": {"plan_id": turn.plan.get("plan_id")},
                },
            )
            _persist_plan(db, turn)
            return ChatResponse(
                conversation_id=conv.conversation_id,
                user_message=_msg_to_response(user_msg),
                assistant_message=_msg_to_response(asst_msg),
                intent=intent.intent,
                **payload,
            )

    # 顺序：先有历史再建上下文 —— 教练侧的风险分析要参考用户前面说过的话
    context = build_context(
        db,
        request.user_id,
        history_window=history_window,
        message=request.message,
        history=history_dicts,
    )

    response = _agent.respond(
        context=context,
        history=history_dicts,
        user_message=request.message,
    )

    action_dict = response.action_request.to_dict() if response.action_request else None
    asst_msg = crud.add_message(
        db,
        conv.conversation_id,
        role="assistant",
        content=response.content,
        action_request=action_dict,
    )

    return ChatResponse(
        conversation_id=conv.conversation_id,
        user_message=_msg_to_response(user_msg),
        assistant_message=_msg_to_response(asst_msg),
        action_request=ActionRequestSchema(**action_dict) if action_dict else None,
        intent=intent.intent,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=ChatResponse,
    summary="Send a follow-up message in an existing conversation",
)
def post_message(
    conversation_id: str,
    request: ChatRequest,
    history_window: int = Query(8, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """Convenience alias of POST /chat that pins the conversation_id from the URL."""
    request.conversation_id = conversation_id
    return chat(request=request, history_window=history_window, db=db)


# =============================================================================
# Endpoints — SSE streaming
# =============================================================================

def _sse_format(event: Dict[str, Any]) -> str:
    """Format a dict as an SSE 'data:' line."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post(
    "/chat/stream",
    summary="Stream a chat response via Server-Sent Events",
)
def chat_stream(
    request: ChatRequest,
    history_window: int = Query(8, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """
    Stream a coach response token-by-token using Server-Sent Events (SSE).

    The response Content-Type is `text/event-stream`. Each line begins with
    `data: ` followed by a single-line JSON object.

    Event payloads:
        {"type": "start", "conversation_id": "...", "user_message_id": <int>}
        {"type": "delta", "text": "..."}                        — repeated
        {"type": "final", "content": "...",
                          "action_request": {...} | null,
                          "assistant_message_id": <int>}
        {"type": "error", "message": "..."}                     — terminal on failure

    The frontend should accumulate `delta.text` for live typing, and use
    `final.content` as the canonical persisted message body.
    """
    conv = _ensure_conversation(
        db,
        user_id=request.user_id,
        conversation_id=request.conversation_id,
        fallback_title=request.title or _derive_title(request.message),
    )

    user_msg = crud.add_message(db, conv.conversation_id, "user", request.message)

    prior = crud.get_messages(db, conv.conversation_id, limit=30)
    history_dicts = crud.messages_to_history_dicts(prior[:-1])

    # ── 要计划的对话同样必须过三 Agent（流式与同步行为保持一致）────────
    _user = crud.get_user(db, request.user_id)
    _profile = crud.user_to_profile_dict(_user) if _user else {"user_id": request.user_id}
    intent = classify_intent(
        request.message,
        has_plan=_revisable_draft(db, request.user_id) is not None,
        history=[str(m.get("content") or "") for m in history_dicts[-4:]],
    )

    if intent.intent in (INTENT_GENERATE, INTENT_REVISE):

        def plan_event_stream():
            yield _sse_format({
                "type": "start",
                "conversation_id": conv.conversation_id,
                "user_message_id": user_msg.id,
                "intent": intent.intent,
            })
            yield _sse_format({
                "type": "status",
                "text": "正在跑三个 Agent（风险分析 → 生成 → 安全审查），约 60-90 秒…",
            })
            turn = _run_plan_turn(
                db,
                user_id=request.user_id,
                message=request.message,
                intent=intent,
                user_profile=_profile,
                history=history_dicts,
            )
            if turn is None:
                yield _sse_format({"type": "error", "message": "计划生成失败，请稍后重试"})
                return
            asst = crud.add_message(
                db,
                conv.conversation_id,
                role="assistant",
                content=turn.text,
                action_request={
                    "tool": "generated_plan",
                    "args": {"plan_id": turn.plan.get("plan_id")},
                },
            )
            _persist_plan(db, turn)
            yield _sse_format({
                "type": "final",
                "content": turn.text,
                "assistant_message_id": asst.id,
                "intent": intent.intent,
                **_plan_response_payload(turn),
            })

        return StreamingResponse(
            plan_event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    context = build_context(
        db,
        request.user_id,
        history_window=history_window,
        message=request.message,
        history=history_dicts,
    )

    def event_stream():
        # Initial event tells the client what conversation we're on
        yield _sse_format({
            "type": "start",
            "conversation_id": conv.conversation_id,
            "user_message_id": user_msg.id,
        })

        full_content_parts: List[str] = []
        action_dict: Optional[Dict[str, Any]] = None
        final_clean: str = ""

        try:
            for evt in _agent.stream_respond(
                context=context,
                history=history_dicts,
                user_message=request.message,
            ):
                if evt["type"] == "delta":
                    full_content_parts.append(evt["text"])
                    yield _sse_format(evt)
                elif evt["type"] == "final":
                    final_clean = evt.get("content", "")
                    action_dict = evt.get("action_request")
                    # The assistant message is persisted *after* full stream
                    # — so we attach the new id to the final event.
                elif evt["type"] == "error":
                    yield _sse_format(evt)
                    return
        except Exception as exc:
            yield _sse_format({"type": "error", "message": f"streaming failed: {exc}"})
            return

        # Persist the assistant's full reply
        if not final_clean:
            # If for some reason the provider didn't emit a final event,
            # fall back to the concatenated stream.
            final_clean = "".join(full_content_parts).strip()
            if not final_clean:
                final_clean = "（教练未返回任何内容）"

        asst_msg = crud.add_message(
            db,
            conv.conversation_id,
            role="assistant",
            content=final_clean,
            action_request=action_dict,
        )

        yield _sse_format({
            "type": "final",
            "content": final_clean,
            "action_request": action_dict,
            "assistant_message_id": asst_msg.id,
        })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx proxy buffering
        },
    )


@router.post(
    "/conversations/{conversation_id}/messages/stream",
    summary="Stream a follow-up reply for an existing conversation",
)
def post_message_stream(
    conversation_id: str,
    request: ChatRequest,
    history_window: int = Query(8, ge=1, le=30),
    db: Session = Depends(get_db),
):
    """Streaming variant of POST /conversations/{id}/messages."""
    request.conversation_id = conversation_id
    return chat_stream(request=request, history_window=history_window, db=db)
