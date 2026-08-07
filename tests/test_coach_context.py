"""Tests for AI coach context — forbidden exercise hard constraints."""
from __future__ import annotations

import crud
from coach_agent import build_context
from safety_sync import format_forbidden_context_for_coach, get_risk_snapshot

from tests.conftest import KNEE_HIGH_PROFILE, NO_INJURY_PROFILE


def test_build_context_includes_forbidden_summary(db_session) -> None:
    crud.create_user(db_session, KNEE_HIGH_PROFILE)
    ctx = build_context(db_session, KNEE_HIGH_PROFILE["user_id"])

    assert ctx.forbidden_summary is not None
    assert "禁止动作清单" in ctx.forbidden_summary

    rendered = ctx.render()
    assert "🚫" in rendered
    forbidden, _ = get_risk_snapshot(KNEE_HIGH_PROFILE)
    assert forbidden[0].name in rendered


def test_build_context_no_injury_shows_empty_forbidden(db_session) -> None:
    crud.create_user(db_session, NO_INJURY_PROFILE)
    ctx = build_context(db_session, NO_INJURY_PROFILE["user_id"])

    assert ctx.forbidden_summary is not None
    assert "无绝对禁止动作" in ctx.forbidden_summary


def test_format_forbidden_context_empty() -> None:
    text = format_forbidden_context_for_coach([], 50)
    assert "无绝对禁止动作" in text
