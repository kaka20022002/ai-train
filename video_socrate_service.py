"""Application adapter for the vendored V-Socrate-1020 inference runtime.

V-Socrate uses a multimodal Qwen/vLLM endpoint to find and review evidence frames.
The text evidence returned here is intentionally kept separate from ``LLMClient``:
the regular coach model (DeepSeek by default) consumes it in the API layer.
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


ProgressCallback = Callable[[str, Dict[str, Any]], None]


class VideoSocrateError(RuntimeError):
    """Base error for a configured runtime that failed to analyse a video."""


class VideoSocrateUnavailable(VideoSocrateError):
    """The optional video runtime is disabled, incomplete, or unreachable."""


class VideoSocrateInputError(VideoSocrateError):
    """The uploaded video could not be decoded or contained no usable frames."""


@dataclass(frozen=True)
class EvidenceFrame:
    frame_id: int
    timestamp_seconds: float


@dataclass(frozen=True)
class VideoAnalysisResult:
    model: str
    summary: str
    reason: str
    evidence_frames: List[EvidenceFrame]
    duration_seconds: float
    processing_seconds: float
    mock: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_PROJECT_ROOT = Path(__file__).resolve().parent
_DEFAULT_CLIP_MODEL = (
    "/apdcephfs_gy5/share_303098609/hunyuan/jaypernzhou/dev/"
    "Videoagent/V-Socrate-1020/models/clip-vit-base-patch32"
)

# V-Socrate deliberately reads all tuning values from the environment at import time.
# These application defaults mirror configs/common_env.sh while keeping benchmark-only
# paths out of the web service.
_TAKA_DEFAULTS: Dict[str, str] = {
    "TAKA_IMAGE_MAX_SIDE": "448",
    "TAKA_OBS_MAX_SIDE": "448",
    "TAKA_CROP_MAX_SIDE": "640",
    "TAKA_ENHANCE_MAX_SIDE": "900",
    "TAKA_SELECTOR_ENHANCE_MAX_SIDE": "640",
    "TAKA_REFLECT_MAX_FRAMES": "32",
    "TAKA_REFLECTOR_MAX_TOOL_CALLS": "8",
    "TAKA_LLM_MAX_ATTEMPTS": "3",
    "TAKA_LEAD_MAX_SIDE": "224",
    "TAKA_OBS_MAX_IMAGES": "60",
    "TAKA_CONTEXT_LIMIT": "163840",
    "TAKA_CONTEXT_RESERVE": "16384",
    "TAKA_MOTION_GRAY_WIDTH": "160",
    "TAKA_SEARCH_FOCUS_K": "4",
    "TAKA_SIMILAR_K": "4",
    "TAKA_TOOL_MAX_K": "100",
    "TAKA_SEARCH_MAX_QUERIES": "5",
    "TAKA_EXTRACT_MAX_INTERVALS": "5",
    "TAKA_CROP_MAX_REGIONS": "10",
    "TAKA_REVIEW_MAX_FRAMES": "3",
    "TAKA_ENHANCE_MAX_FRAMES": "3",
    "TAKA_CROP_MIN_SIDE": "448",
    "TAKA_CROP_MIN_BOX": "50",
    "TAKA_LOOP_WARN_AT": "3",
    "TAKA_LOOP_FAIL_AT": "5",
    "SEL_MAX_STEPS": "12",
    "SEL_MAX_REFLECT_REJECTS": "3",
    "TAKA_EXTRACT_UNIFORM_BROAD": "12",
    "TAKA_EXTRACT_MOTION_DEFAULT": "8",
    "TAKA_MOTION_MAX_RANGE": "120",
    "TAKA_SEARCH_COVER_BUDGET_SHORT": "12",
    "TAKA_SEARCH_COVER_BUDGET_MEDIUM": "20",
    "TAKA_SEARCH_COVER_BUDGET_LONG": "32",
    "TAKA_FRAME_LRU_CACHE_SIZE": "128",
    "TAKA_TORCH_THREADS": "4",
    "TAKA_DECODE_THREADS": "4",
    "TAKA_LLM_FAILOVER": "2",
    "TAKA_LLM_COOLDOWN_FAILS": "3",
    "TAKA_LLM_MAX_CONN_PER_EP": "32",
    "AGENT_MAX_TOKENS": "16384",
    "REFLECT_MAX_TOKENS": "16384",
    "LLM_TOP_K": "20",
    "TAKA_LLM_TIMEOUT": "300",
    "TAKA_LLM_COOLDOWN": "30",
    "TAKA_LLM_SLOW_FACTOR": "0",
    "TAKA_LLM_SLOW_MIN_SEC": "8",
    "SCENE_SIM_THRESHOLD": "0.8",
    "TAKA_SEARCH_COVER_MAXGAP_FRAC": "0.06",
    "TAKA_SIMILAR_EXCLUDE_SEC": "1.0",
    "TAKA_SIMILAR_MIN_GAP_SEC": "2.0",
    "AGENT_TEMPERATURE": "1.0",
    "AGENT_TOP_P": "0.95",
    "REFLECT_TEMPERATURE": "1.0",
    "REFLECT_TOP_P": "0.95",
    "LLM_PRESENCE_PENALTY": "1.5",
    "TAKA_DISABLE_THINKING": "0",
    "TAKA_KEEP_CONVERSATION_IMAGES": "0",
    "CLIP_FORCE_CPU": "0",
    "TAKA_FRAME_BUDGET_SHORT": "3-8",
    "TAKA_FRAME_BUDGET_MEDIUM": "4-12",
    "TAKA_FRAME_BUDGET_LONG": "6-16",
    "TAKA_RETRIEVER": "clip",
    "TAKA_DISABLE_TOOLS": "",
}


_EXERCISE_EVIDENCE_INSTRUCTIONS = """
### Open-ended exercise-form task
There are no answer candidates. Search the complete relevant timeline and gather visual
evidence for the user's question. For repeated exercise motion, cover representative
repetitions and then use motion extraction around the setup, transition, bottom/loaded
position, and return. Look for visible joint alignment, trunk/pelvis stability, left-right
symmetry, range of motion, balance, tempo changes, and repeated compensations. Camera
limitations are evidence limitations, not permission to guess. Submit the smallest
temporally ordered frame set that supports useful observations across the video.
""".strip()


def _as_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _notify(callback: Optional[ProgressCallback], stage: str, **details: Any) -> None:
    if callback is None:
        return
    try:
        callback(stage, details)
    except Exception:
        # Progress reporting must never fail the analysis.
        pass


def _endpoint_list(raw: str) -> List[str]:
    return [item.rstrip("/") for item in re.split(r"[\s,]+", raw.strip()) if item]


def configure_video_socrate_environment() -> None:
    """Populate the vendored runtime's required environment without overriding users."""

    cache_root = os.getenv(
        "V_SOCRATE_CACHE_DIR",
        str(_PROJECT_ROOT / ".cache" / "v_socrate"),
    )
    clip_model = os.getenv("V_SOCRATE_CLIP_MODEL", _DEFAULT_CLIP_MODEL)

    mapped_defaults = {
        **_TAKA_DEFAULTS,
        "TAKA_CACHE_ROOT": cache_root,
        "CLIP_MODEL_NAME": clip_model,
    }
    mapped_defaults["SEL_MAX_STEPS"] = os.getenv(
        "V_SOCRATE_MAX_STEPS", mapped_defaults["SEL_MAX_STEPS"]
    )
    mapped_defaults["SEL_MAX_REFLECT_REJECTS"] = os.getenv(
        "V_SOCRATE_MAX_REFLECT_REJECTS",
        mapped_defaults["SEL_MAX_REFLECT_REJECTS"],
    )
    mapped_defaults["CLIP_FORCE_CPU"] = os.getenv(
        "V_SOCRATE_CLIP_FORCE_CPU", mapped_defaults["CLIP_FORCE_CPU"]
    )

    for name, value in mapped_defaults.items():
        os.environ.setdefault(name, str(value))

    # Keep all model loading local and prevent tokenizer thread explosions in uvicorn.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("OMP_NUM_THREADS", os.environ["TAKA_TORCH_THREADS"])
    os.environ.setdefault("MKL_NUM_THREADS", os.environ["TAKA_TORCH_THREADS"])
    os.environ.setdefault("OPENBLAS_NUM_THREADS", os.environ["TAKA_TORCH_THREADS"])
    if os.getenv("V_SOCRATE_CUDA_VISIBLE_DEVICES"):
        os.environ.setdefault(
            "CUDA_VISIBLE_DEVICES", os.environ["V_SOCRATE_CUDA_VISIBLE_DEVICES"]
        )


class VideoSocrateService:
    """Lazy, process-local V-Socrate runtime with serialized GPU inference."""

    def __init__(self, *, use_mock: Optional[bool] = None) -> None:
        self.use_mock = (
            _as_bool(os.getenv("V_SOCRATE_USE_MOCK"))
            if use_mock is None
            else use_mock
        )
        self.enabled = _as_bool(os.getenv("V_SOCRATE_ENABLED"), default=True)
        self.model = os.getenv("V_SOCRATE_MODEL", "qwen3-vl-8b-instruct")
        self._load_lock = threading.Lock()
        self._inference_lock = threading.Lock()
        self._loaded = False
        self._retriever: Any = None
        self._preprocessor: Any = None
        self._llm: Any = None
        self._types: Dict[str, Any] = {}

    def _load_runtime(self) -> None:
        if self._loaded or self.use_mock:
            return
        if not self.enabled:
            raise VideoSocrateUnavailable(
                "视频理解功能未启用；请设置 V_SOCRATE_ENABLED=true。"
            )

        with self._load_lock:
            if self._loaded:
                return

            configure_video_socrate_environment()
            try:
                import decord  # noqa: F401

                from vendor.v_socrate_1020.agent.config_check import validate_env

                try:
                    validate_env()
                except SystemExit as exc:
                    raise VideoSocrateUnavailable(
                        "V-Socrate 配置校验失败，请检查 CLIP 路径和 TAKA/V_SOCRATE 环境变量。"
                    ) from exc

                from vendor.v_socrate_1020.agent.models.agent import (
                    QuestionFailed,
                    TAKAAgent,
                )
                from vendor.v_socrate_1020.agent.models.llm import LLMofAgent
                from vendor.v_socrate_1020.agent.models.retriever import (
                    cache_dir_for,
                    load_retriever,
                )
                from vendor.v_socrate_1020.agent.tools.agent_tools import (
                    InputDataError,
                    ToolRegistry,
                    VideoPreprocessor,
                )
                from vendor.v_socrate_1020.prompt.selector import (
                    get_duration_routing,
                    get_duration_section,
                )
            except VideoSocrateUnavailable:
                raise
            except (ImportError, OSError, RuntimeError) as exc:
                raise VideoSocrateUnavailable(
                    "V-Socrate 运行依赖不可用；请安装 requirements-video.txt，"
                    "并确认本地 CLIP 权重可读取。"
                ) from exc

            endpoints = _endpoint_list(
                os.getenv(
                    "V_SOCRATE_ENDPOINTS",
                    "http://127.0.0.1:8200/v1 http://127.0.0.1:8201/v1 "
                    "http://127.0.0.1:8202/v1 http://127.0.0.1:8203/v1",
                )
            )
            if not endpoints:
                raise VideoSocrateUnavailable("V_SOCRATE_ENDPOINTS 未配置。")

            Path(os.environ["TAKA_CACHE_ROOT"]).mkdir(parents=True, exist_ok=True)
            try:
                self._retriever = load_retriever()
                self._preprocessor = VideoPreprocessor(
                    self._retriever,
                    cache_dir=cache_dir_for("user_uploads"),
                    scene_sim_threshold=float(os.environ["SCENE_SIM_THRESHOLD"]),
                )
                self._llm = LLMofAgent(
                    config={
                        "model_name": self.model,
                        "base_url": endpoints,
                        "api_key": os.getenv("V_SOCRATE_API_KEY", "EMPTY"),
                        "temperature": float(os.environ["AGENT_TEMPERATURE"]),
                        "top_p": float(os.environ["AGENT_TOP_P"]),
                        "max_tokens": int(os.environ["AGENT_MAX_TOKENS"]),
                    }
                )
            except Exception as exc:
                raise VideoSocrateUnavailable(
                    f"V-Socrate 初始化失败：{type(exc).__name__}: {exc}"
                ) from exc

            self._types = {
                "InputDataError": InputDataError,
                "QuestionFailed": QuestionFailed,
                "TAKAAgent": TAKAAgent,
                "ToolRegistry": ToolRegistry,
                "get_duration_routing": get_duration_routing,
                "get_duration_section": get_duration_section,
            }
            self._loaded = True

    @staticmethod
    def _analysis_question(user_question: str) -> str:
        return (
            "请检查整段运动视频，并只根据可见画面提取能够回答问题的动作证据。"
            "需要覆盖有代表性的完整动作周期；若机位、遮挡或视频范围不足，请明确说明。"
            "不要做医学诊断，也不要推断画面中看不见的疼痛或受力。\n\n"
            f"用户问题：{user_question.strip()}"
        )

    def _mock_analysis(self, processing_seconds: float) -> VideoAnalysisResult:
        return VideoAnalysisResult(
            model="V-Socrate-1020-mock",
            summary=(
                "当前为视频分析 Mock 模式，未执行真实逐帧视觉理解。"
                "请配置 Qwen 多模态 vLLM 与 CLIP 后再据此判断动作。"
            ),
            reason="Mock 模式不提供任何视频证据，最终回答只能给出一般性安全建议。",
            evidence_frames=[],
            duration_seconds=0.0,
            processing_seconds=processing_seconds,
            mock=True,
        )

    def analyze(
        self,
        video_path: Path,
        question: str,
        *,
        content_hash: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> VideoAnalysisResult:
        """Analyse one uploaded video and return evidence-grounded text observations."""

        started = time.monotonic()
        if not video_path.is_file():
            raise VideoSocrateInputError("上传的视频临时文件不存在。")
        if not question.strip():
            raise VideoSocrateInputError("问题不能为空。")
        if self.use_mock:
            _notify(progress_callback, "mock")
            return self._mock_analysis(time.monotonic() - started)

        self._load_runtime()
        sample_fps = float(os.getenv("V_SOCRATE_SAMPLE_FPS", "1.0"))
        max_steps = int(os.getenv("V_SOCRATE_MAX_STEPS", os.environ["SEL_MAX_STEPS"]))
        max_rejects = int(
            os.getenv(
                "V_SOCRATE_MAX_REFLECT_REJECTS",
                os.environ["SEL_MAX_REFLECT_REJECTS"],
            )
        )
        visual_question = self._analysis_question(question)
        video_index = None

        # CLIP, Decord and the vendored CropStore are process-local mutable GPU/runtime
        # objects. Serialize a request from preprocessing through disposal.
        with self._inference_lock:
            try:
                _notify(progress_callback, "preprocessing")
                video_id = f"upload_{content_hash[:24]}"
                video_index = self._preprocessor.process(
                    str(video_path),
                    sample_fps=sample_fps,
                    video_id=video_id,
                    cache_key_override=f"{content_hash}:fps={sample_fps}",
                )

                _notify(
                    progress_callback,
                    "reasoning",
                    duration_seconds=video_index.total_duration,
                )
                registry = self._types["ToolRegistry"](
                    video_index,
                    self._retriever,
                    video_path=str(video_path),
                    question=visual_question,
                )
                agent = self._types["TAKAAgent"](
                    registry,
                    self._llm,
                    video_index,
                    verbose=False,
                )
                route = self._types["get_duration_routing"](
                    video_index.total_duration
                )
                selected, _conversation, reflection, _history = agent.run(
                    question=visual_question,
                    candidates=None,
                    max_steps=max_steps,
                    max_reflect_rejects=max_rejects,
                    step_callback=(
                        lambda step, total, tool: _notify(
                            progress_callback,
                            "reasoning",
                            step=step,
                            total_steps=total,
                            tool=tool,
                        )
                    ),
                    use_long_video_section=route["long_video_section"],
                    react_video_section=self._types["get_duration_section"](
                        video_index.total_duration
                    ),
                    react_task_section=_EXERCISE_EVIDENCE_INSTRUCTIONS,
                    qid=video_id,
                    duration_guidance=True,
                    reflect_temperature=float(os.environ["REFLECT_TEMPERATURE"]),
                    reflect_top_p=float(os.environ["REFLECT_TOP_P"]),
                    reflect_max_tokens=int(os.environ["REFLECT_MAX_TOKENS"]),
                )
                answer = reflection.get("answer") or {}
                summary = str(answer.get("text") or "").strip()
                reason = str(reflection.get("reason") or "").strip()
                if not summary or not reason or not selected:
                    raise VideoSocrateError("V-Socrate 未返回完整的可验证视频证据。")

                evidence = [
                    EvidenceFrame(
                        frame_id=int(frame_id),
                        timestamp_seconds=round(
                            float(video_index.frame_time(frame_id)), 3
                        ),
                    )
                    for frame_id in reflection.get("evidence_frame_ids", selected)
                ]
                _notify(progress_callback, "complete", evidence_count=len(evidence))
                return VideoAnalysisResult(
                    model=self.model,
                    summary=summary,
                    reason=reason,
                    evidence_frames=evidence,
                    duration_seconds=round(float(video_index.total_duration), 3),
                    processing_seconds=round(time.monotonic() - started, 3),
                )
            except self._types["InputDataError"] as exc:
                raise VideoSocrateInputError(str(exc)) from exc
            except self._types["QuestionFailed"] as exc:
                raise VideoSocrateError(
                    f"V-Socrate 无法形成可靠结论：{exc.failed_type}"
                ) from exc
            except VideoSocrateError:
                raise
            except Exception as exc:
                raise VideoSocrateError(
                    f"V-Socrate 推理失败：{type(exc).__name__}: {exc}"
                ) from exc
            finally:
                if video_index is not None:
                    video_index.dispose()


_service: Optional[VideoSocrateService] = None
_service_lock = threading.Lock()


def get_video_socrate_service() -> VideoSocrateService:
    """FastAPI dependency and process singleton."""

    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = VideoSocrateService()
    return _service
