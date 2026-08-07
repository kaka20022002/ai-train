"""
WeChat Mini Program Auth
========================

Endpoints
---------
  POST /auth/wechat/login   — exchange wx.login code for access token
  POST /auth/dev-login      — local/dev login without WeChat credentials

Env
---
  WECHAT_APPID / WECHAT_SECRET  — real WeChat login (optional in development)
  AUTH_SECRET                   — HMAC secret for tokens (defaults for local only)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import crud
from database import get_db
from models import WeChatAccount

router = APIRouter(tags=["Auth"])

AUTH_SECRET = os.getenv("AUTH_SECRET", "ai-train-dev-secret-change-me")
WECHAT_APPID = os.getenv("WECHAT_APPID", "")
WECHAT_SECRET = os.getenv("WECHAT_SECRET", "")
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 days


class WeChatLoginRequest(BaseModel):
    code: str = Field(..., min_length=1, description="wx.login() temporary code")


class DevLoginRequest(BaseModel):
    user_id: str = Field("usr_demo", description="Existing or new local user id")


class AuthLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    is_new_user: bool = False
    mode: str = "dev"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def issue_token(user_id: str) -> str:
    payload = {
        "uid": user_id,
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64url(
        hmac.new(AUTH_SECRET.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    )
    return f"{body}.{sig}"


def verify_token(token: str) -> str:
    try:
        body, sig = token.split(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid token format") from exc

    expected = _b64url(
        hmac.new(AUTH_SECRET.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    )
    if not hmac.compare_digest(sig, expected):
        raise HTTPException(status_code=401, detail="Invalid token signature")

    payload = json.loads(_b64url_decode(body))
    if int(payload.get("exp", 0)) < int(time.time()):
        raise HTTPException(status_code=401, detail="Token expired")
    user_id = payload.get("uid")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing user id")
    return user_id


def _ensure_user(db: Session, user_id: str) -> bool:
    """Create a minimal profile if missing. Returns True when newly created."""
    existing = crud.get_user(db, user_id)
    if existing:
        return False
    crud.create_user(
        db,
        {
            "user_id": user_id,
            "basic_info": {"age": 28, "gender": "unknown"},
            "fitness_level": "beginner",
            "fitness_goal": "general_fitness",
            "training_frequency": 3,
            "available_equipment": [],
            "medical_history": [],
        },
    )
    return True


def _bind_openid(db: Session, openid: str, user_id: str) -> WeChatAccount:
    row = db.query(WeChatAccount).filter(WeChatAccount.openid == openid).first()
    if row:
        return row
    row = WeChatAccount(openid=openid, user_id=user_id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


async def _code2session(code: str) -> dict:
    if not WECHAT_APPID or not WECHAT_SECRET:
        # Local / tourist mode: synthesize a stable openid from the code
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]
        return {
            "openid": f"dev_openid_{digest}",
            "session_key": "dev",
            "mode": "dev",
        }

    url = "https://api.weixin.qq.com/sns/jscode2session"
    params = {
        "appid": WECHAT_APPID,
        "secret": WECHAT_SECRET,
        "js_code": code,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params=params)
        data = resp.json()
    if "errcode" in data and data["errcode"] != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"WeChat login failed: {data.get('errmsg', data)}",
        )
    data["mode"] = "wechat"
    return data


@router.post("/auth/wechat/login", response_model=AuthLoginResponse)
async def wechat_login(body: WeChatLoginRequest, db: Session = Depends(get_db)):
    session = await _code2session(body.code)
    openid = session["openid"]
    mode = session.get("mode", "wechat")

    binding = db.query(WeChatAccount).filter(WeChatAccount.openid == openid).first()
    is_new = False
    if binding:
        user_id = binding.user_id
    else:
        user_id = f"wx_{uuid.uuid4().hex[:10]}"
        is_new = _ensure_user(db, user_id)
        _bind_openid(db, openid, user_id)

    return AuthLoginResponse(
        access_token=issue_token(user_id),
        user_id=user_id,
        is_new_user=is_new,
        mode=mode,
    )


@router.post("/auth/dev-login", response_model=AuthLoginResponse)
def dev_login(body: DevLoginRequest, db: Session = Depends(get_db)):
    """
    Simulator-friendly login. Creates the user profile if it does not exist.
    Prefer this during local Taro development.
    """
    user_id = (body.user_id or "usr_demo").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id required")
    is_new = _ensure_user(db, user_id)
    return AuthLoginResponse(
        access_token=issue_token(user_id),
        user_id=user_id,
        is_new_user=is_new,
        mode="dev",
    )


