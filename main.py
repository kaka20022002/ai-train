"""
Adaptive Athletic Risk Assessment System - FastAPI Application
===============================================================

This module provides a RESTful API for the Adaptive Athletic Training System.
It exposes endpoints for generating personalized, constraint-respecting
workout plans based on user injury profiles and workout feedback.

Author: Master's Thesis Project - Adaptive Athletic Risk Assessment System
Date: 2026-03-04

To run the server:
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

API Documentation (auto-generated):
    - Swagger UI: http://localhost:8000/docs
    - ReDoc: http://localhost:8000/redoc
"""

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
import os
from pathlib import Path
from urllib.parse import quote, unquote
import httpx
from sqlalchemy.orm import Session

# Load .env before routers / plan_generator read USE_REAL_LLM & LLM_* vars
# override=True: 避免本机已有的 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN
# （例如指向 DeepSeek）覆盖项目 .env 中的 MiniMax 配置。
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
except ImportError:
    pass

# Import our custom modules
from risk_engine import RiskAssessmentEngine, ForbiddenExercise, RiskConstraint
from plan_generator_mock import PlanGeneratorMock, WorkoutPlan
from program_generator import ProgramGeneratorService
from plan_program_sync import sync_plan_after_generation
from history_analyzer import analyze_history

# 三 Agent 计划生成管线（状态分析 → 计划生成 → 安全评估 + 风险条件约束解码）
from agents import (
    PlanAgent,
    SafetyEvalAgent,
    StateRiskAgent,
    build_bridges,
    build_exercise_index,
    render_plan_draft,
)
from agents import run_pipeline as run_agent_pipeline
from agents.contracts import PHASES as AGENT_PHASES

# Database layer
from database import engine, get_db
import models
import crud
from routers.users import router as users_router
from routers.programs import router as programs_router
from routers.recommendations import router as recommendations_router
from routers.chat import router as chat_router
from routers.insights import router as insights_router
from routers.auth import router as auth_router
from routers.stt import router as stt_router
from routers.video_analysis import router as video_analysis_router
from exercise_meta import guide_for, all_guides, animation_frames, sanitize_workout_phases


# =============================================================================
# Pydantic Models for Request/Response Validation
# =============================================================================

class MedicalHistoryItem(BaseModel):
    """Schema for a single medical history entry."""
    location: str = Field(..., description="Joint/body part affected (e.g., 'knee', 'shoulder', 'spine')")
    condition: str = Field(..., description="Medical condition in snake_case (e.g., 'meniscus_tear')")
    severity: str = Field(..., description="Severity level: 'low', 'medium', or 'high'")
    pain_trigger: Optional[str] = Field(None, description="Movement that triggers pain (e.g., 'deep_flexion')")
    onset_date: Optional[str] = Field(None, description="Date when injury occurred (YYYY-MM-DD)")
    notes: Optional[str] = Field(None, description="Additional notes about the injury")


class BasicInfo(BaseModel):
    """Schema for user basic information."""
    age: int = Field(..., ge=16, le=100, description="User age (16-100)")
    gender: str = Field(..., description="User gender")
    height_cm: Optional[float] = Field(None, description="Height in centimeters")
    weight_kg: Optional[float] = Field(None, description="Weight in kilograms")
    bmi: Optional[float] = Field(None, description="Body Mass Index")


class TrainingPreferences(BaseModel):
    """用户的训练偏好（兴趣）。

    这是**软约束**：影响模型选动作的倾向，不构成医学禁忌。
    与 medical_history 的区别在于——不喜欢不等于不能做，
    所以它不会被写进 forbidden，只作为排序与取舍的偏好。
    """
    liked_patterns: List[str] = Field(
        default_factory=list,
        description="喜欢的动作模式（如 ['squat', 'hinge']），选动作时优先考虑",
    )
    disliked_patterns: List[str] = Field(
        default_factory=list,
        description="不喜欢的动作模式，同等条件下尽量避开（不是禁忌）",
    )
    disliked_exercises: List[str] = Field(
        default_factory=list,
        description="明确不想做的动作名称（中英文均可）",
    )
    notes: Optional[str] = Field(
        None, description="自由文本，如「怕练粗腿」「讨厌长时间有氧」"
    )


class UserProfile(BaseModel):
    """Schema for complete user profile."""
    user_id: str = Field(..., description="Unique user identifier")
    basic_info: BasicInfo
    fitness_level: str = Field("beginner", description="Fitness level: 'beginner', 'intermediate', 'advanced'")
    fitness_goal: Optional[str] = Field(None, description="Primary fitness goal")
    training_frequency: Optional[int] = Field(None, description="Training sessions per week")
    available_equipment: Optional[List[str]] = Field(
        None,
        description=(
            "Equipment the user can train with (e.g. ['barbell', 'dumbbell', 'cable']). "
            "Exercises requiring unavailable equipment are excluded from generation. "
            "Empty/None means full equipment access."
        ),
    )
    medical_history: List[MedicalHistoryItem] = Field(default_factory=list)
    preferences: Optional[TrainingPreferences] = Field(
        None, description="训练偏好（兴趣），软约束"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "usr_001",
                "basic_info": {
                    "age": 28,
                    "gender": "male",
                    "height_cm": 175,
                    "weight_kg": 78,
                    "bmi": 25.5
                },
                "fitness_level": "intermediate",
                "fitness_goal": "strength",
                "training_frequency": 4,
                "medical_history": [
                    {
                        "location": "knee",
                        "condition": "meniscus_tear",
                        "severity": "high",
                        "pain_trigger": "deep_flexion",
                        "notes": "Right knee, avoid deep squats"
                    }
                ]
            }
        }


class PainFeedback(BaseModel):
    """Schema for pain feedback from a workout session."""
    has_pain: bool = Field(..., description="Whether user experienced pain")
    pain_location: Optional[str] = Field(None, description="Location of pain")
    pain_severity: Optional[int] = Field(None, ge=1, le=10, description="Pain severity (1-10)")
    pain_type: Optional[str] = Field(None, description="Type of pain (e.g., 'sharp', 'dull')")
    trigger_exercise: Optional[str] = Field(None, description="Exercise that triggered pain")
    trigger_moment: Optional[str] = Field(None, description="When pain occurred")
    notes: Optional[str] = Field(None, description="Additional notes")


class FatigueFeedback(BaseModel):
    """Schema for fatigue feedback."""
    overall_fatigue: Optional[int] = Field(None, ge=1, le=10, description="Overall fatigue level (1-10)")
    muscle_soreness: Optional[List[str]] = Field(None, description="List of sore muscles")
    sleep_quality_last_night: Optional[int] = Field(None, ge=1, le=10)
    stress_level: Optional[int] = Field(None, ge=1, le=10)


class FeedbackInput(BaseModel):
    """Schema for complete workout feedback."""
    session_id: Optional[str] = Field(None, description="Session identifier")
    user_id: str = Field(..., description="User identifier")
    date: Optional[str] = Field(None, description="Date of workout (YYYY-MM-DD)")
    workout_type: Optional[str] = Field(None, description="Type of workout completed")
    duration_minutes: Optional[int] = Field(None, description="Workout duration")
    rpe: int = Field(..., ge=1, le=10, description="Rate of Perceived Exertion (1-10)")
    completion_rate: Optional[float] = Field(None, ge=0, le=1, description="Completion rate (0-1)")
    pain_feedback: PainFeedback
    fatigue_feedback: Optional[FatigueFeedback] = None
    notes: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "sess_001",
                "user_id": "usr_001",
                "date": "2026-03-04",
                "rpe": 8,
                "completion_rate": 0.85,
                "pain_feedback": {
                    "has_pain": True,
                    "pain_location": "knee",
                    "pain_severity": 5,
                    "pain_type": "sharp",
                    "trigger_exercise": "Leg Press"
                }
            }
        }


class GeneratePlanRequest(BaseModel):
    """Request body for the /generate_plan endpoint."""
    user_profile: UserProfile
    feedback: Optional[FeedbackInput] = None
    workout_type: str = Field("full_body", description="Type of workout to generate")
    query: Optional[str] = Field(
        None,
        max_length=500,
        description=(
            "本次训练需求的一句话描述（自由文本），如「今天想练下肢，只有三十分钟，"
            "膝盖蹲到底有点不舒服」。会原样进入状态分析 Agent，用于抽取"
            "时长上限、症状描述这类结构化字段表达不出的信息。"
        ),
    )

    class Config:
        json_schema_extra = {
            "example": {
                "user_profile": {
                    "user_id": "usr_001",
                    "basic_info": {"age": 28, "gender": "male", "bmi": 25.5},
                    "fitness_level": "intermediate",
                    "medical_history": [
                        {"location": "knee", "condition": "meniscus_tear", "severity": "high"}
                    ]
                },
                "feedback": {
                    "user_id": "usr_001",
                    "rpe": 7,
                    "pain_feedback": {"has_pain": False}
                },
                "workout_type": "full_body"
            }
        }


class ExerciseResponse(BaseModel):
    """Schema for exercise in response."""
    name: str
    name_zh: Optional[str] = Field(
        None,
        description="Chinese display name; frontend may fall back to its own label map",
    )
    sets: int
    reps: str
    rest_seconds: int
    load_pct: Optional[int] = Field(
        None,
        description="强度百分比（1RM 的百分比）。自重/弹力带动作与静态拉伸为 null。",
    )
    notes: Optional[str] = None
    target_muscle: Optional[str] = None


class WorkoutPhases(BaseModel):
    """Schema for workout phases."""
    warm_up: List[ExerciseResponse]
    activation: List[ExerciseResponse]
    main_lifts: List[ExerciseResponse]
    accessories: List[ExerciseResponse]
    cool_down: List[ExerciseResponse]


class ForbiddenExerciseResponse(BaseModel):
    """Schema for forbidden exercise in response."""
    name: str
    reason: str
    substitution: str


class RiskAnalysisResponse(BaseModel):
    """Schema for risk analysis summary."""
    forbidden_exercises: List[ForbiddenExerciseResponse]
    safe_exercise_count: int
    constraints: List[str]


class SafetyViolationResponse(BaseModel):
    """One constraint violation found by the safety-evaluation agent."""
    code: str
    exercise_id: int
    phase: str
    detail: str


class SafetySummaryResponse(BaseModel):
    """Safety conclusion returned alongside every generated plan."""
    passed: bool
    checked_slots: int
    masked_count: int = Field(0, description="禁忌动作在候选池里被屏蔽的数量")
    adversarial_probes: int = Field(0, description="对抗探针注入次数")
    adversarial_blocked: int = Field(0, description="探测动作被拦下的次数")
    profile_hash: str = ""
    grammar_version: str = ""
    rejected_ids: List[int] = Field(default_factory=list, description="生成阶段被白名单挡回的 ID")
    violations: List[SafetyViolationResponse] = Field(default_factory=list)
    # ── 三个 Agent 的 LLM 审查痕迹（未启用 LLM 时分别为 skipped / deterministic）──
    llm_verdict: str = Field(
        "skipped", description="安全评估 Agent 的 LLM 结论：pass / fail / error / skipped"
    )
    llm_disagreed: bool = Field(
        False, description="LLM 结论与规则结论是否不一致（论文里的分歧指标）"
    )
    llm_rationale: str = Field("", description="LLM 审查说明（仅作展示，不参与判定）")
    llm_prompt_version: str = ""
    state_llm_status: str = Field(
        "", description="状态分析 Agent 的 LLM 状态：applied / empty / error / skipped"
    )
    # ── 病历语义抽取出的约束（规则表算不出来，只能由 Agent 1 给）──────────
    avoid_patterns: List[str] = Field(
        default_factory=list, description="需回避的动作模式（如 squat / lunge）"
    )
    session_cap_minutes: Optional[int] = Field(
        None, description="单次训练时长上限（分钟）"
    )
    progression_note: str = Field("", description="进阶/退阶方向建议")
    capacity_note: str = Field("", description="当前训练容量判断")
    adjusted_slots: int = Field(
        0, description="参数被夹进合法区间的槽位数（模型越界程度）"
    )


class GeneratePlanResponse(BaseModel):
    """Response body for the /generate_plan endpoint."""
    plan_id: str
    user_id: str
    date: str
    workout_type: str
    estimated_duration_minutes: int
    phases: WorkoutPhases
    safety_notes: List[str]
    risk_analysis: RiskAnalysisResponse
    generated_at: str
    generator_version: str
    program_id: Optional[str] = Field(
        None,
        description="When save_to_db=true, the training program created from this plan",
    )
    safety: Optional[SafetySummaryResponse] = Field(
        None,
        description="三 Agent 管线的安全评估结论（engine=agents 时返回）",
    )
    audit: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="逐条结构化审计记录：state_risk / plan_gen / safety_eval",
    )


class HealthCheckResponse(BaseModel):
    """Response for health check endpoint."""
    status: str
    version: str
    exercise_db_loaded: bool
    exercise_count: int
    timestamp: str


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    detail: str
    timestamp: str


# =============================================================================
# FastAPI Application Setup
# =============================================================================

# Create all DB tables (SQLite auto-creates the file if missing).
# For production with PostgreSQL, use Alembic migrations instead.
models.Base.metadata.create_all(bind=engine)

# Lightweight inline migration: add columns introduced after the initial schema.
# safe to call repeatedly — the except branch silently ignores "already exists".
def _run_migrations() -> None:
    from sqlalchemy import text as _sql
    _migrations = [
        # Phase 2: exercise performance tracking
        "ALTER TABLE training_sessions ADD COLUMN exercise_performance JSON",
        # Phase 3: link sessions to a multi-week program
        "ALTER TABLE training_sessions ADD COLUMN program_id TEXT",
        "ALTER TABLE training_sessions ADD COLUMN program_week INTEGER",
        # Sprint 3: equipment-aware programming
        "ALTER TABLE users ADD COLUMN available_equipment JSON",
    ]
    with engine.connect() as _conn:
        for _stmt in _migrations:
            try:
                _conn.execute(_sql(_stmt))
                _conn.commit()
            except Exception:
                pass  # column already present

_run_migrations()

app = FastAPI(
    title="Adaptive Athletic Risk Assessment API",
    description="""
    ## 🏋️ Adaptive Athletic Training System API
    
    This API provides intelligent workout plan generation that respects user
    injury profiles and workout feedback. It implements a two-phase risk
    assessment approach:
    
    ### Features
    - **Static Risk Analysis**: Filters exercises based on chronic injuries
    - **Dynamic Feedback Analysis**: Adapts to recent workout feedback
    - **LLM-Ready Constraints**: Generates safety constraints for AI workout generation
    - **Structured Workout Plans**: Returns complete workout with phases
    
    ### Use Cases
    - Personal training apps
    - Rehabilitation programs
    - Fitness platform backends
    - Research in adaptive training systems
    
    ---
    *Master's Thesis Project - Adaptive Athletic Risk Assessment System*
    """,
    version="1.0.0",
    contact={
        "name": "Thesis Project",
        "email": "research@example.com"
    },
    license_info={
        "name": "MIT License"
    }
)

# CORS middleware for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount user & session management routes
app.include_router(users_router)
# Mount Phase 3 program routes
app.include_router(programs_router)
# Mount training-plan recommendation routes
app.include_router(recommendations_router)
# Mount Phase 4 AI coach chat routes
app.include_router(chat_router)
# Mount Sprint 4 insights (readiness + progression) routes
app.include_router(insights_router)
# Mount WeChat / local auth for mini program
app.include_router(auth_router)
# Mount speech-to-text (Whisper fallback for mini program voice)
app.include_router(stt_router)
# Mount V-Socrate video exercise analysis (lazy-loads optional GPU dependencies)
app.include_router(video_analysis_router)

# Initialize the Risk Assessment Engine at startup
try:
    # USE_REAL_LLM 环境变量控制是否调用真实 LLM
    use_llm_env = os.getenv("USE_REAL_LLM", "false").lower()
    USE_REAL_LLM = use_llm_env in ("1", "true", "yes")

    risk_engine = RiskAssessmentEngine(db_path='exercise_db.json')
    plan_generator = PlanGeneratorMock(risk_engine, use_llm=USE_REAL_LLM)
    program_generator = ProgramGeneratorService(risk_engine, use_llm=USE_REAL_LLM)
    ENGINE_LOADED = True
except Exception as e:
    print(f"⚠️ Warning: Could not load Risk Engine: {e}")
    risk_engine = None
    
    plan_generator = None
    ENGINE_LOADED = False
    USE_REAL_LLM = False


# ---------------------------------------------------------------------------
# 三 Agent 管线的 LLM 装配
#
# 一个 client（一个 key、一个 provider）切成三个职责不同的入口：
#   StateRiskAgent  ← bridges.state_fn    病历文本 → 追加型约束
#   PlanAgent       ← bridges.plan_fn     候选集内选动作
#   SafetyEvalAgent ← bridges.safety_fn   独立审查 → 枚举违规码
#
# 装配失败时 AGENT_BRIDGES 保持 None，管线自动退回全规则后端 —— 也就是说
# key 没配、网络不通、provider 挂掉都不影响 /generate_plan 可用，只是
# generator 字段会显示 deterministic。
# ---------------------------------------------------------------------------
AGENT_BRIDGES = None
if USE_REAL_LLM:
    try:
        from llm_client import LLMClient

        AGENT_BRIDGES = build_bridges(LLMClient())
        _versions = ", ".join(
            f"{k}={v}" for k, v in AGENT_BRIDGES.versions().items()
        )
        print(f"🧩 Agent LLM bridges ready ({LLMClient.__module__}): {_versions}")
    except Exception as e:  # noqa: BLE001
        AGENT_BRIDGES = None
        print(
            "⚠️  Agent LLM bridges unavailable — agents fall back to rule-only "
            f"backends: {e}"
        )
else:
    # 常见误配：key 填了但忘了打开开关。这里主动提示，省得对着
    # generator=deterministic 排查半天。
    if os.getenv("OPENAI_API_KEY") or os.getenv("MINIMAX_API_KEY"):
        print(
            "ℹ️  Detected an API key but USE_REAL_LLM=false — the three agents "
            "are running on rule-only backends. Set USE_REAL_LLM=true in .env "
            "to switch them to the LLM backends."
        )


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/", tags=["Root"])
async def root():
    """
    Root endpoint - API welcome message.
    """
    return {
        "message": "🏋️ Welcome to the Adaptive Athletic Risk Assessment API",
        "version": "1.0.0",
        "documentation": "/docs",
        "health_check": "/health"
    }


@app.get("/health", response_model=HealthCheckResponse, tags=["Health"])
async def health_check():
    """
    Health check endpoint for monitoring and load balancers.
    
    Returns the current status of the API and whether the exercise
    database is properly loaded.
    """
    return HealthCheckResponse(
        status="healthy" if ENGINE_LOADED else "degraded",
        version="1.0.0",
        exercise_db_loaded=ENGINE_LOADED,
        exercise_count=len(risk_engine.exercise_db) if risk_engine else 0,
        timestamp=datetime.now().isoformat()
    )


@app.post(
    "/generate_plan",
    response_model=GeneratePlanResponse,
    responses={
        200: {"description": "Successfully generated workout plan"},
        400: {"model": ErrorResponse, "description": "Invalid input data"},
        500: {"model": ErrorResponse, "description": "Internal server error"}
    },
    tags=["Workout Plans"],
    summary="Generate a personalized workout plan"
)
async def generate_plan(
    request: GeneratePlanRequest,
    save_to_db: bool = Query(
        False,
        description="Persist the generated plan to the database for history tracking",
    ),
    use_latest_feedback: bool = Query(
        False,
        description=(
            "Auto-load the most recent training session feedback from the database "
            "as dynamic constraints. Requires the user to be registered and have at "
            "least one logged session. Overrides any feedback in the request body."
        ),
    ),
    use_history: bool = Query(
        False,
        description=(
            "[Phase 2] Load the user's full training history from the database, "
            "analyse RPE trends / pain patterns / deload needs, and inject the "
            "resulting coaching context into the LLM prompt. Requires USE_REAL_LLM=true "
            "to affect the LLM output; safe to pass with Mock mode too (context is "
            "computed and returned in safety_notes for transparency). "
            "history_window controls how many sessions to analyse."
        ),
    ),
    history_window: int = Query(
        10,
        ge=1,
        le=30,
        description="Number of recent sessions to include in the history analysis (default 10)",
    ),
    engine: str = Query(
        "agents",
        description=(
            "计划生成引擎。agents（默认）= 三 Agent 管线，状态分析/计划生成/安全评估"
            "彼此独立，并对候选动作施加风险条件约束解码；legacy = 旧的单步 mock 生成器，"
            "仅用于对照实验与回退。"
        ),
    ),
    db: Session = Depends(get_db),
):
    """
    Generate a personalized, constraint-respecting workout plan.

    This endpoint performs the following steps:
    1. **Static Risk Analysis**: Analyzes user's medical history to identify forbidden exercises
    2. **Dynamic Feedback Analysis**: Processes recent workout feedback for additional constraints
    3. **[Phase 2] History Analysis** *(when `use_history=true`)*: Analyses the user's recent
       training history (RPE trends, pain recurrence, deload signals) and injects a structured
       coaching context into the LLM prompt.
    4. **Plan Generation**: Creates a structured workout plan respecting all constraints

    **Query parameters:**
    - `save_to_db=true` — save the generated plan to the database.
    - `use_latest_feedback=true` — auto-load the most recent session's feedback as constraints.
    - `use_history=true` — enable Phase 2 history-aware coaching context injection.
    - `history_window=N` — how many past sessions to analyse (default 10, max 30).
    """

    if not ENGINE_LOADED:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Risk Assessment Engine not loaded. Please check server logs."
        )

    try:
        user_profile_dict = request.user_profile.model_dump()
        feedback_dict = request.feedback.model_dump() if request.feedback else None
        user_id = request.user_profile.user_id

        # ── Auto-load latest feedback from DB ──────────────────────────────
        if use_latest_feedback:
            latest_session = crud.get_latest_session(db, user_id)
            if latest_session:
                feedback_dict = crud.session_to_feedback_dict(latest_session)
                print(
                    f"   📂 Auto-loaded feedback from session "
                    f"'{latest_session.session_id}' (RPE={latest_session.rpe})"
                )
            else:
                print(
                    f"   ℹ️  use_latest_feedback=true but no sessions found for "
                    f"user '{user_id}'. Proceeding without feedback."
                )

        # ── Phase 2: Build training history context ─────────────────────────
        history_context = ""
        history_summary = None
        if use_history:
            recent_sessions = crud.get_recent_sessions(db, user_id, n=history_window)
            if recent_sessions:
                session_dicts = [crud.session_to_feedback_dict(s) for s in recent_sessions]
                history_summary = analyze_history(session_dicts, user_profile_dict)
                history_context = history_summary.llm_context_text
                print(
                    f"   📊 History analysis: {history_summary.session_count} sessions | "
                    f"avg RPE={history_summary.avg_rpe} | "
                    f"deload={history_summary.deload_recommended} | "
                    f"direction={history_summary.intensity_direction}"
                )
            else:
                print(
                    f"   ℹ️  use_history=true but no sessions found for user '{user_id}'."
                )

        # Run static risk analysis
        forbidden_exercises, safe_exercises = risk_engine.analyze_static_risk(user_profile_dict)

        # Run dynamic feedback analysis if feedback provided
        constraints: List[RiskConstraint] = []
        if feedback_dict:
            constraints = risk_engine.analyze_dynamic_feedback(feedback_dict)

        # ── 生成计划：默认走三 Agent 管线，legacy 走旧单步生成器 ──────────
        agent_result = None
        if engine == "agents":
            # 三个 Agent 的 LLM 后端在这里注入；AGENT_BRIDGES 为 None 时
            # 不传参数，三个 Agent 都用各自的规则后端。
            agent_kwargs: Dict[str, Any] = {}
            if AGENT_BRIDGES is not None:
                agent_kwargs = {
                    "state_agent": StateRiskAgent(
                        risk_engine.exercise_db,
                        llm_enhance_fn=AGENT_BRIDGES.state_fn,
                    ),
                    "plan_agent": PlanAgent(llm_plan_fn=AGENT_BRIDGES.plan_fn),
                    "safety_agent": SafetyEvalAgent(
                        llm_judge_fn=AGENT_BRIDGES.safety_fn
                    ),
                }
            agent_result = run_agent_pipeline(
                exercise_db=risk_engine.exercise_db,
                user_profile=user_profile_dict,
                feedback=feedback_dict,
                workout_type=request.workout_type,
                query=request.query,
                **agent_kwargs,
            )
            plan_export = render_plan_draft(
                agent_result.draft,
                build_exercise_index(risk_engine.exercise_db),
                agent_result.profile,
                agent_result.report,
                fitness_level=str(user_profile_dict.get("fitness_level") or "beginner"),
                workout_type=request.workout_type,
            )
            print(
                f"   \U0001f9e9 Agents pipeline: {agent_result.draft.slot_count()} slots | "
                f"allowed={len(agent_result.profile.allowed_ids)} "
                f"forbidden={len(agent_result.profile.forbidden_reasons)} | "
                f"safety_passed={agent_result.report.passed} | "
                f"generator={plan_export['generator_version']} | "
                f"llm=[state={agent_result.profile.llm_status or 'skipped'} "
                f"plan={agent_result.draft.generator} "
                f"safety={agent_result.report.llm_verdict}]"
            )
        else:
            # Generate the workout plan (history_context passed through to LLM)
            workout_plan = plan_generator.generate_plan(
                user_profile=user_profile_dict,
                feedback_input=feedback_dict,
                workout_type=request.workout_type,
                history_context=history_context,
            )

            # Export plan as JSON (pass actual generator version)
            plan_export = plan_generator.export_plan_as_json(
                workout_plan,
                generator_version=plan_generator.generator_version,
            )

        # Augment safety_notes with history coaching summary (Phase 2)
        if history_summary:
            history_notes = []
            if history_summary.deload_recommended:
                history_notes.append(
                    f"🔴 减量建议：{history_summary.deload_reason}"
                )
            elif history_summary.intensity_direction == "increase":
                history_notes.append("📈 历史分析建议：可渐进增加训练强度")
            else:
                history_notes.append(
                    f"📊 历史分析（最近 {history_summary.session_count} 次）："
                    f"平均 RPE {history_summary.avg_rpe}，"
                    f"趋势 {history_summary.rpe_trend}，建议维持当前强度"
                )
            if history_summary.recurring_pain_locations:
                locs = "、".join(history_summary.recurring_pain_locations)
                history_notes.append(f"⚠️ 反复疼痛部位（需重点关注）：{locs}")
            plan_export["safety_notes"] = history_notes + plan_export.get("safety_notes", [])

        # Optionally persist the plan to the database
        program_id: Optional[str] = None
        if save_to_db:
            crud.save_generated_plan(
                db,
                plan_export,
                generator_version=plan_export["generator_version"],
            )
            print(f"   💾 Plan '{plan_export['plan_id']}' saved to database.")

            if program_generator:
                program_id = sync_plan_after_generation(
                    db,
                    plan_export,
                    user_profile_dict,
                    program_generator,
                    plan_export["generator_version"],
                    history_summary=history_summary,
                )
                print(
                    f"   📅 Profile synced and program '{program_id}' created "
                    f"from generated plan."
                )
            else:
                crud.upsert_user(db, user_profile_dict)
                print("   👤 User profile synced (program generator unavailable).")

        # Build the response
        response = GeneratePlanResponse(
            plan_id=plan_export["plan_id"],
            user_id=plan_export["user_id"],
            date=plan_export["date"],
            workout_type=plan_export["workout_type"],
            estimated_duration_minutes=plan_export["estimated_duration_minutes"],
            phases=WorkoutPhases(
                warm_up=[ExerciseResponse(**ex) for ex in plan_export["phases"]["warm_up"]],
                activation=[ExerciseResponse(**ex) for ex in plan_export["phases"]["activation"]],
                main_lifts=[ExerciseResponse(**ex) for ex in plan_export["phases"]["main_lifts"]],
                accessories=[ExerciseResponse(**ex) for ex in plan_export["phases"]["accessories"]],
                cool_down=[ExerciseResponse(**ex) for ex in plan_export["phases"]["cool_down"]]
            ),
            safety_notes=plan_export["safety_notes"],
            risk_analysis=RiskAnalysisResponse(
                forbidden_exercises=[
                    ForbiddenExerciseResponse(
                        name=ex.name,
                        reason=ex.reason,
                        substitution=ex.substitution
                    ) for ex in forbidden_exercises
                ],
                safe_exercise_count=len(safe_exercises),
                constraints=[c.description for c in constraints]
            ),
            generated_at=plan_export["generated_at"],
            generator_version=plan_export["generator_version"],
            program_id=program_id,
            safety=(
                SafetySummaryResponse(
                    passed=agent_result.report.passed,
                    checked_slots=agent_result.report.checked_slots,
                    masked_count=agent_result.report.masked_count,
                    adversarial_probes=agent_result.report.adversarial_probes,
                    adversarial_blocked=agent_result.report.adversarial_blocked,
                    profile_hash=agent_result.profile.profile_hash,
                    grammar_version=agent_result.draft.grammar_version,
                    rejected_ids=list(agent_result.draft.rejected_ids),
                    violations=[
                        SafetyViolationResponse(**v.to_dict())
                        for v in agent_result.report.violations
                    ],
                    llm_verdict=agent_result.report.llm_verdict,
                    llm_disagreed=agent_result.report.llm_disagreed,
                    llm_rationale=agent_result.report.llm_rationale,
                    llm_prompt_version=agent_result.report.llm_prompt_version,
                    state_llm_status=agent_result.profile.llm_status or "skipped",
                    avoid_patterns=list(agent_result.profile.avoid_patterns),
                    session_cap_minutes=agent_result.profile.session_cap_minutes,
                    progression_note=agent_result.profile.progression_note,
                    capacity_note=agent_result.profile.capacity_note,
                    adjusted_slots=agent_result.draft.adjusted_slots,
                )
                if agent_result
                else None
            ),
            audit=agent_result.audit.entries if agent_result else None,
        )

        return response

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating workout plan: {str(e)}"
        )


@app.get("/exercises", tags=["Exercises"])
async def list_exercises(
    request: Request,
    muscle_group: Optional[str] = None,
    exercise_type: Optional[str] = None,
    max_risk_level: Optional[int] = None
):
    """
    List all exercises in the database with optional filtering.
    
    **Query Parameters:**
    - `muscle_group`: Filter by target muscle (e.g., "Quadriceps", "Pectorals")
    - `exercise_type`: Filter by type — Compound / Isolation / Isometric
      （训练动作）或 Warmup / Stretch / Activation（热身、拉伸、激活）
    - `max_risk_level`: Only return exercises with risk_level <= this value (1-5)
    """
    
    if not ENGINE_LOADED:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Exercise database not loaded."
        )
    
    exercises = risk_engine.exercise_db
    
    # Apply filters
    if muscle_group:
        exercises = [ex for ex in exercises if muscle_group.lower() in ex.get('target_muscle', '').lower()]
    
    if exercise_type:
        exercises = [ex for ex in exercises if ex.get('type', '').lower() == exercise_type.lower()]
    
    if max_risk_level:
        exercises = [ex for ex in exercises if ex.get('risk_level', 5) <= max_risk_level]

    base = str(request.base_url).rstrip("/") if request else ""
    enriched = []
    for ex in exercises:
        item = dict(ex)
        g = guide_for(ex["name"])
        if base:
            g = _proxy_guide_urls(g, base)
        item["has_guide"] = g["has_guide"]
        item["image_url"] = g.get("image_url")
        item["animation_frames"] = g.get("animation_frames", [])
        enriched.append(item)

    return {
        "count": len(enriched),
        "exercises": enriched
    }


def _proxy_guide_urls(guide: dict, base_url: str) -> dict:
    """将 GitHub 图源替换为本地代理 URL，避免浏览器直连失败。"""
    name = guide["name"]
    src_frames = animation_frames(name)
    if not src_frames:
        return guide
    encoded = quote(name, safe="")
    out = {**guide}
    out["image_url"] = f"{base_url}/exercises/media/{encoded}/0"
    out["animation_frames"] = [
        f"{base_url}/exercises/media/{encoded}/{i}"
        for i in range(min(2, len(src_frames)))
    ]
    return out


@app.get("/exercises/media/{name}/{frame}", tags=["Exercises"])
async def exercise_media(name: str, frame: int):
    """代理动作示意图/动图帧（缓存 GitHub 图源）。"""
    decoded = unquote(name)
    frames = animation_frames(decoded)
    if not frames:
        raise HTTPException(status_code=404, detail="Exercise not found")
    idx = frame if 0 <= frame < len(frames) else 0
    urls_to_try = [frames[idx]]
    if idx != 0:
        urls_to_try.append(frames[0])
    last_exc: Optional[Exception] = None
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            for url in urls_to_try:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return Response(
                        content=resp.content,
                        media_type=resp.headers.get("content-type", "image/jpeg"),
                        headers={"Cache-Control": "public, max-age=86400"},
                    )
                except Exception as exc:
                    last_exc = exc
                    continue
    except Exception as exc:
        last_exc = exc
    raise HTTPException(
        status_code=502,
        detail=f"Failed to fetch exercise media: {last_exc}",
    ) from last_exc


@app.get("/exercises/guide-meta", tags=["Exercises"])
async def exercise_guide_meta(request: Request, name: Optional[str] = None):
    """
    动作教程元数据：示意图、起止位动图帧、中文技术要领。

    - 不传 `name`：返回全部已录入教程的动作字典
    - 传 `name`：返回单个动作的教程（未录入则 has_guide=false）
    """
    if name:
        return _proxy_guide_urls(guide_for(name), str(request.base_url).rstrip("/"))
    guides = all_guides()
    base = str(request.base_url).rstrip("/")
    return {
        "count": len(guides),
        "guides": {k: _proxy_guide_urls(v, base) for k, v in guides.items()},
    }


@app.post("/analyze_risk", tags=["Risk Analysis"])
async def analyze_risk_only(user_profile: UserProfile):
    """
    Perform risk analysis without generating a workout plan.
    
    Useful for:
    - Previewing which exercises will be restricted
    - Understanding the impact of a user's injury profile
    - Debugging and testing risk assessment logic
    """
    
    if not ENGINE_LOADED:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Risk Assessment Engine not loaded."
        )
    
    user_profile_dict = user_profile.model_dump()
    forbidden_exercises, safe_exercises = risk_engine.analyze_static_risk(user_profile_dict)
    
    return {
        "user_id": user_profile.user_id,
        "analysis_timestamp": datetime.now().isoformat(),
        "summary": {
            "total_exercises": len(risk_engine.exercise_db),
            "forbidden_count": len(forbidden_exercises),
            "safe_count": len(safe_exercises)
        },
        "forbidden_exercises": [
            {
                "name": ex.name,
                "reason": ex.reason,
                "risk_level": ex.risk_level,
                "involved_joints": ex.involved_joints,
                "substitution": ex.substitution
            } for ex in forbidden_exercises
        ],
        "safe_exercises": safe_exercises
    }


# =============================================================================
# Startup/Shutdown Events
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Log startup information and run lightweight schema migrations."""
    from database import DATABASE_URL
    from sqlalchemy import text

    print("\n" + "="*60)
    print("🚀 Adaptive Athletic Risk Assessment API Starting...")
    print("="*60)
    if ENGINE_LOADED:
        print(f"✅ Risk Engine loaded with {len(risk_engine.exercise_db)} exercises")
    else:
        print("⚠️ Risk Engine failed to load - running in degraded mode")
    print(f"🗄️  Database: {DATABASE_URL}")
    print("📚 API Documentation available at: http://localhost:8000/docs")
    print("="*60 + "\n")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    print("\n🛑 API shutting down...")


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("""
╔══════════════════════════════════════════════════════════════════╗
║        🏋️ ADAPTIVE ATHLETIC RISK ASSESSMENT API                  ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  To run the server, use one of the following commands:           ║
║                                                                  ║
║  Development mode (with auto-reload):                            ║
║    uvicorn main:app --reload --host 0.0.0.0 --port 8000          ║
║                                                                  ║
║  Production mode:                                                ║
║    uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4       ║
║                                                                  ║
║  Or simply run this file:                                        ║
║    python main.py                                                ║
║                                                                  ║
║  API Documentation:                                              ║
║    Swagger UI: http://localhost:8000/docs                        ║
║    ReDoc:      http://localhost:8000/redoc                       ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
