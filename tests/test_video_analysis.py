"""Video-analysis API tests that do not require GPU models."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from coach_agent import CoachResponse
from main import app
from routers import video_analysis as video_router
from video_socrate_service import (
    EvidenceFrame,
    VideoAnalysisResult,
    VideoSocrateUnavailable,
    get_video_socrate_service,
)


VALID_MP4 = b"\x00\x00\x00\x18ftypmp42" + (b"\x00" * 128)


class FakeVideoService:
    def __init__(self, *, unavailable: bool = False) -> None:
        self.unavailable = unavailable
        self.temp_path: Path | None = None
        self.question = ""

    def analyze(
        self,
        video_path: Path,
        question: str,
        *,
        content_hash: str,
        progress_callback: Any = None,
    ) -> VideoAnalysisResult:
        self.temp_path = video_path
        self.question = question
        assert video_path.is_file()
        assert len(content_hash) == 64
        if self.unavailable:
            raise VideoSocrateUnavailable("vision runtime unavailable")
        return VideoAnalysisResult(
            model="qwen-test-vl",
            summary="下蹲下降阶段可见右膝向内偏移，回程时躯干略向左侧倾。",
            reason="2.0s、3.0s 和 4.0s 的画面覆盖下降、底部与回程。",
            evidence_frames=[
                EvidenceFrame(frame_id=48, timestamp_seconds=2.0),
                EvidenceFrame(frame_id=72, timestamp_seconds=3.0),
                EvidenceFrame(frame_id=96, timestamp_seconds=4.0),
            ],
            duration_seconds=8.5,
            processing_seconds=1.2,
        )


def _create_user(client) -> str:
    user_id = "usr_video_test"
    response = client.post(
        "/users",
        json={
            "user_id": user_id,
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
        },
    )
    assert response.status_code == 201, response.text
    return user_id


def test_video_analysis_uses_evidence_and_cleans_temp(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id = _create_user(client)
    service = FakeVideoService()
    app.dependency_overrides[get_video_socrate_service] = lambda: service
    captured: dict[str, Any] = {}

    def fake_respond(*, context, history, user_message):
        captured["context"] = context
        captured["history"] = history
        captured["user_message"] = user_message
        return CoachResponse(
            content="视频显示右膝内移；结合你的膝伤史，建议先降低负荷并纠正对线。"
        )

    monkeypatch.setattr(video_router._video_coach, "respond", fake_respond)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_MODEL", "deepseek-chat")

    response = client.post(
        "/video-analysis",
        data={
            "user_id": user_id,
            "question": "我的深蹲动作在整个视频里有没有问题？",
        },
        files={"file": ("squat.mp4", VALID_MP4, "video/mp4")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["video_analysis"]["model"] == "qwen-test-vl"
    assert body["video_analysis"]["evidence_frames"][1]["timestamp_seconds"] == 3.0
    assert body["answer_model"] == {
        "provider": "openai",
        "model": "deepseek-chat",
    }
    assert body["assistant_message"]["content"].startswith("视频显示右膝内移")
    assert body["conversation_id"]
    assert body["disclaimer"]

    enriched = captured["user_message"]
    assert "右膝向内偏移" in enriched
    assert "2.0s（帧 48）" in enriched
    assert "用户原问题" in enriched
    assert captured["context"].user_id == user_id
    assert service.temp_path is not None
    assert not service.temp_path.exists()


def test_video_analysis_rejects_unsupported_file(client) -> None:
    service = FakeVideoService()
    app.dependency_overrides[get_video_socrate_service] = lambda: service
    response = client.post(
        "/video-analysis",
        data={"user_id": "usr_bad_video", "question": "动作安全吗？"},
        files={"file": ("notes.txt", b"not video", "text/plain")},
    )
    assert response.status_code == 415
    assert service.temp_path is None


def test_video_analysis_rejects_oversized_file(
    client, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = FakeVideoService()
    app.dependency_overrides[get_video_socrate_service] = lambda: service
    monkeypatch.setenv("VIDEO_MAX_BYTES", "32")
    response = client.post(
        "/video-analysis",
        data={"user_id": "usr_large_video", "question": "动作安全吗？"},
        files={"file": ("large.mp4", VALID_MP4, "video/mp4")},
    )
    assert response.status_code == 413
    assert service.temp_path is None


def test_video_analysis_returns_503_and_cleans_temp(client) -> None:
    service = FakeVideoService(unavailable=True)
    app.dependency_overrides[get_video_socrate_service] = lambda: service
    response = client.post(
        "/video-analysis",
        data={"user_id": "usr_unavailable", "question": "动作安全吗？"},
        files={"file": ("squat.mp4", VALID_MP4, "video/mp4")},
    )
    assert response.status_code == 503
    assert "vision runtime unavailable" in response.text
    assert service.temp_path is not None
    assert not service.temp_path.exists()


def test_open_ended_reflector_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("cv2")
    from video_socrate_service import configure_video_socrate_environment

    configure_video_socrate_environment()
    from vendor.v_socrate_1020.agent.models.agent import TAKAAgent
    from vendor.v_socrate_1020.prompt.reflector import format_reflector_prompt

    prompt = format_reflector_prompt(
        question="我的动作安全吗？",
        candidates="  (No candidates provided)",
        long_video_section="",
        crop_section="judge frames as shown",
        open_ended=True,
    )
    assert "open-ended" not in prompt.lower()  # user-facing protocol, not implementation jargon
    assert "exercise form and safety" in prompt
    assert '"choice":""' in prompt
    assert "UNASSESSABLE" in prompt

    decision, error = TAKAAgent._validate_reflect_decision(
        {
            "status": "CONFIRM",
            "answer": {"choice": "", "text": "可见躯干在回程时向左侧倾。"},
            "reason": "连续画面覆盖底部与回程。",
            "evidence_frame_ids": [10, 20],
        },
        [10, 20],
        [],
    )
    assert error == ""
    assert decision["answer"]["text"].startswith("可见躯干")

    unassessable, error = TAKAAgent._validate_reflect_decision(
        {
            "status": "UNASSESSABLE",
            "answer": {
                "choice": "",
                "text": "整段仅显示火柴人动画，无法判断真实膝关节对线。",
            },
            "reason": "时间线上多个画面都没有可辨识的人体关节。",
            "evidence_frame_ids": [10, 20],
        },
        [10, 20],
        [],
    )
    assert error == ""
    assert unassessable["status"] == "UNASSESSABLE"

    _, candidate_error = TAKAAgent._validate_reflect_decision(
        {
            "status": "CONFIRM",
            "answer": {"choice": "", "text": "A"},
            "reason": "visible",
            "evidence_frame_ids": [10],
        },
        [10],
        ["A", "B"],
    )
    assert "choice must be a non-empty string" in candidate_error
