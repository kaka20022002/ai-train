"""Training-program recommendation endpoints."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import crud
import models
from database import get_db
from program_recommender import ProgramRecommendationService
from risk_engine import RiskAssessmentEngine

router = APIRouter(tags=["Plan Recommendations"])

_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "exercise_db.json")
_recommender = ProgramRecommendationService()

try:
    _risk_engine = RiskAssessmentEngine(db_path=_DB_PATH)
    _ENGINE_READY = True
except Exception as exc:
    print(f"WARNING: recommendation router could not load risk engine: {exc}")
    _risk_engine = None
    _ENGINE_READY = False


class RecommendationModelInfo(BaseModel):
    name: str
    version: str
    weights: Dict[str, float]


class RecommendationUserSnapshot(BaseModel):
    goal: str
    goal_label: str
    fitness_level: str
    training_frequency: int
    available_equipment: List[str] = Field(default_factory=list)
    injury_count: int
    session_count: int
    average_completion_rate: Optional[float] = None
    average_rpe: Optional[float] = None
    actual_sessions_per_week: Optional[float] = None
    pain_locations: List[str] = Field(default_factory=list)


class RecommendationComponentScores(BaseModel):
    profile: float
    behaviour: float
    population: float


class ProgramRecommendation(BaseModel):
    rank: int
    template_id: str
    name: str
    description: str
    goal: str
    goal_label: str
    split_type: str
    split_label: str
    total_weeks: int
    sessions_per_week: int
    difficulty: str
    difficulty_label: str
    estimated_duration_minutes: int
    focus_areas: List[str] = Field(default_factory=list)
    required_equipment: List[str] = Field(default_factory=list)
    score: float
    component_scores: RecommendationComponentScores
    match_reasons: List[str] = Field(default_factory=list)
    cautions: List[str] = Field(default_factory=list)
    safe_exercise_count: int
    forbidden_exercise_count: int


class ProgramRecommendationResponse(BaseModel):
    user_id: str
    generated_at: str
    model: RecommendationModelInfo
    user_snapshot: RecommendationUserSnapshot
    recommendations: List[ProgramRecommendation]


@router.get(
    "/users/{user_id}/plan-recommendations",
    response_model=ProgramRecommendationResponse,
    summary="Personalised multi-week training-plan recommendations",
)
def get_plan_recommendations(
    user_id: str,
    limit: int = Query(6, ge=1, le=12),
    db: Session = Depends(get_db),
):
    """Return ranked program templates using profile and training behaviour."""
    if not _ENGINE_READY or _risk_engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Recommendation safety engine is unavailable.",
        )

    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found.",
        )

    profile = crud.user_to_profile_dict(user)
    sessions = crud.get_recent_sessions(db, user_id, n=30)
    session_dicts = [crud.session_to_feedback_dict(item) for item in sessions]
    adoption_programs = (
        db.query(models.TrainingProgram)
        .filter(models.TrainingProgram.user_id != user_id)
        .limit(1000)
        .all()
    )

    forbidden, safe = _risk_engine.analyze_static_risk(profile)
    result = _recommender.recommend(
        user_profile=profile,
        sessions=session_dicts,
        adoption_programs=[
            {
                "goal": item.goal,
                "split_type": item.split_type,
                "sessions_per_week": item.sessions_per_week,
                "total_weeks": item.total_weeks,
            }
            for item in adoption_programs
        ],
        safe_exercise_count=len(safe),
        forbidden_exercise_count=len(forbidden),
        limit=limit,
    )

    return {
        "user_id": user_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }
