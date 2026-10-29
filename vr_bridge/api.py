"""Short-code association, optional reference, and one-shot result upload.

Web identity deliberately reuses the existing local/development login. Deploying
this prototype publicly requires replacing that login, not trusting a user_id.
No polling, heartbeat, training command, or prescription enforcement is provided.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import threading
import time
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import crud
from database import get_db
from routers.auth import verify_token
from vr_bridge.models import VRConnection, VRResult, VRPairing

router = APIRouter(prefix="/vr", tags=["VR bridge (independent)"])
bearer = HTTPBearer(auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
Db = Annotated[Session, Depends(get_db)]
PAIR_TTL_SECONDS = 300
_attempts: dict[str, tuple[float, int]] = {}
_attempt_lock = threading.Lock()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _limit(key: str, maximum: int) -> None:
    """Bounded process-local limiter for this local prototype only."""
    now = time.monotonic()
    with _attempt_lock:
        for old in list(_attempts):
            if now - _attempts[old][0] >= 60:
                del _attempts[old]
        start, count = _attempts.get(key, (now, 0))
        if count >= maximum or (key not in _attempts and len(_attempts) >= 2048):
            raise HTTPException(429, "尝试过于频繁，请稍后再试。", headers={"Retry-After": "60"})
        _attempts[key] = (start, count + 1)


def _web_user(credentials: Credentials, db: Db) -> str:
    if credentials is None:
        raise HTTPException(401, "请先登录当前用户。")
    try:
        uid = verify_token(credentials.credentials)
    except (ValueError, TypeError, KeyError):
        raise HTTPException(401, "登录凭据无效，请重新登录。")
    if not crud.get_user(db, uid):
        raise HTTPException(401, "用户档案不存在。")
    return uid


WebUser = Annotated[str, Depends(_web_user)]


def _device(credentials: Credentials, db: Db) -> VRConnection:
    if credentials is None:
        raise HTTPException(401, "缺少头显凭据。")
    device_id, _, secret = credentials.credentials.partition(".")
    item = db.get(VRConnection, device_id)
    if not item or not secret or not hmac.compare_digest(item.secret_hash, _hash(secret)):
        raise HTTPException(401, "头显凭据无效。")
    if item.state == "revoked":
        raise HTTPException(410, "关联已解除，请重新获取连接短码。")
    if item.state == "pending" and item.expires_at <= int(time.time()):
        raise HTTPException(410, "连接短码已过期，请重新获取。")
    return item


Device = Annotated[VRConnection, Depends(_device)]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PairingRequest(Input):
    include_today_plan: bool = False


class RedeemRequest(Input):
    code: str = Field(pattern=r"^[0-9]{6}$")
    device_name: str = Field(min_length=1, max_length=80)
    # Device-generated 256-bit secret enables safe retry after a lost response.
    device_secret: str = Field(pattern=r"^[A-Za-z0-9_-]{43,128}$")


class ReferenceRequest(Input):
    enabled: bool


class ActionResult(Input):
    action_id: str = Field(min_length=1, max_length=100)
    action_name: str = Field(min_length=1, max_length=80)
    completed_sets: int | None = Field(None, ge=0, le=200)
    completed_reps: int | None = Field(None, ge=0, le=20000)
    duration_seconds: float | None = Field(None, ge=0, le=86400, allow_inf_nan=False)
    quality_score_01: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)
    tracking_good_ratio_01: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)


class ResultRequest(Input):
    client_session_id: str = Field(min_length=1, max_length=80)
    context_user_id: str = Field(min_length=1, max_length=64)
    started_at: datetime
    ended_at: datetime
    outcome: Literal["completed", "stopped"]
    actions: list[ActionResult] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def valid_times(self):
        if self.started_at.utcoffset() is None or self.ended_at.utcoffset() is None:
            raise ValueError("开始与结束时间必须包含时区")
        if not 0 <= (self.ended_at - self.started_at).total_seconds() <= 86400:
            raise ValueError("训练时间范围无效")
        return self


def _reference_exercises(value) -> list[dict]:
    """Only copy readable preview fields; never repair the original prescription."""
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            continue
        sets, reps = item.get("sets"), item.get("reps")
        if type(sets) is not int or sets <= 0 or not isinstance(reps, (str, int, float)) or isinstance(reps, bool):
            continue
        if isinstance(reps, float) and not math.isfinite(reps):
            continue
        result.append({"name": item["name"], "sets": sets, "reps": str(reps)})
    return result


def _safe_reference(value) -> dict | None:
    if not isinstance(value, dict) or not isinstance(value.get("title"), str) or not value["title"].strip():
        return None
    if type(value.get("source_week")) is not int or value["source_week"] < 1:
        return None
    result = dict(value)
    result["key_exercises"] = _reference_exercises(value.get("key_exercises"))
    phases = value.get("phases")
    result["phases"] = {key: _reference_exercises(items) for key, items in phases.items()} if isinstance(phases, dict) else None
    duration = value.get("estimated_duration_minutes")
    result["estimated_duration_minutes"] = duration if type(duration) in (int, float) and math.isfinite(duration) and duration > 0 else None
    return result


def _today_reference(db: Session, uid: str) -> dict | None:
    """Read existing next-session data without advancing or changing a program."""
    program = crud.get_active_program(db, uid)
    if not program or not isinstance(program.program_data, dict):
        return None
    weeks = program.program_data.get("weeks")
    if not isinstance(weeks, list) or type(program.sessions_per_week) is not int or program.sessions_per_week <= 0:
        return None
    week = next((w for w in weeks if isinstance(w, dict) and w.get("week_number") == program.current_week), None)
    if not week:
        return None
    done = len(crud.get_sessions_for_program_week(db, program.program_id, program.current_week))
    sessions = week.get("sessions")
    if not isinstance(sessions, list):
        return None
    if done >= min(len(sessions), program.sessions_per_week):
        return None
    session = sessions[done]
    if not isinstance(session, dict):
        return None
    title = next((session.get(key) for key in ("label", "workout_type")
                  if isinstance(session.get(key), str) and session[key].strip()), "今日训练")
    return _safe_reference({
        "source_program_id": program.program_id,
        "source_week": program.current_week,
        "title": title,
        "workout_type": session.get("workout_type"),
        "estimated_duration_minutes": session.get("estimated_duration_minutes"),
        "phases": session.get("phases"),
        "key_exercises": session.get("key_exercises") or [],
        "advisory_only": True,
        "vr_schedule_authoritative": True,
    })


def _connection(item: VRConnection | None) -> dict | None:
    if not item:
        return None
    return {
        "id": item.id,
        "device_name": item.device_name,
        "connected_at": item.connected_at,
        "reference": _safe_reference(item.reference),
        "reference_updated_at": item.reference_updated_at,
    }


def _active(db: Session, uid: str) -> VRConnection:
    item = db.query(VRConnection).filter_by(user_id=uid, state="connected").first()
    if not item:
        raise HTTPException(404, "尚未关联头显。")
    return item


@router.post("/pairings", status_code=201)
def create_pairing(body: PairingRequest, uid: WebUser, db: Db):
    """WEB/MINI: issue a code tied to the authenticated user and optional snapshot."""
    _limit("pair:" + uid, 10)
    if db.query(VRConnection).filter_by(user_id=uid, state="connected").first():
        raise HTTPException(409, "请先解除当前头显关联，再申请新短码。")
    reference = _today_reference(db, uid) if body.include_today_plan else None
    if body.include_today_plan and reference is None:
        raise HTTPException(409, "今日计划已变化或不可用，请刷新后重试。")
    now = int(time.time())
    previous = db.query(VRPairing).filter_by(user_id=uid).first()
    previous_hash = previous.code_hash if previous else None
    # Delete the previous code only inside the successful issuance transaction.
    # Collision retries roll this deletion back as well.
    for _ in range(5):
        db.query(VRPairing).filter((VRPairing.user_id == uid) | (VRPairing.expires_at <= now)).delete(synchronize_session=False)
        code = f"{secrets.randbelow(1_000_000):06d}"
        if _hash(code) == previous_hash:
            db.rollback()
            continue
        item = VRPairing(id=uuid.uuid4().hex, user_id=uid, code_hash=_hash(code),
                         expires_at=now + PAIR_TTL_SECONDS, state="pending", reference=reference)
        db.add(item)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            continue
        return {"id": item.id, "code": code, "expires_at": item.expires_at, "reference": reference}
    raise HTTPException(503, "暂时无法生成短码，请重试。")


@router.delete("/pairings", status_code=204)
def cancel_pairing(uid: WebUser, db: Db):
    db.query(VRPairing).filter_by(user_id=uid, state="pending").delete(synchronize_session=False)
    db.commit()
    return Response(status_code=204)


def _context(item: VRConnection) -> dict:
    return {"state": "connected", "user_id": item.user_id, "today_reference": _safe_reference(item.reference),
            "advisory_only": True, "vr_schedule_authoritative": True, "training_channel": "none"}


@router.post("/device/pairings/redeem")
def redeem_pairing(body: RedeemRequest, request: Request, db: Db):
    """HEADSET: atomically consume a web-issued code; only this device gets credentials."""
    _limit("redeem:" + (request.client.host if request.client else "unknown"), 6)
    now = int(time.time())
    pairing = db.query(VRPairing).filter_by(code_hash=_hash(body.code)).first()
    if not pairing or pairing.expires_at <= now:
        raise HTTPException(400, "短码无效或已过期，请在网页或小程序重新申请。")
    device_id = _hash("device:" + body.device_secret)[:32]

    def response(item):
        return {"device_token": f"{item.id}.{body.device_secret}", **_context(item)}

    if pairing.state == "consumed":
        item = db.get(VRConnection, pairing.connection_id)
        if item and item.id == device_id and hmac.compare_digest(item.secret_hash, _hash(body.device_secret)):
            if item.state != "connected" or not item.user_id:
                raise HTTPException(410, "关联已解除，请重新申请短码。")
            return response(item)
        raise HTTPException(400, "短码已使用，请在网页或小程序重新申请。")
    if db.query(VRConnection).filter_by(user_id=pairing.user_id, state="connected").first():
        raise HTTPException(409, "该用户已有头显关联，请先解除关联。")
    count = db.query(VRPairing).filter_by(id=pairing.id, state="pending").filter(VRPairing.expires_at > now).update(
        {"state": "consumed", "connection_id": device_id}, synchronize_session=False)
    if not count:
        db.rollback()
        raise HTTPException(409, "短码状态已变化，请重新匹配。")
    item = VRConnection(id=device_id, device_name=body.device_name, secret_hash=_hash(body.device_secret),
                        code_hash=None, expires_at=pairing.expires_at, user_id=pairing.user_id,
                        state="connected", connected_at=now, reference=pairing.reference,
                        reference_updated_at=now if pairing.reference else None)
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "关联状态已变化，请刷新网页或小程序后重试。")
    return response(item)


@router.post("/device/pairings", deprecated=True)
def retired_device_pairing():
    raise HTTPException(410, "配对方式已更新：请在网页或小程序申请短码，在头显输入。")


@router.get("/overview")
def overview(uid: WebUser, db: Db):
    item = db.query(VRConnection).filter_by(user_id=uid, state="connected").first()
    results = db.query(VRResult).filter_by(user_id=uid).order_by(VRResult.received_at.desc(), VRResult.id.desc()).limit(20).all()
    pending = db.query(VRPairing).filter_by(user_id=uid, state="pending").filter(VRPairing.expires_at > int(time.time())).first()
    return {"connection": _connection(item), "pairing": {"id": pending.id, "expires_at": pending.expires_at, "reference": _safe_reference(pending.reference)} if pending else None,
            "today_reference": _today_reference(db, uid),
            "results": [{"id": r.id, "received_at": r.received_at, **r.data} for r in results]}


@router.post("/connection", deprecated=True)
def retired_web_redemption():
    raise HTTPException(410, "请在网页或小程序申请短码，在头显输入匹配。")


@router.put("/connection/reference")
def update_reference(body: ReferenceRequest, uid: WebUser, db: Db):
    item = _active(db, uid)
    reference = _today_reference(db, uid) if body.enabled else None
    if body.enabled and reference is None:
        raise HTTPException(409, "暂无可附带的今日计划，请先创建计划。")
    item.reference = reference
    item.reference_updated_at = int(time.time())
    db.commit()
    return _connection(item)


@router.delete("/connection", status_code=204)
def disconnect(uid: WebUser, db: Db):
    item = _active(db, uid)
    item.state = "revoked"
    item.user_id = None
    item.reference = None
    db.commit()
    return Response(status_code=204)


@router.get("/device/context")
def device_context(item: Device):
    """HEADSET: read only before training; do not poll during execution."""
    if item.state == "pending":
        return {"state": "pending", "expires_at": item.expires_at}
    return _context(item)


@router.post("/device/results")
def upload_result(body: ResultRequest, item: Device, db: Db):
    """HEADSET: optional single upload after training, retry identical IDs safely."""
    if item.state != "connected" or not item.user_id:
        raise HTTPException(409, "请先在网页完成短码关联。")
    if body.context_user_id != item.user_id:
        raise HTTPException(409, "结果所属用户与当前关联不同，请切回原用户后同步。")
    data = body.model_dump(mode="json")
    digest = _hash(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False))

    def existing():
        return db.query(VRResult).filter_by(user_id=item.user_id, client_session_id=body.client_session_id).first()

    def reply(record, duplicate):
        if record.payload_hash != digest:
            raise HTTPException(409, "相同训练编号已有不同内容，请检查上传数据。")
        return {"id": record.id, "duplicate": duplicate}

    record = existing()
    if record:
        return reply(record, True)
    record = VRResult(id=uuid.uuid4().hex, user_id=item.user_id, connection_id=item.id,
                      client_session_id=body.client_session_id, payload_hash=digest,
                      data=data, received_at=int(time.time()))
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = existing()
        if previous:
            return reply(previous, True)
        raise HTTPException(409, "结果保存冲突，请重试。")
    return reply(record, False)
