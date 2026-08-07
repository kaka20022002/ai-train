"""
Database Configuration for Adaptive Athletic Training System
============================================================

Uses SQLite for development (zero-config, file-based).
Switch to PostgreSQL for production by setting the DATABASE_URL env variable:
    DATABASE_URL=postgresql://user:password@localhost/ai_train

All models are defined in models.py; this module only owns the engine and
the session factory so there are no circular imports.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Default: SQLite file in project root. Override via env for PostgreSQL.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ai_train.db")

# SQLite requires check_same_thread=False for FastAPI's async request handling.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency: yields a DB session per request, always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
