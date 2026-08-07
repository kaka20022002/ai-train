"""
User & Session Management Router
=================================

All endpoints that deal with persisted user profiles and training sessions
live here so main.py stays focused on plan generation.

Prefix: /users   (mounted in main.py)

Endpoints
---------
Users
  POST   /users                            — register a new user profile
  GET    /users/{user_id}                  — retrieve user profile
  PUT    /users/{user_id}                  — update user profile (partial)

Training Sessions
  POST   /users/{user_id}/sessions         — log a completed workout session
  GET    /users/{user_id}/sessions         — list session history (paginated)
  GET    /users/{user_id}/sessions/latest  — get the most recent session

Plan History
  GET    /users/{user_id}/plans            — list generated plan history (paginated)
  GET    /users/{user_id}/plans/{plan_id}  — retrieve a single plan
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import crud
from database import get_db
from safety_sync import revalidate_user_training_data

router = APIRouter(tags=["Users & Sessions"])


# =============================================================================
# Pydantic Schemas (request / response)
# =============================================================================

class BasicInfoSchema(BaseModel):
    age: int = Field(..., ge=16, le=100)
    gender: str
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    bmi: Optional[float] = None


class MedicalHistoryItemSchema(BaseModel):
    location: str
    condition: str
    severity: str
    pain_trigger: Optional[str] = None
    onset_date: Optional[str] = None
    notes: Optional[str] = None


class CreateUserRequest(BaseModel):
    user_id: str = Field(..., description="Unique user identifier")
    basic_info: BasicInfoSchema
    fitness_level: str = Field("beginner", description="beginner / intermediate / advanced")
    fitness_goal: Optional[str] = None
    training_frequency: Optional[int] = Field(None, description="Sessions per week")
    available_equipment: Optional[List[str]] = Field(
        None, description="Equipment the user can train with (Sprint 3)"
    )
    medical_history: List[MedicalHistoryItemSchema] = Field(default_factory=list)

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "usr_001",
                "basic_info": {"age": 28, "gender": "male", "height_cm": 175, "weight_kg": 78},
                "fitness_level": "intermediate",
                "fitness_goal": "strength",
                "training_frequency": 4,
                "medical_history": [
                    {"location": "knee", "condition": "meniscus_tear", "severity": "high"}
                ],
            }
        }


class UpdateUserRequest(BaseModel):
    """All fields are optional — only provided fields will be updated."""
    basic_info: Optional[BasicInfoSchema] = None
    fitness_level: Optional[str] = None
    fitness_goal: Optional[str] = None
    training_frequency: Optional[int] = None
    available_equipment: Optional[List[str]] = None
    medical_history: Optional[List[MedicalHistoryItemSchema]] = None


class SafetyRevalidationResponse(BaseModel):
    programs_scanned: int = 0
    programs_updated: int = 0
    plans_scanned: int = 0
    plans_updated: int = 0
    exercises_replaced: int = 0
    replacements: List[Dict[str, str]] = Field(default_factory=list)


class UserResponse(BaseModel):
    user_id: str
    basic_info: Dict[str, Any]
    fitness_level: str
    fitness_goal: Optional[str]
    training_frequency: Optional[int]
    available_equipment: List[str] = Field(default_factory=list)
    medical_history: List[Dict[str, Any]]
    created_at: Optional[str]
    updated_at: Optional[str]
    safety_revalidation: Optional[SafetyRevalidationResponse] = None


class PainFeedbackSchema(BaseModel):
    has_pain: bool
    pain_location: Optional[str] = None
    pain_severity: Optional[int] = Field(None, ge=1, le=10)
    pain_type: Optional[str] = None
    trigger_exercise: Optional[str] = None
    trigger_moment: Optional[str] = None
    notes: Optional[str] = None


class FatigueFeedbackSchema(BaseModel):
    overall_fatigue: Optional[int] = Field(None, ge=1, le=10)
    muscle_soreness: Optional[List[str]] = None
    sleep_quality_last_night: Optional[int] = Field(None, ge=1, le=10)
    stress_level: Optional[int] = Field(None, ge=1, le=10)


class ExercisePerformance(BaseModel):
    """
    Actual performance data for a single exercise in a completed session.
    Used for progressive overload tracking (Phase 2).
    """
    name: str = Field(..., description="Exercise name (match exercise_db.json)")
    weight_kg: Optional[float] = Field(None, description="Weight used (kg)")
    sets_completed: Optional[int] = Field(None, description="Number of sets actually completed")
    reps_per_set: Optional[List[int]] = Field(
        None, description="Actual reps completed per set, e.g. [8, 8, 7, 6]"
    )
    notes: Optional[str] = Field(None, description="Free-text notes for this exercise")


class LogSessionRequest(BaseModel):
    """
    Log a completed training session.

    plan_id links this session to the plan that was executed.
    exercise_performance enables progressive overload tracking (Phase 2).
    All other fields mirror FeedbackInput from main.py.
    """
    session_id: Optional[str] = None
    plan_id: Optional[str] = Field(None, description="ID of the single-session plan that was executed")
    program_id: Optional[str] = Field(
        None,
        description="ID of the multi-week training program this session belongs to",
    )
    program_week: Optional[int] = Field(
        None,
        ge=1,
        description="Week number within the program (1-based). Required when program_id is set.",
    )
    date: Optional[str] = Field(None, description="YYYY-MM-DD, defaults to today")
    workout_type: Optional[str] = None
    duration_minutes: Optional[int] = None
    rpe: int = Field(..., ge=1, le=10, description="Rate of Perceived Exertion (1-10)")
    completion_rate: Optional[float] = Field(None, ge=0.0, le=1.0)
    pain_feedback: PainFeedbackSchema
    fatigue_feedback: Optional[FatigueFeedbackSchema] = None
    exercise_performance: Optional[List[ExercisePerformance]] = Field(
        None,
        description=(
            "Per-exercise performance data for progressive overload tracking. "
            "Provide after each session for best coaching recommendations."
        ),
    )
    notes: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "plan_id": "plan_12345",
                "date": "2026-05-07",
                "workout_type": "full_body",
                "duration_minutes": 55,
                "rpe": 7,
                "completion_rate": 0.9,
                "pain_feedback": {"has_pain": False},
                "fatigue_feedback": {
                    "overall_fatigue": 4,
                    "sleep_quality_last_night": 8,
                    "stress_level": 3,
                },
                "exercise_performance": [
                    {
                        "name": "Barbell Back Squat",
                        "weight_kg": 80,
                        "sets_completed": 4,
                        "reps_per_set": [8, 8, 7, 6],
                        "notes": "最后一组明显感到疲劳",
                    },
                    {
                        "name": "Romanian Deadlift",
                        "weight_kg": 70,
                        "sets_completed": 3,
                        "reps_per_set": [10, 10, 9],
                    },
                ],
            }
        }


class TrainingSessionResponse(BaseModel):
    session_id: str
    user_id: str
    plan_id: Optional[str]
    program_id: Optional[str]
    program_week: Optional[int]
    date: str
    workout_type: Optional[str]
    duration_minutes: Optional[int]
    rpe: int
    completion_rate: Optional[float]
    pain_feedback: Dict[str, Any]
    fatigue_feedback: Optional[Dict[str, Any]]
    exercise_performance: Optional[List[Dict[str, Any]]]
    notes: Optional[str]
    created_at: Optional[str]


class SessionListResponse(BaseModel):
    user_id: str
    total: int
    limit: int
    offset: int
    sessions: List[TrainingSessionResponse]


class PlanSummary(BaseModel):
    plan_id: str
    workout_type: str
    generator_version: str
    estimated_duration_minutes: Optional[int]
    generated_at: Optional[str]


class PlanListResponse(BaseModel):
    user_id: str
    total: int
    limit: int
    offset: int
    plans: List[PlanSummary]


class PlanDetailResponse(BaseModel):
    plan_id: str
    user_id: str
    workout_type: str
    generator_version: str
    plan_data: Dict[str, Any]
    generated_at: Optional[str]


# =============================================================================
# Helpers
# =============================================================================

def _user_response(user, revalidation: Optional[SafetyRevalidationResponse] = None) -> UserResponse:
    return UserResponse(
        user_id=user.user_id,
        basic_info=user.basic_info or {},
        fitness_level=user.fitness_level or "beginner",
        fitness_goal=user.fitness_goal,
        training_frequency=user.training_frequency,
        available_equipment=getattr(user, "available_equipment", None) or [],
        medical_history=user.medical_history or [],
        created_at=user.created_at.isoformat() if user.created_at else None,
        updated_at=user.updated_at.isoformat() if user.updated_at else None,
        safety_revalidation=revalidation,
    )


def _session_response(sess) -> TrainingSessionResponse:
    return TrainingSessionResponse(
        session_id=sess.session_id,
        user_id=sess.user_id,
        plan_id=sess.plan_id,
        program_id=getattr(sess, "program_id", None),
        program_week=getattr(sess, "program_week", None),
        date=sess.date,
        workout_type=sess.workout_type,
        duration_minutes=sess.duration_minutes,
        rpe=sess.rpe,
        completion_rate=sess.completion_rate,
        pain_feedback=sess.pain_feedback or {},
        fatigue_feedback=sess.fatigue_feedback,
        exercise_performance=sess.exercise_performance,
        notes=sess.notes,
        created_at=sess.created_at.isoformat() if sess.created_at else None,
    )


# =============================================================================
# User Endpoints
# =============================================================================

@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user profile",
)
def create_user(request: CreateUserRequest, db: Session = Depends(get_db)):
    """
    Persist a user profile to the database.

    Once registered, the user can reference their profile by `user_id` alone
    for subsequent plan generation and session logging.
    """
    try:
        user = crud.create_user(db, request.model_dump())
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"User '{request.user_id}' already exists. Use PUT /users/{request.user_id} to update.",
        )
    return _user_response(user)


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Get user profile",
)
def get_user(user_id: str, db: Session = Depends(get_db)):
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found.",
        )
    return _user_response(user)


@router.put(
    "/users/{user_id}",
    response_model=UserResponse,
    summary="Update user profile (partial)",
)
def update_user(user_id: str, request: UpdateUserRequest, db: Session = Depends(get_db)):
    """
    Partial update: only the fields you provide will be changed.
    The medical_history list is replaced entirely if provided.

    When medical_history changes, active/paused programs and recent plans are
    automatically re-scanned and forbidden exercises are replaced.
    """
    updates = {k: v for k, v in request.model_dump().items() if v is not None}
    user = crud.update_user(db, user_id, updates)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found.",
        )

    revalidation: Optional[SafetyRevalidationResponse] = None
    if "medical_history" in updates:
        profile = crud.user_to_profile_dict(user)
        report = revalidate_user_training_data(db, user_id, profile)
        revalidation = SafetyRevalidationResponse(**report.to_dict())

    return _user_response(user, revalidation)


# =============================================================================
# Training Session Endpoints
# =============================================================================

@router.post(
    "/users/{user_id}/sessions",
    response_model=TrainingSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log a completed training session",
)
def log_session(
    user_id: str,
    request: LogSessionRequest,
    db: Session = Depends(get_db),
):
    """
    Record the results and feedback of a completed workout.

    - `plan_id`: link to the plan that was executed (optional but recommended)
    - `rpe`: Rate of Perceived Exertion — drives next-session intensity adjustment
    - `pain_feedback`: any pain reported during the session
    - `fatigue_feedback`: sleep quality, soreness, stress levels

    The stored session will be loaded automatically as context when the user
    next calls `POST /generate_plan` with `use_latest_feedback=true`.
    """
    # Ensure user exists
    if not crud.get_user(db, user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found. Register first via POST /users.",
        )

    # If plan_id provided, verify it belongs to this user
    if request.plan_id:
        plan = crud.get_generated_plan(db, request.plan_id)
        if plan and plan.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Plan '{request.plan_id}' does not belong to user '{user_id}'.",
            )

    data = request.model_dump()
    data["user_id"] = user_id  # path param is authoritative

    sess = crud.create_training_session(db, data)
    return _session_response(sess)


@router.get(
    "/users/{user_id}/sessions",
    response_model=SessionListResponse,
    summary="List training session history",
)
def list_sessions(
    user_id: str,
    limit: int = Query(20, ge=1, le=100, description="Results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    if not crud.get_user(db, user_id):
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")

    sessions = crud.get_training_sessions(db, user_id, limit=limit, offset=offset)
    total = crud.count_training_sessions(db, user_id)

    return SessionListResponse(
        user_id=user_id,
        total=total,
        limit=limit,
        offset=offset,
        sessions=[_session_response(s) for s in sessions],
    )


@router.get(
    "/users/{user_id}/sessions/latest",
    response_model=TrainingSessionResponse,
    summary="Get the most recent training session",
)
def get_latest_session(user_id: str, db: Session = Depends(get_db)):
    """
    Returns the latest completed session.
    Useful for quickly loading feedback before generating the next plan.
    """
    if not crud.get_user(db, user_id):
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")

    sess = crud.get_latest_session(db, user_id)
    if not sess:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No training sessions found for user '{user_id}'.",
        )
    return _session_response(sess)


# =============================================================================
# Plan History Endpoints
# =============================================================================

@router.get(
    "/users/{user_id}/plans",
    response_model=PlanListResponse,
    summary="List generated plan history",
)
def list_plans(
    user_id: str,
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    if not crud.get_user(db, user_id):
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")

    plans = crud.get_user_plans(db, user_id, limit=limit, offset=offset)
    total = crud.count_user_plans(db, user_id)

    summaries = [
        PlanSummary(
            plan_id=p.plan_id,
            workout_type=p.workout_type,
            generator_version=p.generator_version or "unknown",
            estimated_duration_minutes=p.plan_data.get("estimated_duration_minutes"),
            generated_at=p.generated_at.isoformat() if p.generated_at else None,
        )
        for p in plans
    ]

    return PlanListResponse(
        user_id=user_id,
        total=total,
        limit=limit,
        offset=offset,
        plans=summaries,
    )


@router.get(
    "/users/{user_id}/plans/{plan_id}",
    response_model=PlanDetailResponse,
    summary="Retrieve a single generated plan",
)
def get_plan(user_id: str, plan_id: str, db: Session = Depends(get_db)):
    plan = crud.get_generated_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found.")
    if plan.user_id != user_id:
        raise HTTPException(status_code=403, detail="Plan does not belong to this user.")

    return PlanDetailResponse(
        plan_id=plan.plan_id,
        user_id=plan.user_id,
        workout_type=plan.workout_type,
        generator_version=plan.generator_version or "unknown",
        plan_data=plan.plan_data,
        generated_at=plan.generated_at.isoformat() if plan.generated_at else None,
    )
