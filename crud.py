"""
CRUD Operations for Adaptive Athletic Training System
=====================================================

All functions accept plain Python dicts (matching the shapes produced by
Pydantic .model_dump()) and return ORM model instances so callers can
decide how much to read from the returned object.

Sections:
  1. User
  2. GeneratedPlan
  3. TrainingSession
  4. Helpers
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models import (
    Conversation,
    GeneratedPlan,
    Message,
    TrainingProgram,
    TrainingSession,
    User,
)


# =============================================================================
# 1. User
# =============================================================================

def create_user(db: Session, profile: Dict[str, Any]) -> User:
    """
    Persist a new user profile.

    Raises:
        sqlalchemy.exc.IntegrityError: if user_id already exists.
    """
    user = User(
        user_id=profile["user_id"],
        basic_info=profile.get("basic_info", {}),
        fitness_level=profile.get("fitness_level", "beginner"),
        fitness_goal=profile.get("fitness_goal"),
        training_frequency=profile.get("training_frequency"),
        medical_history=profile.get("medical_history", []),
        available_equipment=profile.get("available_equipment") or [],
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user(db: Session, user_id: str) -> Optional[User]:
    """Return the User with this user_id, or None."""
    return db.query(User).filter(User.user_id == user_id).first()


def upsert_user(db: Session, profile: Dict[str, Any]) -> User:
    """Create or update a user profile from a full profile dict."""
    existing = get_user(db, profile["user_id"])
    if existing:
        updated = update_user(db, profile["user_id"], profile)
        return updated or existing
    return create_user(db, profile)


def update_user(db: Session, user_id: str, updates: Dict[str, Any]) -> Optional[User]:
    """
    Partial-update a user profile.
    Only the fields present in *updates* are changed.
    Returns None if the user does not exist.
    """
    user = get_user(db, user_id)
    if not user:
        return None

    updatable_fields = (
        "basic_info",
        "fitness_level",
        "fitness_goal",
        "training_frequency",
        "medical_history",
        "available_equipment",
    )
    for field in updatable_fields:
        if field in updates and updates[field] is not None:
            setattr(user, field, updates[field])

    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return user


def user_to_profile_dict(user: User) -> Dict[str, Any]:
    """
    Convert a User ORM object to the profile dict shape expected by
    RiskAssessmentEngine and PlanGeneratorMock.
    """
    return {
        "user_id": user.user_id,
        "basic_info": user.basic_info or {},
        "fitness_level": user.fitness_level or "beginner",
        "fitness_goal": user.fitness_goal,
        "training_frequency": user.training_frequency,
        "medical_history": user.medical_history or [],
        "available_equipment": getattr(user, "available_equipment", None) or [],
    }


# =============================================================================
# 2. GeneratedPlan
# =============================================================================

def save_generated_plan(
    db: Session,
    plan_export: Dict[str, Any],
    generator_version: str = "unknown",
    draft_data: Optional[Dict[str, Any]] = None,
    profile_data: Optional[Dict[str, Any]] = None,
) -> GeneratedPlan:
    """
    Persist a plan dict produced by PlanGeneratorMock.export_plan_as_json().

    ``draft_data`` 是 ``PlanDraft.to_dict()`` 的原始结构（带 exercise_id）。
    ``plan_data`` 只存渲染后的名字，无法反查动作库 —— 对话里要修订计划时
    必须靠 draft_data 才能重建草稿。``profile_data`` 是当时的风险档案，
    修订时当作安全地板，防止重算把伤病约束冲淡。

    Idempotent: if the plan_id already exists, returns the existing record.
    """
    existing = get_generated_plan(db, plan_export["plan_id"])
    if existing:
        return existing

    record = GeneratedPlan(
        plan_id=plan_export["plan_id"],
        user_id=plan_export["user_id"],
        workout_type=plan_export["workout_type"],
        plan_data=plan_export,
        draft_data=draft_data,
        profile_data=profile_data,
        generator_version=generator_version,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_latest_user_plan(db: Session, user_id: str) -> Optional[GeneratedPlan]:
    """最新一份计划 —— 对话里说「把深蹲去掉」时，改的就是它。"""
    return (
        db.query(GeneratedPlan)
        .filter(GeneratedPlan.user_id == user_id)
        .order_by(GeneratedPlan.generated_at.desc(), GeneratedPlan.id.desc())
        .first()
    )


def get_generated_plan(db: Session, plan_id: str) -> Optional[GeneratedPlan]:
    return db.query(GeneratedPlan).filter(GeneratedPlan.plan_id == plan_id).first()


def get_user_plans(
    db: Session,
    user_id: str,
    limit: int = 10,
    offset: int = 0,
) -> List[GeneratedPlan]:
    """Return a user's plan history, newest first."""
    return (
        db.query(GeneratedPlan)
        .filter(GeneratedPlan.user_id == user_id)
        .order_by(GeneratedPlan.generated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def update_generated_plan(
    db: Session,
    plan_id: str,
    plan_data: Dict[str, Any],
) -> Optional[GeneratedPlan]:
    """Overwrite stored plan JSON (e.g. after safety revalidation)."""
    record = get_generated_plan(db, plan_id)
    if not record:
        return None
    record.plan_data = plan_data
    db.commit()
    db.refresh(record)
    return record


def count_user_plans(db: Session, user_id: str) -> int:
    return db.query(GeneratedPlan).filter(GeneratedPlan.user_id == user_id).count()


# =============================================================================
# 3. TrainingSession
# =============================================================================

def create_training_session(
    db: Session,
    session_data: Dict[str, Any],
) -> TrainingSession:
    """
    Persist a completed training session.

    *session_data* must include at minimum:
        user_id (str)
        rpe     (int, 1-10)
        pain_feedback (dict with at least {"has_pain": bool})

    Optional fields mirror FeedbackInput + plan_id.
    A session_id is auto-generated (uuid4) if not provided.
    """
    session_id = (
        session_data.get("session_id")
        or f"sess_{uuid.uuid4().hex[:12]}"
    )
    date = session_data.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    record = TrainingSession(
        session_id=session_id,
        user_id=session_data["user_id"],
        plan_id=session_data.get("plan_id"),
        # Phase 3: link to a multi-week program
        program_id=session_data.get("program_id"),
        program_week=session_data.get("program_week"),
        date=date,
        workout_type=session_data.get("workout_type"),
        duration_minutes=session_data.get("duration_minutes"),
        rpe=session_data["rpe"],
        completion_rate=session_data.get("completion_rate"),
        pain_feedback=session_data.get("pain_feedback", {"has_pain": False}),
        fatigue_feedback=session_data.get("fatigue_feedback"),
        exercise_performance=session_data.get("exercise_performance"),
        notes=session_data.get("notes"),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_training_sessions(
    db: Session,
    user_id: str,
    limit: int = 20,
    offset: int = 0,
) -> List[TrainingSession]:
    """Return a user's session history, newest first."""
    return (
        db.query(TrainingSession)
        .filter(TrainingSession.user_id == user_id)
        .order_by(TrainingSession.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def count_training_sessions(db: Session, user_id: str) -> int:
    return (
        db.query(TrainingSession)
        .filter(TrainingSession.user_id == user_id)
        .count()
    )


def get_latest_session(db: Session, user_id: str) -> Optional[TrainingSession]:
    """Return the most recent completed session for adaptive plan generation."""
    return (
        db.query(TrainingSession)
        .filter(TrainingSession.user_id == user_id)
        .order_by(TrainingSession.created_at.desc())
        .first()
    )


def get_session_by_id(db: Session, session_id: str) -> Optional[TrainingSession]:
    return (
        db.query(TrainingSession)
        .filter(TrainingSession.session_id == session_id)
        .first()
    )


# =============================================================================
# 5. TrainingProgram  (Phase 3)
# =============================================================================

def create_program(db: Session, program_data: Dict[str, Any]) -> TrainingProgram:
    """Persist a newly generated training program."""
    record = TrainingProgram(
        program_id          = program_data["program_id"],
        user_id             = program_data["user_id"],
        name                = program_data["name"],
        status              = program_data.get("status", "active"),
        goal                = program_data["goal"],
        split_type          = program_data["split_type"],
        periodization_model = program_data.get("periodization_model", "linear"),
        total_weeks         = program_data["total_weeks"],
        current_week        = program_data.get("current_week", 1),
        sessions_per_week   = program_data["sessions_per_week"],
        program_data        = program_data,
        generator_version   = program_data.get("generator_version", "unknown"),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_program(db: Session, program_id: str) -> Optional[TrainingProgram]:
    return (
        db.query(TrainingProgram)
        .filter(TrainingProgram.program_id == program_id)
        .first()
    )


def update_program(
    db: Session,
    program_id: str,
    updated_data: Dict[str, Any],
) -> Optional[TrainingProgram]:
    """
    Overwrite the program_data JSON and sync scalar columns.
    Called by advance_week after computing the next-week adaptation.
    """
    record = get_program(db, program_id)
    if not record:
        return None

    record.program_data  = updated_data
    record.current_week  = updated_data.get("current_week", record.current_week)
    record.status        = updated_data.get("status", record.status)
    record.updated_at    = datetime.now(timezone.utc)
    db.commit()
    db.refresh(record)
    return record


def get_user_programs(
    db: Session,
    user_id: str,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> List[TrainingProgram]:
    q = db.query(TrainingProgram).filter(TrainingProgram.user_id == user_id)
    if status:
        q = q.filter(TrainingProgram.status == status)
    return q.order_by(TrainingProgram.created_at.desc()).offset(offset).limit(limit).all()


def count_user_programs(db: Session, user_id: str, status: Optional[str] = None) -> int:
    q = db.query(TrainingProgram).filter(TrainingProgram.user_id == user_id)
    if status:
        q = q.filter(TrainingProgram.status == status)
    return q.count()


def get_active_program(db: Session, user_id: str) -> Optional[TrainingProgram]:
    """Return the most recent active program for a user."""
    return (
        db.query(TrainingProgram)
        .filter(TrainingProgram.user_id == user_id, TrainingProgram.status == "active")
        .order_by(TrainingProgram.created_at.desc())
        .first()
    )


def pause_active_programs(db: Session, user_id: str) -> int:
    """Pause all active programs for a user. Returns how many were paused."""
    active = get_user_programs(db, user_id, status="active", limit=100)
    paused = 0
    for record in active:
        data = dict(record.program_data or {})
        data["status"] = "paused"
        update_program(db, record.program_id, data)
        paused += 1
    return paused


def get_sessions_for_program_week(
    db: Session,
    program_id: str,
    week_number: int,
) -> List[TrainingSession]:
    """
    Return all training sessions logged against a specific program week.
    Used by advance_week to analyse weekly completion.
    """
    return (
        db.query(TrainingSession)
        .filter(
            TrainingSession.program_id   == program_id,
            TrainingSession.program_week == week_number,
        )
        .order_by(TrainingSession.created_at.asc())
        .all()
    )


def get_recent_sessions(
    db: Session,
    user_id: str,
    n: int = 10,
) -> List[TrainingSession]:
    """
    Return the *n* most recent training sessions for a user, newest first.

    Used by the history analyzer (Phase 2) to build LLM context.
    """
    return (
        db.query(TrainingSession)
        .filter(TrainingSession.user_id == user_id)
        .order_by(TrainingSession.created_at.desc())
        .limit(n)
        .all()
    )


# =============================================================================
# 4. Helpers
# =============================================================================

def session_to_feedback_dict(session: TrainingSession) -> Dict[str, Any]:
    """
    Convert a TrainingSession ORM object back to the FeedbackInput dict shape
    expected by RiskAssessmentEngine.analyze_dynamic_feedback() and
    history_analyzer.analyze_history().
    """
    return {
        "session_id":       session.session_id,
        "user_id":          session.user_id,
        "date":             session.date,
        "workout_type":     session.workout_type,
        "duration_minutes": session.duration_minutes,
        "rpe":              session.rpe,
        "completion_rate":  session.completion_rate,
        "pain_feedback":    session.pain_feedback or {"has_pain": False},
        "fatigue_feedback": session.fatigue_feedback,
        "exercise_performance": session.exercise_performance,
        "program_id":       getattr(session, "program_id",   None),
        "program_week":     getattr(session, "program_week", None),
        "notes":            session.notes,
    }


# =============================================================================
# 6. Conversation & Message  (Phase 4)
# =============================================================================

def create_conversation(
    db: Session,
    user_id: str,
    title: Optional[str] = None,
    program_id: Optional[str] = None,
) -> Conversation:
    """Start a new chat session for a user."""
    conv = Conversation(
        conversation_id=f"conv_{uuid.uuid4().hex[:12]}",
        user_id=user_id,
        title=title or "新对话",
        program_id=program_id,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def get_conversation(db: Session, conversation_id: str) -> Optional[Conversation]:
    return (
        db.query(Conversation)
        .filter(Conversation.conversation_id == conversation_id)
        .first()
    )


def list_user_conversations(
    db: Session,
    user_id: str,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> List[Conversation]:
    q = db.query(Conversation).filter(Conversation.user_id == user_id)
    if status:
        q = q.filter(Conversation.status == status)
    return q.order_by(Conversation.updated_at.desc()).offset(offset).limit(limit).all()


def count_user_conversations(
    db: Session, user_id: str, status: Optional[str] = None
) -> int:
    q = db.query(Conversation).filter(Conversation.user_id == user_id)
    if status:
        q = q.filter(Conversation.status == status)
    return q.count()


def update_conversation_title(
    db: Session, conversation_id: str, title: str
) -> Optional[Conversation]:
    conv = get_conversation(db, conversation_id)
    if not conv:
        return None
    conv.title = title
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conv)
    return conv


def archive_conversation(
    db: Session, conversation_id: str
) -> Optional[Conversation]:
    conv = get_conversation(db, conversation_id)
    if not conv:
        return None
    conv.status = "archived"
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conv)
    return conv


def add_message(
    db: Session,
    conversation_id: str,
    role: str,
    content: str,
    action_request: Optional[Dict[str, Any]] = None,
) -> Message:
    """Append a message to a conversation; bumps the conversation's updated_at."""
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        action_request=action_request,
    )
    db.add(msg)

    conv = get_conversation(db, conversation_id)
    if conv:
        conv.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(msg)
    return msg


def get_messages(
    db: Session,
    conversation_id: str,
    limit: Optional[int] = None,
) -> List[Message]:
    """Return messages in chronological order. If limit is set, take the latest N."""
    q = db.query(Message).filter(Message.conversation_id == conversation_id)
    if limit:
        # Take the most recent N, then reverse to chronological
        items = q.order_by(Message.created_at.desc()).limit(limit).all()
        return list(reversed(items))
    return q.order_by(Message.created_at.asc()).all()


def messages_to_history_dicts(messages: List[Message]) -> List[Dict[str, str]]:
    """
    Convert ORM messages → list of {"role", "content"} dicts that
    CoachAgent.build_messages() expects as prior history.
    Skips system messages (the coach injects its own system prompt).
    """
    out: List[Dict[str, str]] = []
    for m in messages:
        if m.role in ("user", "assistant") and m.content:
            out.append({"role": m.role, "content": m.content})
    return out
