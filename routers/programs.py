"""
Training Program Router — Phase 3
===================================

All endpoints for creating, viewing, and adaptively advancing
multi-week training programs (mesocycles).

Prefix: /programs  (mounted in main.py)

Endpoints
---------
  POST  /programs/generate                           — generate a new mesocycle
  GET   /programs/{program_id}                       — full program detail
  GET   /users/{user_id}/programs                    — list user's programs
  GET   /programs/{program_id}/weeks/{week_number}   — single week detail
  GET   /programs/{program_id}/next-session          — what to do next
  POST  /programs/{program_id}/advance               — advance to next week (adaptive)
  PATCH /programs/{program_id}/status                — pause / resume / complete
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from exercise_meta import sanitize_program_weeks
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import crud
from database import get_db
from history_analyzer import analyze_history
from program_generator import ProgramGeneratorService
from risk_engine import RiskAssessmentEngine

router = APIRouter(tags=["Training Programs"])

# ---------------------------------------------------------------------------
# Initialise risk engine + program generator (shared, loaded once per process)
# ---------------------------------------------------------------------------
_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "exercise_db.json")

try:
    _risk_engine = RiskAssessmentEngine(db_path=_DB_PATH)
    USE_REAL_LLM = os.getenv("USE_REAL_LLM", "false").lower() in ("1", "true", "yes")
    _program_svc = ProgramGeneratorService(_risk_engine, use_llm=USE_REAL_LLM)
    _ENGINE_READY = True
except Exception as _e:
    print(f"⚠️  programs router: failed to load risk engine — {_e}")
    _risk_engine = None
    _program_svc = None
    _ENGINE_READY = False


def _require_engine():
    if not _ENGINE_READY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Risk engine not available. Check server logs.",
        )


# =============================================================================
# Pydantic schemas
# =============================================================================

class MedicalHistoryItemSchema(BaseModel):
    location: str
    condition: str
    severity: str
    pain_trigger: Optional[str] = None
    onset_date: Optional[str] = None
    notes: Optional[str] = None


class UserProfileSchema(BaseModel):
    user_id: str
    basic_info: Dict[str, Any]
    fitness_level: str = "beginner"
    fitness_goal: Optional[str] = None
    training_frequency: Optional[int] = None
    available_equipment: Optional[List[str]] = None
    medical_history: List[MedicalHistoryItemSchema] = Field(default_factory=list)


class GenerateProgramRequest(BaseModel):
    user_profile: UserProfileSchema
    goal: str = Field(
        "general_fitness",
        description="strength | hypertrophy | general_fitness",
    )
    total_weeks: int = Field(4, ge=2, le=12, description="Program length in weeks")
    sessions_per_week: int = Field(3, ge=2, le=6, description="Training days per week")
    split_type: str = Field(
        "auto",
        description=(
            "auto (recommended) | full_body | upper_lower | push_pull_legs. "
            "'auto' selects the best split based on goal and sessions_per_week."
        ),
    )
    use_history: bool = Field(
        False,
        description="Load training history from DB to inform the program design.",
    )
    history_window: int = Field(10, ge=1, le=30)

    class Config:
        json_schema_extra = {
            "example": {
                "user_profile": {
                    "user_id": "usr_001",
                    "basic_info": {"age": 28, "gender": "male"},
                    "fitness_level": "intermediate",
                    "medical_history": [
                        {"location": "knee", "condition": "meniscus_tear", "severity": "high"}
                    ],
                },
                "goal": "strength",
                "total_weeks": 4,
                "sessions_per_week": 4,
                "split_type": "upper_lower",
                "use_history": True,
            }
        }


class KeyExerciseResponse(BaseModel):
    name: str
    sets: int
    reps: str
    rest_seconds: int
    intensity_note: str
    target_muscle: Optional[str] = None


class PlanExerciseSchema(BaseModel):
    name: str
    sets: int
    reps: str
    rest_seconds: int
    notes: Optional[str] = None
    target_muscle: Optional[str] = None


class WorkoutPhasesSchema(BaseModel):
    warm_up: List[PlanExerciseSchema] = Field(default_factory=list)
    activation: List[PlanExerciseSchema] = Field(default_factory=list)
    main_lifts: List[PlanExerciseSchema] = Field(default_factory=list)
    accessories: List[PlanExerciseSchema] = Field(default_factory=list)
    cool_down: List[PlanExerciseSchema] = Field(default_factory=list)


class SessionTemplateResponse(BaseModel):
    session_number: int
    workout_type: str
    label: str
    estimated_duration_minutes: int
    key_exercises: List[KeyExerciseResponse]
    notes: Optional[str] = None
    phases: Optional[WorkoutPhasesSchema] = None
    source_plan_id: Optional[str] = None


class WeekResponse(BaseModel):
    week_number: int
    week_type: str
    actual_week_type: Optional[str] = None
    status: Optional[str] = None
    label: str
    volume_modifier: float
    intensity_note: str
    sessions: List[SessionTemplateResponse]
    adaptation_notes: List[str] = Field(default_factory=list)
    completed_sessions: Optional[int] = None
    actual_avg_rpe: Optional[float] = None


class ProgramSummaryResponse(BaseModel):
    program_id: str
    user_id: str
    name: str
    status: str
    goal: str
    split_type: str
    total_weeks: int
    current_week: int
    sessions_per_week: int
    periodization_model: Optional[str] = None
    generator_version: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ProgramDetailResponse(ProgramSummaryResponse):
    description: Optional[str] = None
    forbidden_exercise_count: Optional[int] = None
    safe_exercise_count: Optional[int] = None
    weeks: List[WeekResponse] = Field(default_factory=list)


class ProgramListResponse(BaseModel):
    user_id: str
    total: int
    limit: int
    offset: int
    programs: List[ProgramSummaryResponse]


class AdvanceWeekRequest(BaseModel):
    """
    Trigger week advancement.

    If session_ids is empty, the system auto-loads all training sessions
    linked to this program and the current week from the database.
    """
    session_ids: List[str] = Field(
        default_factory=list,
        description=(
            "IDs of sessions completed this week. "
            "Leave empty to auto-load from DB (requires sessions logged with program_id)."
        ),
    )

    class Config:
        json_schema_extra = {
            "example": {"session_ids": ["sess_abc123", "sess_def456"]}
        }


class AdvanceWeekResponse(BaseModel):
    program_id: str
    adaptation_report: Dict[str, Any]
    next_week: Optional[WeekResponse] = None


class NextSessionResponse(BaseModel):
    program_id: str
    current_week: int
    sessions_completed_this_week: int
    sessions_planned_this_week: int
    next_session: Optional[SessionTemplateResponse] = None
    message: str


class StatusPatchRequest(BaseModel):
    status: str = Field(..., description="active | paused | completed")


# =============================================================================
# Helpers
# =============================================================================

def _phases_to_schema(phases: Optional[Dict[str, Any]]) -> Optional[WorkoutPhasesSchema]:
    if not phases:
        return None
    return WorkoutPhasesSchema(
        warm_up=[PlanExerciseSchema(**ex) for ex in phases.get("warm_up", [])],
        activation=[PlanExerciseSchema(**ex) for ex in phases.get("activation", [])],
        main_lifts=[PlanExerciseSchema(**ex) for ex in phases.get("main_lifts", [])],
        accessories=[PlanExerciseSchema(**ex) for ex in phases.get("accessories", [])],
        cool_down=[PlanExerciseSchema(**ex) for ex in phases.get("cool_down", [])],
    )


def _session_to_response(s: Dict[str, Any]) -> SessionTemplateResponse:
    return SessionTemplateResponse(
        session_number=s.get("session_number", 1),
        workout_type=s.get("workout_type", "full_body"),
        label=s.get("label", "训练日"),
        estimated_duration_minutes=s.get("estimated_duration_minutes", 60),
        key_exercises=[
            KeyExerciseResponse(
                name=ex.get("name", ""),
                sets=ex.get("sets", 3),
                reps=str(ex.get("reps", "8-12")),
                rest_seconds=ex.get("rest_seconds", 90),
                intensity_note=ex.get("intensity_note", ex.get("notes", "")),
                target_muscle=ex.get("target_muscle"),
            )
            for ex in s.get("key_exercises", [])
        ],
        notes=s.get("notes"),
        phases=_phases_to_schema(s.get("phases")),
        source_plan_id=s.get("source_plan_id"),
    )


def _week_to_response(week: Dict[str, Any]) -> WeekResponse:
    sessions = [_session_to_response(s) for s in week.get("sessions", [])]
    return WeekResponse(
        week_number=week.get("week_number", 1),
        week_type=week.get("week_type", "base"),
        actual_week_type=week.get("actual_week_type"),
        status=week.get("status", "scheduled"),
        label=week.get("label", f"第{week.get('week_number',1)}周"),
        volume_modifier=week.get("volume_modifier", 1.0),
        intensity_note=week.get("intensity_note", ""),
        sessions=sessions,
        adaptation_notes=week.get("adaptation_notes", []),
        completed_sessions=week.get("completed_sessions"),
        actual_avg_rpe=week.get("actual_avg_rpe"),
    )


def _program_to_summary(p) -> ProgramSummaryResponse:
    return ProgramSummaryResponse(
        program_id=p.program_id,
        user_id=p.user_id,
        name=p.name,
        status=p.status,
        goal=p.goal,
        split_type=p.split_type,
        total_weeks=p.total_weeks,
        current_week=p.current_week,
        sessions_per_week=p.sessions_per_week,
        periodization_model=p.periodization_model,
        generator_version=p.generator_version,
        created_at=p.created_at.isoformat() if p.created_at else None,
        updated_at=p.updated_at.isoformat() if p.updated_at else None,
    )


def _program_to_detail(p) -> ProgramDetailResponse:
    data = p.program_data or {}
    sanitized_weeks = sanitize_program_weeks(data.get("weeks", []))
    weeks = [_week_to_response(w) for w in sanitized_weeks]
    return ProgramDetailResponse(
        program_id=p.program_id,
        user_id=p.user_id,
        name=p.name,
        status=p.status,
        goal=p.goal,
        split_type=p.split_type,
        total_weeks=p.total_weeks,
        current_week=p.current_week,
        sessions_per_week=p.sessions_per_week,
        periodization_model=p.periodization_model,
        generator_version=p.generator_version,
        created_at=p.created_at.isoformat() if p.created_at else None,
        updated_at=p.updated_at.isoformat() if p.updated_at else None,
        description=data.get("description"),
        forbidden_exercise_count=data.get("forbidden_exercise_count"),
        safe_exercise_count=data.get("safe_exercise_count"),
        weeks=weeks,
    )


# =============================================================================
# Endpoints
# =============================================================================

@router.post(
    "/programs/generate",
    response_model=ProgramDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a multi-week training program",
)
def generate_program(
    request: GenerateProgramRequest,
    db: Session = Depends(get_db),
):
    """
    Generate a personalised multi-week training program (mesocycle).

    The system:
    1. Runs static risk analysis to filter exercises for the user's injuries.
    2. Optionally loads training history to inform the program design.
    3. Generates a periodised program (Mock or LLM based on USE_REAL_LLM).
    4. Persists and returns the full program.

    The returned program contains week-by-week session templates.
    Use `POST /programs/{id}/advance` after each week to adapt the plan.
    """
    _require_engine()
    user_profile = request.user_profile.model_dump()

    # Optional history context
    history_summary = None
    if request.use_history:
        recent = crud.get_recent_sessions(db, request.user_profile.user_id, n=request.history_window)
        if recent:
            session_dicts = [crud.session_to_feedback_dict(s) for s in recent]
            history_summary = analyze_history(session_dicts, user_profile)
            print(
                f"   📊 History: {history_summary.session_count} sessions | "
                f"deload={history_summary.deload_recommended} | "
                f"direction={history_summary.intensity_direction}"
            )

    try:
        program_data = _program_svc.generate_program(
            user_profile=user_profile,
            goal=request.goal,
            total_weeks=request.total_weeks,
            sessions_per_week=request.sessions_per_week,
            split_type=request.split_type,
            history_summary=history_summary,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Program generation failed: {exc}",
        )

    crud.pause_active_programs(db, request.user_profile.user_id)
    program = crud.create_program(db, program_data)
    print(f"   💾 Program '{program.program_id}' saved ({program.total_weeks} weeks)")
    return _program_to_detail(program)


@router.get(
    "/programs/{program_id}",
    response_model=ProgramDetailResponse,
    summary="Get full program detail",
)
def get_program(program_id: str, db: Session = Depends(get_db)):
    p = crud.get_program(db, program_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Program '{program_id}' not found.")
    return _program_to_detail(p)


@router.get(
    "/users/{user_id}/programs",
    response_model=ProgramListResponse,
    summary="List user's training programs",
)
def list_programs(
    user_id: str,
    program_status: Optional[str] = Query(None, description="Filter: active | paused | completed"),
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    programs = crud.get_user_programs(db, user_id, status=program_status, limit=limit, offset=offset)
    total = crud.count_user_programs(db, user_id, status=program_status)
    return ProgramListResponse(
        user_id=user_id,
        total=total,
        limit=limit,
        offset=offset,
        programs=[_program_to_summary(p) for p in programs],
    )


@router.get(
    "/programs/{program_id}/weeks/{week_number}",
    response_model=WeekResponse,
    summary="Get a single week's session templates",
)
def get_week(program_id: str, week_number: int, db: Session = Depends(get_db)):
    p = crud.get_program(db, program_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Program '{program_id}' not found.")

    weeks = (p.program_data or {}).get("weeks", [])
    matching = [w for w in weeks if w.get("week_number") == week_number]
    if not matching:
        raise HTTPException(
            status_code=404,
            detail=f"Week {week_number} not found in program '{program_id}'.",
        )
    return _week_to_response(matching[0])


@router.get(
    "/programs/{program_id}/next-session",
    response_model=NextSessionResponse,
    summary="Get the next session to complete in the current week",
)
def get_next_session(program_id: str, db: Session = Depends(get_db)):
    """
    Returns the next un-started session template for the current week.

    The system counts training sessions already logged with this program_id
    and program_week to determine which session comes next.
    """
    p = crud.get_program(db, program_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Program '{program_id}' not found.")

    if p.status == "completed":
        return NextSessionResponse(
            program_id=program_id,
            current_week=p.current_week,
            sessions_completed_this_week=0,
            sessions_planned_this_week=p.sessions_per_week,
            next_session=None,
            message="🎉 本训练计划已完成！",
        )

    current_week = p.current_week
    weeks = (p.program_data or {}).get("weeks", [])
    current_week_data = next(
        (w for w in weeks if w.get("week_number") == current_week), None
    )

    if not current_week_data:
        raise HTTPException(status_code=404, detail=f"Current week {current_week} data not found.")

    completed_sessions = crud.get_sessions_for_program_week(db, program_id, current_week)
    n_done = len(completed_sessions)
    sessions_planned = p.sessions_per_week
    all_sessions = current_week_data.get("sessions", [])

    if n_done >= sessions_planned or n_done >= len(all_sessions):
        return NextSessionResponse(
            program_id=program_id,
            current_week=current_week,
            sessions_completed_this_week=n_done,
            sessions_planned_this_week=sessions_planned,
            next_session=None,
            message=(
                f"✅ 本周 {n_done}/{sessions_planned} 次训练已完成！"
                "使用 POST /programs/{id}/advance 推进到下一周。"
            ),
        )

    next_sess_data = all_sessions[n_done]  # 0-indexed
    return NextSessionResponse(
        program_id=program_id,
        current_week=current_week,
        sessions_completed_this_week=n_done,
        sessions_planned_this_week=sessions_planned,
        next_session=_session_to_response(next_sess_data),
        message=(
            f"📋 本周第 {n_done + 1}/{sessions_planned} 次训练 — "
            f"{next_sess_data.get('label', next_sess_data.get('workout_type', ''))}"
        ),
    )


@router.post(
    "/programs/{program_id}/advance",
    response_model=AdvanceWeekResponse,
    summary="Advance to next week with adaptive modifications",
)
def advance_week(
    program_id: str,
    request: AdvanceWeekRequest,
    use_history: bool = Query(
        True,
        description="Run Phase 2 history analysis on completed sessions to inform adaptation.",
    ),
    db: Session = Depends(get_db),
):
    """
    Analyse the current week's completed sessions and advance the program.

    The system applies adaptive rules:
    - **Deload triggered** → override next week as deload week
    - **Completion < 60%** → repeat the current week
    - **RPE > 8.5 or completion < 80%** → hold intensity (no progression)
    - **Normal completion** → advance to next planned week type

    If `session_ids` is empty, sessions are auto-loaded from DB by program_id
    and current week number (requires sessions to be logged with these fields).
    """
    _require_engine()

    p = crud.get_program(db, program_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Program '{program_id}' not found.")

    if p.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Program is already completed.",
        )

    # Load completed sessions
    if request.session_ids:
        orm_sessions = [
            crud.get_session_by_id(db, sid)
            for sid in request.session_ids
            if crud.get_session_by_id(db, sid)
        ]
    else:
        orm_sessions = crud.get_sessions_for_program_week(
            db, program_id, p.current_week
        )

    completed_dicts = [crud.session_to_feedback_dict(s) for s in orm_sessions]

    # Optional history analysis (Phase 2)
    history_summary = None
    if use_history and completed_dicts:
        history_summary = analyze_history(completed_dicts, None)

    # Advance
    updated_program, report = _program_svc.advance_week(
        program=p.program_data,
        completed_sessions=completed_dicts,
        history_summary=history_summary,
    )

    # Persist
    updated_record = crud.update_program(db, program_id, updated_program)

    # Build next week detail for response
    next_week_num = updated_program.get("current_week", 1)
    weeks = updated_program.get("weeks", [])
    next_week_data = next(
        (w for w in weeks if w.get("week_number") == next_week_num), None
    )

    return AdvanceWeekResponse(
        program_id=program_id,
        adaptation_report=report,
        next_week=_week_to_response(next_week_data) if next_week_data else None,
    )


@router.patch(
    "/programs/{program_id}/status",
    response_model=ProgramSummaryResponse,
    summary="Update program status (pause / resume / complete)",
)
def update_status(
    program_id: str,
    request: StatusPatchRequest,
    db: Session = Depends(get_db),
):
    allowed = ("active", "paused", "completed")
    if request.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status '{request.status}'. Must be one of: {allowed}",
        )

    p = crud.get_program(db, program_id)
    if not p:
        raise HTTPException(status_code=404, detail=f"Program '{program_id}' not found.")

    updated_data = dict(p.program_data)
    updated_data["status"] = request.status
    updated = crud.update_program(db, program_id, updated_data)
    return _program_to_summary(updated)
