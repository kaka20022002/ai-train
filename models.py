"""
SQLAlchemy ORM Models for Adaptive Athletic Training System
===========================================================

Six core tables:
  users             — persisted user profiles (replaces one-off JSON files)
  generated_plans   — history of every LLM/Mock-generated single-session plan
  training_sessions — completed workout sessions + post-workout feedback
  training_programs — multi-week mesocycle programs (Phase 3)
  conversations     — AI coach chat sessions (Phase 4)
  messages          — individual messages within a conversation (Phase 4)

All JSON columns (basic_info, medical_history, plan_data, pain_feedback,
fatigue_feedback) are stored as native JSON in SQLite 3.38+ and PostgreSQL,
and fall back to TEXT serialisation on older SQLite builds via SQLAlchemy's
JSON type.
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Float, Integer, String, Text, DateTime, JSON

from database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    """
    Persisted user profile.

    Mirrors the UserProfile Pydantic schema used by the API, but lives in the
    DB so the frontend only needs to send user_id on subsequent requests.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(64), unique=True, index=True, nullable=False)

    # Nested objects stored as JSON blobs for schema flexibility
    basic_info = Column(JSON, nullable=False, default=dict)
    medical_history = Column(JSON, nullable=False, default=list)

    fitness_level = Column(String(32), default="beginner")
    fitness_goal = Column(String(128), nullable=True)
    training_frequency = Column(Integer, nullable=True)  # sessions per week

    # Sprint 3: equipment the user has access to (e.g. ["barbell", "dumbbell"]).
    # Empty / null means "full equipment access" (no filtering applied).
    available_equipment = Column(JSON, nullable=True, default=list)

    created_at = Column(DateTime(timezone=True), default=_utcnow)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class GeneratedPlan(Base):
    """
    Archive of every workout plan produced by the system.

    Storing the full plan_data JSON lets us:
    - Replay any historical plan in the UI
    - Compare LLM vs Mock outputs
    - Feed plan history to future context-aware prompts (Phase 2)
    """
    __tablename__ = "generated_plans"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(String(64), index=True, nullable=False)
    workout_type = Column(String(64), nullable=False)
    plan_data = Column(JSON, nullable=False)          # full export_plan_as_json dict
    # PlanDraft.to_dict(): 动作的 exercise_id / impact / load_pct 等原始字段。
    # plan_data 里只有渲染后的名字，无法反查动作库 —— 用户说「把深蹲去掉」
    # 需要拿真正的草稿去做修订，所以另存一份。
    draft_data = Column(JSON, nullable=True)
    # RiskProfile.to_dict(): 生成时的风险档案。对话内修订要拿它当「安全地板」，
    # 否则用户说一句「换个动作」，重跑状态分析就会把上一轮的伤病约束冲掉。
    profile_data = Column(JSON, nullable=True)
    generator_version = Column(String(32), default="unknown")
    generated_at = Column(DateTime(timezone=True), default=_utcnow)


class TrainingSession(Base):
    """
    Record of a completed training session with post-workout feedback.

    This is the primary data source for the adaptive feedback loop:
    - RPE trend → intensity adjustment
    - Pain reports → joint exclusion rules
    - Fatigue accumulation → deload detection (Phase 2)

    The pain_feedback and fatigue_feedback columns mirror the PainFeedback
    and FatigueFeedback Pydantic schemas exactly so they round-trip cleanly.
    """
    __tablename__ = "training_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(String(64), index=True, nullable=False)
    plan_id = Column(String(64), nullable=True)       # which plan was executed

    date = Column(String(16), nullable=False)          # YYYY-MM-DD
    workout_type = Column(String(64), nullable=True)
    duration_minutes = Column(Integer, nullable=True)

    rpe = Column(Integer, nullable=False)              # 1-10 Borg scale
    completion_rate = Column(Float, nullable=True)     # 0.0 – 1.0

    pain_feedback = Column(JSON, nullable=False, default=dict)
    fatigue_feedback = Column(JSON, nullable=True)

    notes = Column(Text, nullable=True)

    # Phase 2: per-exercise performance log for progressive overload tracking.
    # Each item: {"name": str, "weight_kg": float|null, "sets_completed": int|null,
    #             "reps_per_set": [int, ...] | null, "notes": str|null}
    exercise_performance = Column(JSON, nullable=True)

    # Phase 3: links this session to a long-term training program and week.
    program_id   = Column(String(64), nullable=True, index=True)
    program_week = Column(Integer,    nullable=True)   # 1-based week number

    created_at = Column(DateTime(timezone=True), default=_utcnow)


class TrainingProgram(Base):
    """
    Multi-week training program (mesocycle) generated by ProgramGeneratorService.

    The full program structure — all weeks, sessions, exercises, periodization
    parameters — lives in program_data (JSON). The scalar columns provide fast
    filtering and status management without deserialising the blob.

    Status machine: active → completed | paused
    Week types:     base · progression · peak · deload
    """
    __tablename__ = "training_programs"

    id = Column(Integer, primary_key=True, index=True)
    program_id = Column(String(64), unique=True, index=True, nullable=False)
    user_id    = Column(String(64), index=True,  nullable=False)

    name        = Column(String(256), nullable=False)
    status      = Column(String(32),  default="active")   # active/completed/paused
    goal        = Column(String(64),  nullable=False)      # strength/hypertrophy/general_fitness
    split_type  = Column(String(64),  nullable=False)      # upper_lower/full_body/push_pull_legs
    periodization_model = Column(String(64), default="linear")

    total_weeks        = Column(Integer, nullable=False)
    current_week       = Column(Integer, default=1)
    sessions_per_week  = Column(Integer, nullable=False)

    program_data       = Column(JSON, nullable=False)      # full program dict

    generator_version  = Column(String(32), default="unknown")
    created_at         = Column(DateTime(timezone=True), default=_utcnow)
    updated_at         = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


# =============================================================================
# Phase 4 — Conversational Coach
# =============================================================================

class Conversation(Base):
    """
    A chat session between the user and the AI coach.

    Multiple conversations per user are allowed — useful for separating topics
    (general advice / specific program review / injury rehab planning, etc.).
    """
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String(64), unique=True, index=True, nullable=False)
    user_id         = Column(String(64), index=True, nullable=False)
    title           = Column(String(256), default="新对话")
    status          = Column(String(32),  default="active")  # active / archived

    # Optional anchor: link conversation to a specific program for richer context.
    program_id      = Column(String(64), nullable=True)

    created_at      = Column(DateTime(timezone=True), default=_utcnow)
    updated_at      = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class Message(Base):
    """
    A single message in a conversation.

    role:
      "user"      — message authored by the user
      "assistant" — message from the AI coach
      "system"    — context / system events (rarely persisted; for audit)

    The optional ``action_request`` JSON column captures any structured
    action the coach suggested (so the UI can re-render confirmation state
    when the conversation is reloaded).
    """
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(String(64), index=True, nullable=False)
    role            = Column(String(16),  nullable=False)
    content         = Column(Text,        nullable=False)
    action_request  = Column(JSON,        nullable=True)
    created_at      = Column(DateTime(timezone=True), default=_utcnow)


class WeChatAccount(Base):
    """
    Maps a WeChat mini-program openid to an internal user_id.
    Created on first successful /auth/wechat/login.
    """
    __tablename__ = "wechat_accounts"

    id = Column(Integer, primary_key=True, index=True)
    openid = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(String(64), index=True, nullable=False)
    unionid = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
