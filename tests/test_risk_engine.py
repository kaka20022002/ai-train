"""Unit tests for static risk analysis."""
from __future__ import annotations

from risk_engine import RiskAssessmentEngine

from tests.conftest import KNEE_HIGH_PROFILE, NO_INJURY_PROFILE


def test_no_injury_has_empty_forbidden_list(risk_engine: RiskAssessmentEngine) -> None:
    forbidden, safe = risk_engine.analyze_static_risk(NO_INJURY_PROFILE)
    assert forbidden == []
    assert len(safe) > 0
    assert len(safe) == len(risk_engine.exercise_db) or len(safe) <= len(risk_engine.exercise_db)


def test_knee_high_severity_forbids_loaded_knee_exercises(risk_engine: RiskAssessmentEngine) -> None:
    forbidden, safe = risk_engine.analyze_static_risk(KNEE_HIGH_PROFILE)
    forbidden_names = {ex.name for ex in forbidden}

    assert len(forbidden) > 0
    assert "Barbell Back Squat" in forbidden_names

    for name in forbidden_names:
        assert name not in safe

    for ex in forbidden:
        assert ex.reason
        assert "knee" in ex.reason.lower() or "KNEE" in ex.reason


def test_forbidden_exercise_not_in_safe_pool(risk_engine: RiskAssessmentEngine) -> None:
    forbidden, safe = risk_engine.analyze_static_risk(KNEE_HIGH_PROFILE)
    safe_lower = {n.lower() for n in safe}
    for ex in forbidden:
        assert ex.name.lower() not in safe_lower
