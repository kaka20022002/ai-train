"""Loopback-only fixture server. Never import this file from production code.

Always owns a fresh temporary database, disables real model calls, and exposes
fixture controls only inside this standalone test process.
"""
import copy
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
DATABASE = Path(tempfile.mkdtemp(prefix="fixture-", dir=ARTIFACTS)) / "test.db"
os.environ.update(
    AI_TRAIN_ENV_FROZEN="1", USE_REAL_LLM="false",
    AUTH_SECRET="isolated-browser-tests-only",
    DATABASE_URL="sqlite:///" + DATABASE.as_posix(),
)

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from main import app
from database import Base, SessionLocal, engine
from models import TrainingProgram, TrainingSession, User
from vr_bridge.models import VRConnection, VRPairing, VRResult
import crud

Base.metadata.create_all(engine)


def seed_reference(db, uid):
    if not crud.get_user(db, uid):
        crud.create_user(db, {"user_id":uid,"basic_info":{"age":30,"gender":"unknown"},
                             "fitness_level":"beginner","medical_history":[]})
    if not db.query(TrainingProgram).filter_by(user_id=uid).first():
        db.add(TrainingProgram(program_id="fixture-"+uid,user_id=uid,name="验收周期计划",goal="general_fitness",
            split_type="full_body",total_weeks=4,current_week=1,sessions_per_week=3,status="active",program_data={
                "weeks":[{"week_number":1,"sessions":[{"session_number":1,"label":"全身力量参考",
                "workout_type":"full_body","estimated_duration_minutes":30,
                "key_exercises":[{"name":"Barbell Back Squat","sets":3,"reps":"8","rest_seconds":60}]}]}]}))
        db.commit()
    if not db.query(TrainingSession).filter_by(user_id=uid).first():
        db.add(TrainingSession(session_id="ordinary-"+uid,user_id=uid,date="2026-01-01",rpe=6,
                               duration_minutes=10,completion_rate=1.0,exercise_performance=[]))
        db.commit()


with SessionLocal() as db:
    seed_reference(db,"usr_demo")
    crud.create_user(db,{"user_id":"usr_other","basic_info":{"age":30,"gender":"unknown"},
                        "fitness_level":"beginner","medical_history":[]})


@app.middleware("http")
async def fixture_failures(request: Request, call_next):
    if request.url.path == "/vr/overview":
        mode = request.headers.get("x-vr-test-mode", "")
        headers = {"Access-Control-Allow-Origin":"*"}
        if mode in {"401","429","503"}:
            if mode == "429": headers["Retry-After"]="60"
            return JSONResponse({"detail":"验收模拟服务异常"}, status_code=int(mode),headers=headers)
        if mode == "bad-json":
            return Response("{", media_type="application/json",headers=headers)
        if mode == "bad-data":
            return JSONResponse({"results":[None]},headers=headers)
    return await call_next(request)


@app.get("/__test/ready")
def ready():
    return {"fixture":True}


@app.post("/__test/reference/{uid}")
def reference(uid:str):
    with SessionLocal() as db:
        seed_reference(db,uid)
    return {"seeded":True}


@app.post("/__test/reset")
def reset():
    from vr_bridge.api import _attempts
    with SessionLocal() as db:
        db.query(VRPairing).delete(); db.query(VRResult).delete(); db.query(VRConnection).delete()
        db.commit()
    _attempts.clear()
    return {"reset":True}


@app.get("/__test/original/{uid}")
def original(uid:str):
    """Database snapshot proving that bridge actions do not edit original tables."""
    with SessionLocal() as db:
        user = crud.get_user(db,uid)
        programs = db.query(TrainingProgram).filter_by(user_id=uid).all()
        return {
            "profile":copy.deepcopy(crud.user_to_profile_dict(user)) if user else None,
            "programs":[{column.name:getattr(program,column.name) for column in TrainingProgram.__table__.columns} for program in programs],
            "ordinary_sessions":[{column.name:getattr(session,column.name) for column in TrainingSession.__table__.columns}
                                 for session in db.query(TrainingSession).filter_by(user_id=uid).all()],
        }


@app.post("/__test/expire")
def expire():
    import time
    deadline = int(time.time()) + 1
    with SessionLocal() as db:
        db.query(VRPairing).filter_by(state="pending").update({"expires_at":deadline})
        db.commit()
    return {"expires_at":deadline}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app,host="127.0.0.1",port=int(os.environ.get("VR_TEST_API_PORT","18765")),log_level="warning")
