"""Shared pytest fixtures — in-memory SQLite for isolated API/DB tests."""
from __future__ import annotations

import os

# 必须在 import main / agents 之前钉死：单元测试一律不连真实 LLM。
# .env 里填了 key 并打开 USE_REAL_LLM 之后，若不做这一步，整个测试套件会
# 开始真调 API（慢、花钱、且网络抖动会让结果 flaky）。
# AI_TRAIN_ENV_FROZEN 让 main.py 加载 .env 时不 override，否则下面的
# USE_REAL_LLM=false 会被 .env 里的 true 改回去。
os.environ["AI_TRAIN_ENV_FROZEN"] = "1"
os.environ["USE_REAL_LLM"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import get_db
from main import app
from risk_engine import RiskAssessmentEngine


KNEE_HIGH_PROFILE = {
    "user_id": "usr_test_knee",
    "basic_info": {"age": 28, "gender": "male"},
    "fitness_level": "intermediate",
    "medical_history": [
        {
            "location": "knee",
            "condition": "meniscus_tear",
            "severity": "high",
            "pain_trigger": "deep_flexion",
        }
    ],
}

NO_INJURY_PROFILE = {
    "user_id": "usr_test_clean",
    "basic_info": {"age": 30, "gender": "female"},
    "fitness_level": "beginner",
    "medical_history": [],
}


@pytest.fixture(scope="session")
def risk_engine() -> RiskAssessmentEngine:
    return RiskAssessmentEngine()


@pytest.fixture()
def db_session():
    """Fresh in-memory database per test (StaticPool = shared across threads)."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        models.Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session):
    """FastAPI TestClient with get_db overridden to the in-memory session."""

    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
