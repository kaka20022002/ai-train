"""
Insights Router — Sprint 4
==========================

Read-only analytics derived from a user's logged training history:

  GET /users/{user_id}/readiness     — 0–100 training-readiness score (#8)
  GET /users/{user_id}/progression   — per-exercise overload tracking + next-set
                                        suggestions, with 1RM estimates (#3)

Both endpoints are pure derivations over stored sessions, so they are safe to
poll from the frontend (e.g. on the「今日训练」page).
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import crud
from database import get_db
from progression_engine import analyze_progression
from readiness import compute_readiness

router = APIRouter(tags=["Insights"])


# Load the exercise DB once (for per-exercise load-increment heuristics).
_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "exercise_db.json")
try:
    with open(_DB_PATH, "r", encoding="utf-8") as _f:
        _EXERCISE_DB: List[Dict[str, Any]] = json.load(_f)
except Exception:  # pragma: no cover — degrade gracefully
    _EXERCISE_DB = []


# =============================================================================
# Schemas
# =============================================================================

class ReadinessFactor(BaseModel):
    label: str
    value: str
    score: int
    status: str  # good | ok | bad


class ReadinessResponse(BaseModel):
    user_id: str
    score: Optional[int] = None
    band: str
    label: str
    recommendation: str
    suggested_intensity_modifier: float
    based_on_sessions: int
    factors: List[ReadinessFactor] = Field(default_factory=list)


class NextSetSuggestion(BaseModel):
    suggested_weight_kg: Optional[float] = None
    suggested_reps: str
    action: str
    rationale: str
    last_weight_kg: Optional[float] = None
    last_reps: Optional[List[int]] = None
    est_1rm: Optional[float] = None
    trend: str


class ProgressionHistoryPoint(BaseModel):
    date: Optional[str] = None
    weight_kg: Optional[float] = None
    reps_per_set: List[int] = Field(default_factory=list)
    est_1rm: Optional[float] = None


class ExerciseProgressionReport(BaseModel):
    exercise_name: str
    sessions_tracked: int
    current_weight_kg: Optional[float] = None
    best_est_1rm: Optional[float] = None
    est_1rm_change_kg: Optional[float] = None
    trend: str
    last_date: Optional[str] = None
    history: List[ProgressionHistoryPoint] = Field(default_factory=list)
    suggestion: NextSetSuggestion


class ProgressionResponse(BaseModel):
    user_id: str
    goal: str
    tracked_exercises: int
    reports: List[ExerciseProgressionReport] = Field(default_factory=list)


# =============================================================================
# Helpers
# =============================================================================

def _resolve_goal(db: Session, user_id: str) -> str:
    """Prefer the active program's goal, else the user's stated fitness goal."""
    active = crud.get_active_program(db, user_id)
    if active and active.goal:
        return active.goal
    user = crud.get_user(db, user_id)
    if user and user.fitness_goal:
        return user.fitness_goal
    return "general_fitness"


# =============================================================================
# Endpoints
# =============================================================================

@router.get(
    "/users/{user_id}/readiness",
    response_model=ReadinessResponse,
    summary="Training readiness score (0–100)",
)
def get_readiness(
    user_id: str,
    window: int = Query(7, ge=1, le=30, description="Recent sessions to consider"),
    db: Session = Depends(get_db),
):
    if not crud.get_user(db, user_id):
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")

    sessions = crud.get_recent_sessions(db, user_id, n=window)
    session_dicts = [crud.session_to_feedback_dict(s) for s in sessions]
    result = compute_readiness(session_dicts)
    return ReadinessResponse(user_id=user_id, **result)


@router.get(
    "/users/{user_id}/progression",
    response_model=ProgressionResponse,
    summary="Per-exercise progressive-overload tracking & suggestions",
)
def get_progression(
    user_id: str,
    window: int = Query(20, ge=1, le=60, description="Recent sessions to analyse"),
    db: Session = Depends(get_db),
):
    if not crud.get_user(db, user_id):
        raise HTTPException(status_code=404, detail=f"User '{user_id}' not found.")

    sessions = crud.get_recent_sessions(db, user_id, n=window)
    session_dicts = [crud.session_to_feedback_dict(s) for s in sessions]
    goal = _resolve_goal(db, user_id)

    reports = analyze_progression(session_dicts, goal=goal, exercise_db=_EXERCISE_DB)
    return ProgressionResponse(
        user_id=user_id,
        goal=goal,
        tracked_exercises=len(reports),
        reports=reports,
    )
