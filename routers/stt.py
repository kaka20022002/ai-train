"""
Speech-to-Text for mini program voice input.
--------------------------------------------
POST /stt  (multipart file field: ``file``)

Uses OpenAI-compatible Whisper when configured:
  WHISPER_API_KEY   (fallback: OPENAI_API_KEY)
  WHISPER_BASE_URL  (default https://api.openai.com/v1)
  WHISPER_MODEL     (default whisper-1)

Note: DeepSeek chat keys usually cannot call Whisper. Prefer WeChat SI plugin
on the client; this endpoint is a server-side fallback when you have a Whisper
compatible key.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter(tags=["Speech"])


@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...)):
    api_key = os.getenv("WHISPER_API_KEY") or os.getenv("OPENAI_API_KEY")
    base = (os.getenv("WHISPER_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("WHISPER_MODEL", "whisper-1")

    if not api_key:
        raise HTTPException(
            status_code=503,
            detail=(
                "未配置语音识别密钥。请在小程序使用微信「同声传译」插件，"
                "或设置 WHISPER_API_KEY 后调用本接口。"
            ),
        )

    # DeepSeek chat endpoint cannot transcribe audio
    if "deepseek.com" in base:
        raise HTTPException(
            status_code=503,
            detail=(
                "当前 OPENAI_BASE_URL 指向 DeepSeek，不支持 Whisper。"
                "请单独设置 WHISPER_API_KEY + WHISPER_BASE_URL=https://api.openai.com/v1，"
                "或使用微信同声传译插件。"
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="空音频文件")

    filename = file.filename or "audio.mp3"
    mime = file.content_type or "application/octet-stream"

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{base}/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (filename, content, mime)},
                data={"model": model, "language": "zh"},
            )
        if resp.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=f"语音识别失败: {resp.status_code} {resp.text[:300]}",
            )
        data = resp.json()
        text = (data.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="未识别到有效文本")
        return {"text": text, "provider": "whisper"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"语音识别异常: {exc}") from exc
