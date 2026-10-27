from __future__ import annotations

import bisect
import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from .tool_schema import (
    CROP_BOX_SCALE,
    EXTRACT_MAX_FRAMES,
    REVIEW_MAX_FRAMES,
    ENHANCE_MAX_FRAMES,
    SEARCH_COVER_MAX_K,
    SEARCH_MAX_QUERIES,
    EXTRACT_MAX_INTERVALS,
    CROP_MAX_REGIONS,
    SEARCH_FOCUS_DEFAULT_K,
    SEARCH_FOCUS_MAX_K,
    SIMILAR_DEFAULT_K,
    SIMILAR_MAX_K,
    cover_budget_for,
    env_float,
    env_int,
    env_tool_set,
    get_openai_tools,
    get_tools_description,
)

# ── 解码线程限制（防线程爆炸）──────────────────────────────────────
# 现象（实测）：每个解码上下文默认开一批 frame-level 多线程解码线程。48 个并发
# worker 同时解码 → 几百解码线程 >> CPU 核数，饿死等 LLM 响应的网络 I/O 线程。
# 由 TAKA_DECODE_THREADS 控制（必须在 common_env.sh 中设置）：
#   Decord VideoReader(num_threads=max(1, N))；cv2.setNumThreads(N) 只影响 resize 等。
_DECODE_THREADS = env_int("TAKA_DECODE_THREADS")
if _DECODE_THREADS >= 0:
    cv2.setNumThreads(_DECODE_THREADS)


class InputDataError(Exception):
    """Input data problem (video cannot be opened/decoded/seeked, truncated video,
    corrupted preprocess cache). The runner marks the question status=failed,
    failed_type=input_data_error. Never converted into a tool error."""


class ToolFeedback(Exception):
    """A tool call that cannot produce frames for the given arguments (no scene hit,
    empty time range, no motion peak, ...). ToolRegistry.execute returns it to the
    agent as a tool error so the agent can choose a different call."""


def _open_reader(path, what: str):
    """Decord VideoReader for frame-accurate random access.

    OpenCV 4.5.5 cap.set(CAP_PROP_POS_FRAMES) lands on the wrong frame on most of our
    videos (31/32 random seeks wrong on VideoMME; HEVC with B-frames overshoots to EOF
    on LVB) and cannot read frame 0 of any VideoMME file, so tool frames are decoded
    with Decord only. Imported lazily: torch/BLIP must be loaded before Decord."""
    with open(path, "rb") as f:
        head = f.read(12)
    if head[4:8] == b"ftyp" and head[8:12] == b"dash":
        # Fragmented (DASH) mp4: Decord seeks land up to ~3 s off on 10-25% of frames
        # (measured on LVB). A lossless remux (ffmpeg -c copy) makes them frame-accurate.
        raise InputDataError(f"fragmented (DASH) mp4, random access is not frame-accurate: {path}; "
                             f"remux it first (ffmpeg -i in.mp4 -c copy -movflags +faststart out.mp4)")
    try:
        from decord import VideoReader, cpu
        vr = VideoReader(path, ctx=cpu(0), num_threads=max(1, _DECODE_THREADS))
    except Exception as exc:
        raise InputDataError(f"cannot open video for {what}: {path}: {type(exc).__name__}: {exc}") from exc
    if len(vr) <= 0:
        raise InputDataError(f"Decord found 0 frames in {path} ({what})")
    return vr


def _batch_to_numpy(batch) -> np.ndarray:
    """Decord get_batch result as (N, H, W, 3) uint8 RGB. LAVIS may switch Decord's
    bridge to torch globally; a vanilla Decord process returns an NDArray."""
    if hasattr(batch, "asnumpy"):
        return batch.asnumpy()
    if hasattr(batch, "detach"):
        return batch.detach().cpu().numpy()
    return np.asarray(batch)


@dataclass
class Scene:
    scene_id: int
    start_frame: int
    end_frame: int
    start_time: float
    end_time: float
    representative_frame_idx: int
    centroid_embedding: Optional[np.ndarray] = None


@dataclass
class ToolResult:
    success: bool
    data: Dict[str, Any]
    images: List[Tuple[int, Image.Image]]
    text_summary: str
    terminal: bool = False
    crops: List[Tuple[str, Image.Image]] = field(default_factory=list)   # (crop_id, image)
    lead: bool = False   # True: search previews, shown to the Selector at TAKA_LEAD_MAX_SIDE
    max_side: Optional[int] = None   # set: shown to the Selector at this long side (Enhance)


class VideoIndex:
    """Index over sampled-frame embeddings/scenes with lazy frame decoding.

    All decoding goes through ONE persistent Decord reader per index (opened on the
    first decode, released by dispose()): the videos sit on a network file system, so
    re-opening the mp4 for every frame was the dominant per-frame cost. get_frames()
    decodes a batch in ascending order with get_batch (frame-accurate random access).
    A frame id past the last frame of the video is a ToolFeedback, never clamped.
    """

    # Frames per get_batch call: bounds the temporary (N, H, W, 3) buffer.
    DECODE_CHUNK = 32

    def __init__(
        self,
        frames: Optional[List[Tuple[int, np.ndarray]]],
        scenes: List[Scene],
        embeddings: np.ndarray,
        video_fps: float,
        *,
        frame_indices: Optional[np.ndarray | List[int]] = None,
        video_path: Optional[str] = None,
        frame_cache_size: Optional[int] = None,
    ) -> None:
        self.video_path = video_path
        self.scenes = scenes
        self.embeddings = embeddings.astype(np.float32, copy=False)
        self.video_fps = float(video_fps or 24.0)
        if frame_indices is None:
            frame_indices = [idx for idx, _ in (frames or [])]
        self._frame_indices = np.array(frame_indices, dtype=np.int64)
        self.frames = [(int(idx), None) for idx in self._frame_indices]
        self._frame_times = self._frame_indices / self.video_fps
        self._frame_cache_size = int(
            frame_cache_size or env_int("TAKA_FRAME_LRU_CACHE_SIZE")
        )
        self._pil_cache: OrderedDict[int, Image.Image] = OrderedDict()
        self._static_frames: Dict[int, np.ndarray] = {}
        self._idx_to_pos = {int(idx): pos for pos, idx in enumerate(self._frame_indices)}
        self._scene_starts = np.array([int(s.start_frame) for s in scenes], dtype=np.int64)
        self._reader = None
        self._reader_lock = threading.Lock()
        if frames:
            for frame_idx, image in frames:
                self.add_frame(frame_idx, image)

        centroids = [
            scene.centroid_embedding
            for scene in scenes
            if scene.centroid_embedding is not None
        ]
        if centroids:
            self.scene_centroids = np.stack(centroids, axis=0).astype(np.float32)
        else:
            dim = self.embeddings.shape[1] if self.embeddings.ndim == 2 else 0
            self.scene_centroids = np.zeros((0, dim), dtype=np.float32)

    @property
    def total_duration(self) -> float:
        if len(self._frame_indices) == 0:
            return 0.0
        return float(self._frame_indices[-1] / self.video_fps)

    @property
    def video_end_sec(self) -> float:
        """Time of the last frame of the video file (Decord frame count)."""
        return (self.num_video_frames - 1) / self.video_fps

    @property
    def last_frame_idx(self) -> int:
        """Last frame known to decode (the last 1-fps sample written by preprocessing)."""
        return int(self._frame_indices[-1]) if len(self._frame_indices) else -1

    @staticmethod
    def _to_pil(image: np.ndarray) -> Image.Image:
        if image.dtype != np.uint8:
            image = np.clip(image, 0, 255).astype(np.uint8)
        return Image.fromarray(image).convert("RGB")

    def add_frame(self, frame_idx: int, image: Image.Image | np.ndarray) -> None:
        idx = int(frame_idx)
        if isinstance(image, Image.Image):
            pil = image.convert("RGB")
            if not self.video_path:
                self._static_frames[idx] = np.asarray(pil)
        else:
            arr = image
            if arr.dtype != np.uint8:
                arr = np.clip(arr, 0, 255).astype(np.uint8)
            pil = Image.fromarray(arr).convert("RGB")
            if not self.video_path:
                self._static_frames[idx] = arr
        self._remember_frame(idx, pil)

    def get_frame(self, frame_idx: int) -> Image.Image:
        """Return the frame; raises InputDataError if it cannot be decoded."""
        return self.get_frames([frame_idx])[0][1]

    def get_frames(self, frame_ids) -> List[Tuple[int, Image.Image]]:
        """Return [(frame_id, image)] sorted by frame id (duplicates removed).

        Cached frames come from the LRU; the rest are decoded in one ordered pass.
        Raises InputDataError on the first frame that cannot be decoded."""
        ids = sorted({int(x) for x in frame_ids})
        found: Dict[int, Image.Image] = {}
        missing: List[int] = []
        for idx in ids:
            if idx in self._pil_cache:
                found[idx] = self._pil_cache.pop(idx)
                self._pil_cache[idx] = found[idx]
            elif idx in self._static_frames:
                found[idx] = self._to_pil(self._static_frames[idx])
                self._remember_frame(idx, found[idx])
            else:
                missing.append(idx)
        if missing:
            decoded: List[Tuple[int, Image.Image]] = []
            self.scan_frames(
                missing,
                lambda idx, rgb: decoded.append((idx, Image.fromarray(rgb))),
                what="frame decode",
            )
            for idx, img in decoded:
                self._remember_frame(idx, img)
                found[idx] = img
        return [(idx, found[idx]) for idx in ids]

    def scan_frames(self, frame_ids, on_frame, *, what: str) -> None:
        """Decode frame_ids in ascending order, calling on_frame(idx, rgb_ndarray) for each.

        Does not cache: callers that only need a statistic per frame (motion scores)
        keep nothing but that statistic. A frame id outside [0, num_video_frames) is a
        ToolFeedback naming the video's end; a decode failure is an InputDataError
        (no rescans, no alternative decoder)."""
        if not self.video_path:
            raise InputDataError(f"frames {sorted(frame_ids)[:5]} are not in the in-memory index (no video_path)")
        ids = sorted({int(x) for x in frame_ids})
        if not ids:
            return
        with self._reader_lock:
            vr = self._open(what)
            n = len(vr)
            outside = [idx for idx in ids if not 0 <= idx < n]
            if outside:
                raise ToolFeedback(
                    f"frame {outside[0]} is outside the video: valid frame ids are 0-{n - 1} "
                    f"(the video ends at {(n - 1) / self.video_fps:.1f}s).")
            for start in range(0, len(ids), self.DECODE_CHUNK):
                chunk = ids[start: start + self.DECODE_CHUNK]
                try:
                    batch = _batch_to_numpy(vr.get_batch(chunk))
                except Exception as exc:
                    raise InputDataError(f"decode failed: frames {chunk[0]}-{chunk[-1]} of "
                                         f"{self.video_path}: {type(exc).__name__}: {exc}") from exc
                if batch.shape[0] != len(chunk):
                    raise InputDataError(f"decode returned {batch.shape[0]} frames for {len(chunk)} "
                                         f"requested ({chunk[0]}-{chunk[-1]}) of {self.video_path}")
                for idx, rgb in zip(chunk, batch):
                    on_frame(idx, rgb)

    def _open(self, what: str):
        """The cached reader (caller holds _reader_lock)."""
        if self._reader is None:
            self._reader = _open_reader(self.video_path, what)
        return self._reader

    @property
    def num_video_frames(self) -> int:
        """Frame count of the video file (Decord); the 1-fps count without a video_path."""
        if not self.video_path:
            return self.last_frame_idx + 1
        with self._reader_lock:
            return len(self._open("frame count"))

    def _remember_frame(self, frame_idx: int, image: Image.Image) -> None:
        if self._frame_cache_size <= 0:
            return
        idx = int(frame_idx)
        if idx in self._pil_cache:
            self._pil_cache.pop(idx)
        self._pil_cache[idx] = image.convert("RGB")
        while len(self._pil_cache) > self._frame_cache_size:
            self._pil_cache.popitem(last=False)

    def dispose(self) -> None:
        """Release all per-video buffers so a finished video's memory is reclaimed.

        Decoded frames (native 1280x720 PIL/np) accumulate in _pil_cache /
        _static_frames; embeddings/centroids are large numpy arrays. With 48
        concurrent workers over 2700 videos, not dropping these caused a multi-TB
        RSS leak that exhausted host memory (ffmpeg swscaler EAGAIN -> selection
        stall). Call this after each video is fully processed, then gc.collect().
        """
        with self._reader_lock:
            self._reader = None   # Decord frees the demuxer/decoder when the reader is dropped
        try:
            self._pil_cache.clear()
        except Exception:
            pass
        try:
            self._static_frames.clear()
        except Exception:
            pass
        self.embeddings = np.zeros((0, 0), dtype=np.float32)
        self.scene_centroids = np.zeros((0, 0), dtype=np.float32)

    def frame_time(self, frame_idx: int) -> float:
        return float(frame_idx) / self.video_fps

    def positions_in_window(self, start_time: float, end_time: float) -> np.ndarray:
        """Positions (into the 1-fps arrays) of sampled frames inside [start, end]."""
        mask = (self._frame_times >= start_time) & (self._frame_times <= end_time)
        return np.where(mask)[0]

    def scene_index_of(self, frame_ids: np.ndarray) -> np.ndarray:
        """Index into self.scenes of the scene containing each frame id."""
        return np.searchsorted(self._scene_starts, frame_ids, side="right") - 1

    def get_frames_in_range(self, start_time: float, end_time: float) -> List[Tuple[int, Image.Image]]:
        positions = self.positions_in_window(start_time, end_time)
        return self.get_frames(self._frame_indices[positions].tolist())

    def scene_for_frame(self, frame_idx: int) -> Optional[Scene]:
        for scene in self.scenes:
            if scene.start_frame <= frame_idx <= scene.end_frame:
                return scene
        return None

    def search(
        self,
        query_embedding: np.ndarray,
        *,
        top_k: int,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> List[Tuple[int, float]]:
        if self.embeddings.size == 0:
            return []
        mask = np.ones(len(self._frame_indices), dtype=bool)
        if start_time is not None:
            mask &= self._frame_times >= float(start_time)
        if end_time is not None:
            mask &= self._frame_times <= float(end_time)
        valid = np.where(mask)[0]
        if len(valid) == 0:
            return []
        sims = (self.embeddings[valid] @ query_embedding.reshape(-1, 1)).reshape(-1)
        k = min(max(1, int(top_k)), len(sims))
        top_pos = np.argsort(sims)[-k:][::-1]
        return [(int(self._frame_indices[valid[pos]]), float(sims[pos])) for pos in top_pos]


class VideoPreprocessor:
    """Sample frames, encode CLIP features, split scenes, and cache the index."""

    CACHE_VERSION = "taka0516_preprocess_v1"

    def __init__(self, clip_tool, *, cache_dir: str, scene_sim_threshold: float = 0.8) -> None:
        """cache_dir: where VideoIndex caches live (<TAKA_CACHE_ROOT>/<dataset>); one
        <video_id>.json + <video_id>.npz per video."""
        self.clip = clip_tool
        self.cache_dir = cache_dir
        self.scene_sim_threshold = float(scene_sim_threshold)

    def process(
        self,
        video_path: str,
        *,
        sample_fps: float = 1.0,
        batch_size: int = 32,
        video_id: Optional[str] = None,
        require_cache: bool = False,
        cache_key_override: Optional[str] = None,
    ) -> VideoIndex:
        if not os.path.isfile(video_path):
            raise FileNotFoundError(video_path)
        cache_dir = self.cache_dir
        vid = video_id or os.path.splitext(os.path.basename(video_path))[0]
        # Application uploads are written to a fresh temporary path for every request.
        # Let the caller key the cache by the file content hash so an identical upload can
        # reuse its index without retaining the original video.
        cache_key = cache_key_override or self._cache_key(video_path, sample_fps)
        cached = self._load_cache(cache_dir, vid, cache_key, video_path, sample_fps)
        if cached is not None:
            print(f"[Preprocess] cache hit: {vid}")
            return cached
        if require_cache:
            raise RuntimeError(
                f"Preprocess cache miss for {vid}; run scripts/preprocess_cache.py first or disable --require-cache."
            )

        print(f"[Preprocess] cache miss: {vid}")
        frames, video_fps = self._sample_frames(video_path, sample_fps)
        if not frames:
            raise InputDataError(f"No frames extracted from {video_path}")
        embeddings = self._batch_embed(frames, batch_size)
        scenes = self._split_scenes(frames, embeddings, video_fps)
        self._compute_centroids(scenes, frames, embeddings)
        self._save_cache(cache_dir, vid, cache_key, frames, embeddings, scenes, video_fps)
        frame_indices = [idx for idx, _ in frames]
        return VideoIndex(
            None,
            scenes,
            embeddings,
            video_fps,
            frame_indices=frame_indices,
            video_path=video_path,
        )

    @classmethod
    def _cache_key(cls, video_path: str, sample_fps: float) -> str:
        raw = f"{os.path.abspath(video_path)}|fps={sample_fps}|ver={cls.CACHE_VERSION}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _sample_frames(video_path: str, fps: float) -> Tuple[List[Tuple[int, np.ndarray]], float]:
        """1-fps samples (every int(video_fps / fps)-th frame from frame 0), decoded with
        the same Decord reader the tools use, so the embedded frame and the frame shown
        for a frame id are the same picture."""
        vr = _open_reader(video_path, "preprocessing")
        try:
            video_fps = float(vr.get_avg_fps() or 24.0)
            interval = max(1, int(video_fps / max(float(fps), 1e-6)))
            indices = list(range(0, len(vr), interval))
            frames: List[Tuple[int, np.ndarray]] = []
            # Chunked: one giant batch on an hour-long video is a multi-GB temporary.
            for start in range(0, len(indices), 64):
                batch_ids = indices[start: start + 64]
                batch = _batch_to_numpy(vr.get_batch(batch_ids))
                frames.extend((int(fid), batch[i]) for i, fid in enumerate(batch_ids))
            return frames, video_fps
        except Exception as exc:
            raise InputDataError(f"Decord failed to decode {video_path}: {type(exc).__name__}: {exc}") from exc
        finally:
            del vr

    def _batch_embed(self, frames: List[Tuple[int, np.ndarray]], batch_size: int) -> np.ndarray:
        images = [img for _, img in frames]
        parts = []
        for start in range(0, len(images), batch_size):
            feats = self.clip.extract_frame_features(images[start : start + batch_size])
            parts.append(feats.cpu().numpy())
        return np.concatenate(parts, axis=0).astype(np.float32)

    def _split_scenes(
        self,
        frames: List[Tuple[int, np.ndarray]],
        embeddings: np.ndarray,
        video_fps: float,
    ) -> List[Scene]:
        if len(frames) == 1:
            idx = int(frames[0][0])
            t = idx / video_fps
            return [Scene(0, idx, idx, t, t, idx)]

        boundaries = [0]
        for i in range(1, len(frames)):
            sim = float(embeddings[i] @ embeddings[i - 1])
            if sim < self.scene_sim_threshold:
                boundaries.append(i)
        boundaries.append(len(frames))

        frame_indices = [int(idx) for idx, _ in frames]
        scenes: List[Scene] = []
        for sid, (start_pos, end_next) in enumerate(zip(boundaries[:-1], boundaries[1:])):
            end_pos = end_next - 1
            mid_pos = (start_pos + end_pos) // 2
            start_idx = frame_indices[start_pos]
            end_idx = frame_indices[end_pos]
            scenes.append(
                Scene(
                    scene_id=sid,
                    start_frame=start_idx,
                    end_frame=end_idx,
                    start_time=start_idx / video_fps,
                    end_time=end_idx / video_fps,
                    representative_frame_idx=frame_indices[mid_pos],
                )
            )
        return scenes

    @staticmethod
    def _compute_centroids(
        scenes: List[Scene],
        frames: List[Tuple[int, np.ndarray]],
        embeddings: np.ndarray,
    ) -> None:
        idx_to_pos = {int(idx): pos for pos, (idx, _) in enumerate(frames)}
        for scene in scenes:
            positions = [
                idx_to_pos[int(idx)]
                for idx, _ in frames
                if scene.start_frame <= int(idx) <= scene.end_frame
            ]
            if not positions:
                continue
            anchors = [positions[0]]
            if len(positions) > 2:
                anchors.append(positions[len(positions) // 2])
            if len(positions) > 1:
                anchors.append(positions[-1])
            centroid = embeddings[anchors].mean(axis=0)
            norm = np.linalg.norm(centroid)
            scene.centroid_embedding = centroid / norm if norm > 0 else centroid

    def _save_cache(
        self,
        cache_dir: str,
        video_id: str,
        cache_key: str,
        frames: List[Tuple[int, np.ndarray]],
        embeddings: np.ndarray,
        scenes: List[Scene],
        video_fps: float,
    ) -> None:
        os.makedirs(cache_dir, exist_ok=True)
        prefix = os.path.join(cache_dir, video_id)
        frame_indices = np.array([idx for idx, _ in frames], dtype=np.int64)
        centroids = [
            scene.centroid_embedding if scene.centroid_embedding is not None else np.zeros(embeddings.shape[1])
            for scene in scenes
        ]
        scene_centroids = np.stack(centroids, axis=0).astype(np.float32) if centroids else np.zeros((0, 0))
        np.savez_compressed(
            f"{prefix}.npz",
            embeddings=embeddings,
            frame_indices=frame_indices,
            scene_centroids=scene_centroids,
        )
        meta = {
            "cache_key": cache_key,
            "retriever": getattr(self.clip, "retriever_name", "clip"),
            "video_fps": video_fps,
            "num_frames": len(frames),
            "scenes": [
                {
                    "scene_id": scene.scene_id,
                    "start_frame": scene.start_frame,
                    "end_frame": scene.end_frame,
                    "start_time": scene.start_time,
                    "end_time": scene.end_time,
                    "representative_frame_idx": scene.representative_frame_idx,
                }
                for scene in scenes
            ],
        }
        with open(f"{prefix}.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _load_cache(
        self,
        cache_dir: str,
        video_id: str,
        cache_key: str,
        video_path: str,
        sample_fps: float,
    ) -> Optional[VideoIndex]:
        prefix = os.path.join(cache_dir, video_id)
        npz_path = f"{prefix}.npz"
        json_path = f"{prefix}.json"
        if not os.path.isfile(npz_path) or not os.path.isfile(json_path):
            return None
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as exc:
            raise InputDataError(f"corrupted preprocess cache {json_path}: {exc}")
        if meta.get("cache_key") != cache_key:
            return None      # cache of another (path, fps, version): rebuild, not an error
        try:
            with np.load(npz_path, allow_pickle=False) as data:
                embeddings = data["embeddings"].astype(np.float32)
                frame_indices = data["frame_indices"].astype(np.int64)
                scene_centroids = data["scene_centroids"].astype(np.float32)
            want = getattr(self.clip, "retriever_name", "clip")
            have = meta.get("retriever", "clip")
            if have != want:
                raise InputDataError(f"cache {json_path} was built with retriever={have}, "
                                     f"current TAKA_RETRIEVER={want} (wrong cache dir?)")
            dim = getattr(self.clip, "embed_dim", None)
            if dim is not None and embeddings.shape[-1] != dim:
                raise InputDataError(f"cache {npz_path}: embedding dim {embeddings.shape[-1]} != {dim} for {want}")
            if len(frame_indices) != int(meta.get("num_frames", -1)):
                raise InputDataError(f"inconsistent preprocess cache {npz_path}: "
                                     f"{len(frame_indices)} frames vs num_frames={meta.get('num_frames')}")
            scenes: List[Scene] = []
            for i, item in enumerate(meta["scenes"]):
                centroid = scene_centroids[i] if i < len(scene_centroids) else None
                scenes.append(
                    Scene(
                        scene_id=item["scene_id"],
                        start_frame=item["start_frame"],
                        end_frame=item["end_frame"],
                        start_time=item["start_time"],
                        end_time=item["end_time"],
                        representative_frame_idx=item["representative_frame_idx"],
                        centroid_embedding=centroid,
                    )
                )
            return VideoIndex(
                None,
                scenes,
                embeddings,
                float(meta.get("video_fps", 24.0)),
                frame_indices=frame_indices,
                video_path=video_path,
            )
        except InputDataError:
            raise
        except Exception as exc:
            raise InputDataError(f"corrupted preprocess cache {npz_path}: {exc}")


def _as_time(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ToolFeedback(f"{name}={value!r} is not a number of seconds")


def _time_window(vi: VideoIndex, start_time: Any, end_time: Any) -> Tuple[float, float]:
    """Validated [start, end] window; omitted bounds default to the whole video."""
    start = 0.0 if start_time is None else max(0.0, _as_time(start_time, "start_time"))
    end = vi.total_duration if end_time is None else _as_time(end_time, "end_time")
    if end < start:
        raise ToolFeedback(f"invalid time range: start_time={start} must be <= end_time={end}")
    return start, end


def _as_count(value: Any, name: str, default: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ToolFeedback(f"{name}={value!r} must be an integer")
    count = int(value)
    if not 1 <= count <= maximum:
        raise ToolFeedback(f"{name}={count} must be between 1 and {maximum}")
    return count


def _as_text_list(value: Any, name: str, maximum: int) -> List[str]:
    """Non-empty strings from a list (a bare string is accepted as one item)."""
    if value is None:
        return []
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or any(not isinstance(x, str) for x in items):
        raise ToolFeedback(f"{name}={value!r} must be a list of strings")
    texts = list(dict.fromkeys(x.strip() for x in items if x.strip()))   # order kept, repeats dropped
    if len(texts) > maximum:
        raise ToolFeedback(f"at most {maximum} {name} per call")
    return texts


def _check_obs_images(n_images: int) -> None:
    """One observation may carry at most TAKA_OBS_MAX_IMAGES images (bounds a batch's tokens)."""
    cap = env_int("TAKA_OBS_MAX_IMAGES")
    if n_images > cap:
        raise ToolFeedback(f"this call would return {n_images} images; one observation holds at "
                           f"most {cap}. Use fewer queries / intervals / regions, or a smaller k / max_frames.")


def _as_frame_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ToolFeedback(f"frame_id={value!r} must be an integer frame id")
    return int(value)


def _frame_lines(vi: VideoIndex, frames: List[Tuple[int, Image.Image]]) -> List[str]:
    return [f"  Frame {fid} @ {vi.frame_time(fid):.1f}s" for fid, _ in frames]


class SearchTool:
    """Search(queries, mode, k, start_time, end_time) over the cached 1-fps embeddings.

    queries are required in both modes (no default to the question text).
    focus: per query, per-frame text similarity -> best frame of each scene -> top-k scenes.
    cover: the scene-adaptive coverage selection (formerly Scaffold) restricted to the
           window, scoring each frame by its best match over the queries, with k as its
           budget, then the gap-filling coverage floor.
    No online dense re-ranking: every returned frame is a 1-fps sample. Frames of all
    queries are merged (deduplicated) into one observation and decoded in one pass."""


    def __init__(self, video_index: VideoIndex, clip_tool, *, question: str = "") -> None:
        self.vi = video_index
        self.clip = clip_tool
        self.question = question or ""

    def __call__(
        self,
        queries: Optional[List[str]] = None,
        mode: str = "focus",
        k: Optional[int] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> ToolResult:
        mode = str(mode).strip().lower()
        if mode not in ("focus", "cover"):
            raise ToolFeedback(f"mode={mode!r}; use \"focus\" or \"cover\"")
        texts = _as_text_list(queries, "queries", SEARCH_MAX_QUERIES)
        if not texts:
            raise ToolFeedback("queries is required: pass a list of short descriptions of what is "
                               "visible, e.g. {\"queries\": [\"a man in a black suit at a podium\"]}.")
        too_long = getattr(self.clip, "query_too_long", None)
        if callable(too_long):
            for text in texts:
                reason = too_long(text)
                if reason:
                    raise ToolFeedback(f"query '{text[:60]}...' is too long ({reason}). Use short "
                                       f"queries that describe what is visible; split separate "
                                       f"events into separate queries.")
        start, end = _time_window(self.vi, start_time, end_time)
        positions = self.vi.positions_in_window(start, end)
        if len(positions) == 0:
            raise ToolFeedback(f"no sampled frames in [{start:.1f}s, {end:.1f}s] "
                               f"(video is {self.vi.total_duration:.1f}s long).")
        q_mat = self._encode(texts)
        if mode == "focus":
            count = _as_count(k, "k", SEARCH_FOCUS_DEFAULT_K, SEARCH_FOCUS_MAX_K)
            _check_obs_images(min(count, len(positions)) * len(texts))
            return self._focus(texts, q_mat, positions, start, end, count)
        budget = _as_count(k, "k", cover_budget_for(self.vi.total_duration), SEARCH_COVER_MAX_K)
        _check_obs_images(min(budget, len(positions)))
        return self._cover(texts, q_mat, positions, start, end, budget)

    def _encode(self, texts: List[str]) -> np.ndarray:
        encode_many = getattr(self.clip, "encode_texts", None)
        if callable(encode_many):
            mat = np.asarray(encode_many(texts), dtype=np.float32)
        else:
            mat = np.stack([np.asarray(self.clip.encode_text(t), dtype=np.float32).reshape(-1) for t in texts])
        return mat.reshape(len(texts), -1)

    def _focus(self, texts, q_mat, positions, start, end, k) -> ToolResult:
        frame_ids = self.vi._frame_indices[positions]
        scene_idx = self.vi.scene_index_of(frame_ids)
        all_sims = self.vi.embeddings[positions] @ q_mat.T          # (frames, queries)
        lines = [f"Search focus in [{start:.1f}s, {end:.1f}s], {k} scene(s) per query, best first:"]
        segments, wanted = [], []
        for qi, text in enumerate(texts):
            sims = all_sims[:, qi]
            seen, hits = set(), []
            for pos in np.argsort(sims)[::-1]:
                sid = int(scene_idx[pos])
                if sid in seen:
                    continue
                seen.add(sid)
                hits.append((sid, int(frame_ids[pos]), float(sims[pos])))
                if len(hits) >= k:
                    break
            lines.append(f"Query '{text}':")
            for sid, fid, score in hits:
                scene = self.vi.scenes[sid]
                lines.append(f"  Frame {fid} @ {self.vi.frame_time(fid):.1f}s  "
                             f"scene [{scene.start_time:.1f}s-{scene.end_time:.1f}s]  score={score:.3f}")
                segments.append({"query": text, "scene_id": scene.scene_id, "best_frame": fid,
                                 "score": round(score, 4)})
                wanted.append(fid)
        images = self.vi.get_frames(wanted)
        return ToolResult(True, {"mode": "focus", "segments": segments}, images, "\n".join(lines), lead=True)

    def _cover(self, texts, q_mat, positions, start, end, budget) -> ToolResult:
        frames, info = _scene_adaptive_select(self.vi, q_mat, budget, positions)
        frames = _coverage_floor(self.vi._frame_indices[positions].tolist(), frames, budget,
                                 env_float("TAKA_SEARCH_COVER_MAXGAP_FRAC"))
        images = self.vi.get_frames(frames)
        shown = "; ".join(f"'{t}'" for t in texts)
        lines = [f"Search cover {shown} in [{start:.1f}s, {end:.1f}s]: {len(images)} frames "
                 f"over {info['valid_scenes']} scenes (mode={info['mode']}), in temporal order:"]
        lines += _frame_lines(self.vi, images)
        return ToolResult(True, {"mode": "cover", "frame_ids": [fid for fid, _ in images], **info},
                          images, "\n".join(lines), lead=True)


class SimilarTool:
    """Similar(frame_id, k, start_time, end_time): image-to-image search on the 1-fps index."""

    def __init__(self, video_index: VideoIndex, clip_tool, returned_ids: set) -> None:
        self.vi = video_index
        self.clip = clip_tool
        self.returned_ids = returned_ids

    def __call__(
        self,
        frame_id: int,
        k: Optional[int] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> ToolResult:
        fid = _as_frame_id(frame_id)
        if fid not in self.returned_ids:
            raise ToolFeedback(f"frame {fid} was not returned by an earlier tool call; "
                               f"use a frame id from a previous observation.")
        count = _as_count(k, "k", SIMILAR_DEFAULT_K, SIMILAR_MAX_K)
        _check_obs_images(count)
        start, end = _time_window(self.vi, start_time, end_time)
        pos = self.vi._idx_to_pos.get(fid)
        if pos is not None:
            ref = self.vi.embeddings[pos]
        else:
            feats = self.clip.extract_frame_features([self.vi.get_frame(fid)])
            ref = np.asarray(feats.cpu().numpy(), dtype=np.float32).reshape(-1)
        positions = self.vi.positions_in_window(start, end)
        ref_time = self.vi.frame_time(fid)
        positions = positions[np.abs(self.vi._frame_times[positions] - ref_time)
                              >= env_float("TAKA_SIMILAR_EXCLUDE_SEC")]
        if len(positions) == 0:
            raise ToolFeedback(f"no other sampled frames in [{start:.1f}s, {end:.1f}s].")
        sims = self.vi.embeddings[positions] @ ref
        candidates = [(int(self.vi._frame_indices[p]), float(s)) for p, s in zip(positions, sims)]
        min_gap = max(1, int(env_float("TAKA_SIMILAR_MIN_GAP_SEC") * self.vi.video_fps))
        picked = _temporal_nms_pick(candidates, count, set(), min_gap)
        scores = dict(candidates)
        images = self.vi.get_frames(picked)
        lines = [f"Similar to Frame {fid} @ {ref_time:.1f}s in [{start:.1f}s, {end:.1f}s]: "
                 f"{len(images)} frames, in temporal order:"]
        lines += [f"  Frame {f} @ {self.vi.frame_time(f):.1f}s  similarity={scores[f]:.3f}" for f, _ in images]
        return ToolResult(True, {"frame_ids": [f for f, _ in images]}, images, "\n".join(lines), lead=True)


class ExtractTool:
    """Extract(intervals, mode, max_frames) inside known intervals.

    uniform: the target frame ids are computed directly (interval + linspace rule of
             the previous Extract_uniform).
    motion:  candidates at 5-10 fps are scanned once per interval; each is reduced to a
             small gray image only long enough to score its difference to the previous
             one, and peaks are chosen from the scores.
    The chosen frames of all intervals are then decoded in RGB in one ordered pass."""

    def __init__(self, video_index: VideoIndex) -> None:
        self.vi = video_index

    def __call__(
        self,
        intervals: List[List[float]],
        mode: str = "uniform",
        max_frames: Optional[int] = None,
    ) -> ToolResult:
        mode = str(mode).strip().lower()
        if mode not in ("uniform", "motion"):
            raise ToolFeedback(f"mode={mode!r}; use \"uniform\" or \"motion\"")
        spans, clipped = self._spans(intervals, mode)
        default = env_int("TAKA_EXTRACT_UNIFORM_BROAD" if mode == "uniform" else "TAKA_EXTRACT_MOTION_DEFAULT")
        count = _as_count(max_frames, "max_frames", default, EXTRACT_MAX_FRAMES)
        _check_obs_images(count * len(spans))
        per_span: List[List[int]] = []
        frames: Dict[int, Image.Image] = {}
        for start, end in spans:
            if not self.vi.video_path:
                picked = (_uniform_from_index(self.vi, start, end, count) if mode == "uniform"
                          else _motion_from_index(self.vi, start, end, count))
                frames.update(picked)
                ids = [fid for fid, _ in picked]
            elif mode == "uniform":
                ids = uniform_frame_ids(start, end, self.vi.video_fps, self.vi.num_video_frames - 1, count)
            else:
                ids = self._motion_ids(start, end, count)
            if not ids:
                raise ToolFeedback(f"no frames in [{start:.1f}s, {end:.1f}s] "
                                   f"(video is {self.vi.total_duration:.1f}s long). Intervals are in "
                                   f"seconds, not frame ids; to look at frames by id, use Review.")
            per_span.append(ids)
        if self.vi.video_path:
            frames.update(self.vi.get_frames([fid for ids in per_span for fid in ids]))
        selected = sorted(frames.items())
        lines = [f"Extracted {len(selected)} frames ({mode}) from {len(spans)} interval(s):"]
        for i, ((start, end), ids) in enumerate(zip(spans, per_span)):
            note = (f" (requested end_time {clipped[i]:.1f}s is past the end of the video; "
                    f"clipped to the last frame at {end:.1f}s)" if i in clipped else "")
            lines.append(f"Interval [{start:.1f}s, {end:.1f}s]{note}:")
            lines += [f"  Frame {fid} @ {self.vi.frame_time(fid):.1f}s" for fid in ids]
        return ToolResult(True, {"frame_ids": [fid for fid, _ in selected], "mode": mode},
                          selected, "\n".join(lines))

    def _spans(self, intervals: Any, mode: str) -> Tuple[List[Tuple[float, float]], Dict[int, float]]:
        """Validated intervals, and {interval index: requested end} for ends clipped to the
        video end. An interval starting after the video end is a ToolFeedback."""
        if (not isinstance(intervals, list) or not intervals
                or any(not isinstance(iv, (list, tuple)) or len(iv) != 2 for iv in intervals)):
            raise ToolFeedback(f"intervals={intervals!r} must be a non-empty list of [start_time, end_time] pairs")
        if len(intervals) > EXTRACT_MAX_INTERVALS:
            raise ToolFeedback(f"at most {EXTRACT_MAX_INTERVALS} intervals per call")
        max_range = env_int("TAKA_MOTION_MAX_RANGE")
        video_end = self.vi.video_end_sec if self.vi.video_path else self.vi.total_duration
        spans, clipped = [], {}
        for iv in intervals:
            start, end = _as_time(iv[0], "start_time"), _as_time(iv[1], "end_time")
            if end <= start:
                raise ToolFeedback(f"invalid interval [{start}, {end}]: start_time must be < end_time. "
                                   f"To see a moment t, use a short interval such as [t - 1, t + 1]; "
                                   f"to look again at a frame id, use Review.")
            start = max(0.0, start)
            if start > video_end:
                raise ToolFeedback(f"interval [{start:.1f}s, {end:.1f}s] starts after the end of the video "
                                   f"(the video is {video_end:.1f}s long; its last frame is at {video_end:.1f}s).")
            if mode == "motion" and end - start > max_range + 0.1:
                raise ToolFeedback(f"motion mode covers at most {max_range}s per interval (got {end - start:.0f}s). "
                                   f"Narrow the interval, use Search to find it, or use mode=\"uniform\".")
            if end > video_end:
                clipped[len(spans)] = end
                end = video_end
            spans.append((start, end))
        return spans, clipped

    def _motion_ids(self, start: float, end: float, count: int) -> List[int]:
        cand = motion_candidate_ids(start, end, self.vi.video_fps, self.vi.num_video_frames - 1)
        if len(cand) <= count:
            return cand
        # Only (frame, score) survives the scan: score = mean |gray - previous gray|.
        scores = np.zeros(len(cand), dtype=np.float32)
        pos_of = {fid: i for i, fid in enumerate(cand)}
        prev: List[Optional[np.ndarray]] = [None]
        width = env_int("TAKA_MOTION_GRAY_WIDTH")

        def score(frame_id, rgb):
            h, w = rgb.shape[:2]
            small = cv2.resize(rgb, (width, max(1, round(h * width / w))), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY).astype(np.float32)
            if prev[0] is not None:
                scores[pos_of[frame_id]] = float(np.mean(np.abs(gray - prev[0])))
            prev[0] = gray

        self.vi.scan_frames(cand, score, what="Extract motion")
        times = [fid / self.vi.video_fps for fid in cand]
        return [cand[p] for p in _motion_diverse_positions(scores, times, count)]


def uniform_frame_ids(start: float, end: float, fps: float, last_idx: int, max_frames: int) -> List[int]:
    """Extract(mode="uniform") frame ids: stride at 10/5/2 fps by interval length, then
    max_frames evenly spaced picks (the previous decode-then-select rule, computed
    directly). The end is clipped to the last frame known to decode."""
    duration = end - start
    target_fps = min(10.0 if duration < 5 else 5.0 if duration < 30 else 2.0, fps)
    interval = max(1, int(fps / max(target_fps, 1e-6)))
    start_idx = int(start * fps)
    end_idx = min(int(end * fps), last_idx)
    if start_idx > end_idx:
        return []
    cand = range(start_idx, end_idx + 1, interval)
    n = len(cand)
    if n <= max_frames:
        return list(cand)
    return sorted({cand[int(p)] for p in np.linspace(0, n - 1, max_frames)})


def motion_candidate_ids(start: float, end: float, fps: float, last_idx: int) -> List[int]:
    """Extract(mode="motion") scan points: 10 fps for intervals < 3s, else 5 fps."""
    target_fps = min(10.0 if end - start < 3 else 5.0, fps)
    interval = max(1, int(fps / max(target_fps, 1e-6)))
    start_idx = int(start * fps)
    end_idx = min(int(end * fps), last_idx)
    return list(range(start_idx, end_idx + 1, interval)) if start_idx <= end_idx else []


def _uniform_from_index(vi: VideoIndex, start: float, end: float, max_frames: int):
    """In-memory index (no video_path): uniform picks from the 1-fps frames."""
    frames = vi.get_frames_in_range(start, end)
    if len(frames) <= max_frames:
        return frames
    return [frames[int(p)] for p in np.linspace(0, len(frames) - 1, max_frames, dtype=int)]


def _motion_from_index(vi: VideoIndex, start: float, end: float, max_frames: int):
    """In-memory index (no video_path): motion from 1-fps embedding changes."""
    frames = vi.get_frames_in_range(start, end)
    if len(frames) <= max_frames:
        return frames
    positions = [vi._idx_to_pos[fid] for fid, _ in frames]
    embs = vi.embeddings[positions]
    dists = np.zeros(len(positions), dtype=np.float32)
    for i in range(1, len(positions)):
        dists[i] = 1.0 - float(embs[i] @ embs[i - 1])
    times = [vi.frame_time(fid) for fid, _ in frames]
    return [frames[p] for p in _motion_diverse_positions(dists, times, max_frames)]


class ReviewTool:
    """Review(frame_ids): show frames an earlier call returned again (from the frame cache
    or the video); nothing new is searched."""

    def __init__(self, video_index: VideoIndex, returned_ids: set) -> None:
        self.vi = video_index
        self.returned_ids = returned_ids

    def __call__(self, frame_ids: List[int]) -> ToolResult:
        if not isinstance(frame_ids, list) or not frame_ids:
            raise ToolFeedback("frame_ids must be a non-empty list of frame ids from earlier observations.")
        ids = [_as_frame_id(x) for x in frame_ids]
        unknown = sorted({fid for fid in ids if fid not in self.returned_ids})
        if unknown:
            raise ToolFeedback(f"frames {unknown} were not returned by an earlier tool call.")
        if len(set(ids)) > REVIEW_MAX_FRAMES:
            raise ToolFeedback(f"at most {REVIEW_MAX_FRAMES} frames per Review.")
        _check_obs_images(len(set(ids)))
        images = self.vi.get_frames(ids)
        lines = [f"Review of {len(images)} earlier frames, in temporal order:"] + _frame_lines(self.vi, images)
        return ToolResult(True, {"frame_ids": [fid for fid, _ in images]}, images, "\n".join(lines))


class EnhanceTool:
    """Enhance(frame_ids): whole frames an earlier call returned, shown to the Selector at
    TAKA_SELECTOR_ENHANCE_MAX_SIDE (higher than the Extract / Review view)."""

    def __init__(self, video_index: VideoIndex, returned_ids: set) -> None:
        self.vi = video_index
        self.returned_ids = returned_ids

    def __call__(self, frame_ids: List[int]) -> ToolResult:
        if not isinstance(frame_ids, list) or not frame_ids:
            raise ToolFeedback("frame_ids must be a non-empty list of frame ids from earlier observations.")
        ids = sorted({_as_frame_id(x) for x in frame_ids})
        unknown = [fid for fid in ids if fid not in self.returned_ids]
        if unknown:
            raise ToolFeedback(f"frames {unknown} were not returned by an earlier tool call.")
        if len(ids) > ENHANCE_MAX_FRAMES:
            raise ToolFeedback(f"at most {ENHANCE_MAX_FRAMES} frames per Enhance.")
        images = self.vi.get_frames(ids)
        side = env_int("TAKA_SELECTOR_ENHANCE_MAX_SIDE")
        lines = [f"Enhanced {len(images)} frames (long side {side}px), in temporal order:"] + _frame_lines(self.vi, images)
        return ToolResult(True, {"frame_ids": ids}, images, "\n".join(lines), max_side=side)


class CropStore:
    """Crops made while answering one question. The Selector's Crop tool and the
    Reflector's Crop share this store, so a Selector crop id can be submitted."""


    def __init__(self, video_index: VideoIndex) -> None:
        self.vi = video_index
        self._crops: Dict[str, Dict[str, Any]] = {}

    def make(self, frame_id: int, box: Any) -> Tuple[str, Image.Image]:
        x1, y1, x2, y2 = self._validate_box(box)
        img = self.vi.get_frame(frame_id)
        w, h = img.size
        s = CROP_BOX_SCALE
        crop = img.crop((round(x1 * w / s), round(y1 * h / s), round(x2 * w / s), round(y2 * h / s)))
        long_side = max(crop.size)
        min_side = env_int("TAKA_CROP_MIN_SIDE")     # small regions are upscaled to this long side
        if long_side < min_side:
            scale = min_side / long_side
            crop = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))),
                               Image.LANCZOS)
        crop_id = f"f{int(frame_id)}_c{len(self._crops) + 1}"
        self._crops[crop_id] = {"frame_id": int(frame_id), "box": [x1, y1, x2, y2], "image": crop}
        return crop_id, crop

    def make_many(self, regions: Any, allowed_frames, what: str) -> List[Tuple[str, Image.Image]]:
        """Validate every region first (frame id in allowed_frames, box valid), then decode the
        frames in one pass and crop them. Nothing is created when any region is invalid."""
        if not isinstance(regions, list) or not regions:
            raise ToolFeedback(f"regions={regions!r} must be a non-empty list of {{\"frame_id\", \"box\"}} objects")
        if len(regions) > CROP_MAX_REGIONS:
            raise ToolFeedback(f"at most {CROP_MAX_REGIONS} regions per Crop call")
        _check_obs_images(len(regions))
        parsed = []
        for region in regions:
            if not isinstance(region, dict) or set(region) != {"frame_id", "box"}:
                raise ToolFeedback(f"region {region!r} must be {{\"frame_id\": ..., \"box\": [x1, y1, x2, y2]}}")
            fid = _as_frame_id(region["frame_id"])
            if fid not in allowed_frames:
                raise ToolFeedback(f"frame {fid} is not {what}")
            parsed.append((fid, self._validate_box(region["box"])))
        self.vi.get_frames([fid for fid, _ in parsed])          # one decode pass, then cache hits
        return [self.make(fid, list(box)) for fid, box in parsed]

    def get(self, crop_id: Any) -> Optional[Dict[str, Any]]:
        return self._crops.get(crop_id) if isinstance(crop_id, str) else None

    @classmethod
    def _validate_box(cls, box: Any) -> Tuple[int, int, int, int]:
        if (not isinstance(box, (list, tuple)) or len(box) != 4
                or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in box)):
            raise ToolFeedback(f"box={box!r} must be [x1, y1, x2, y2] in 0-{CROP_BOX_SCALE} coordinates")
        x1, y1, x2, y2 = (int(round(v)) for v in box)
        if not (0 <= x1 < x2 <= CROP_BOX_SCALE and 0 <= y1 < y2 <= CROP_BOX_SCALE):
            raise ToolFeedback(f"box={box!r}: need 0 <= x1 < x2 <= {CROP_BOX_SCALE} and "
                               f"0 <= y1 < y2 <= {CROP_BOX_SCALE}")
        min_box = env_int("TAKA_CROP_MIN_BOX")       # in 0-1000 units
        if x2 - x1 < min_box or y2 - y1 < min_box:
            raise ToolFeedback(f"box={box!r} is too small; each side must span at least {min_box}")
        return x1, y1, x2, y2


class CropTool:
    """Crop(regions): native-resolution zooms on frames earlier calls returned."""

    def __init__(self, video_index: VideoIndex, store: CropStore, returned_ids: set) -> None:
        self.vi = video_index
        self.store = store
        self.returned_ids = returned_ids

    def __call__(self, regions: List[Dict[str, Any]]) -> ToolResult:
        crops = self.store.make_many(regions, self.returned_ids,
                                     "returned by an earlier tool call; use a frame id from a previous observation")
        lines = [f"Cropped {len(crops)} region(s):"]
        for crop_id, _ in crops:
            info = self.store.get(crop_id)
            lines.append(f"  Crop {crop_id}: Frame {info['frame_id']} @ "
                         f"{self.vi.frame_time(info['frame_id']):.1f}s, box={info['box']}")
        lines.append("Pass decisive crops in Reflect crop_ids, together with their frames.")
        return ToolResult(True, {"crop_ids": [cid for cid, _ in crops]}, [], "\n".join(lines), crops=crops)


class ReflectTool:
    """Reflect(frame_ids, crop_ids) -- hand the candidate evidence to the Reflector.

    No validation here: the agent loop checks the ids before the Reflector is
    started (TAKAAgent._check_submission)."""

    def __init__(self, video_index: VideoIndex) -> None:
        self.vi = video_index

    def __call__(self, frame_ids: List[int], crop_ids: Optional[List[str]] = None) -> ToolResult:
        return ToolResult(True, {"reflected_frame_ids": frame_ids, "crop_ids": crop_ids or []},
                          [], "", terminal=True)


class ToolRegistry:
    def __init__(self, video_index: VideoIndex, clip_tool, subtitles=None, starting_timestamp=0, video_path: Optional[str] = None, question: str = "") -> None:
        # Ablation: TAKA_DISABLE_TOOLS=Similar,Review,Crop (comma-separated) removes those tools
        # from both the registry and the tool description shown to the LLM. Reflect is
        # never disableable (required for the agent to terminate). Prompt guidance that
        # names a disabled tool is scrubbed in models.agent (scrub_disabled_tool_guidance).
        # video_path is kept for call compatibility; frames are decoded via video_index.
        disabled = env_tool_set("TAKA_DISABLE_TOOLS")
        self._video_index = video_index
        self._trace_qid = None
        self._disabled_tools = disabled
        self._returned_ids: set = set()   # frame ids returned by earlier tool calls
        self.crop_store = CropStore(video_index)
        self._tools = {
            "Search": SearchTool(video_index, clip_tool, question=question),
            "Similar": SimilarTool(video_index, clip_tool, self._returned_ids),
            "Extract": ExtractTool(video_index),
            "Review": ReviewTool(video_index, self._returned_ids),
            "Enhance": EnhanceTool(video_index, self._returned_ids),
            "Crop": CropTool(video_index, self.crop_store, self._returned_ids),
            "Reflect": ReflectTool(video_index),
        }
        for name in list(self._tools):
            if name != "Reflect" and name in disabled:
                del self._tools[name]

    @property
    def returned_ids(self) -> set:
        return self._returned_ids

    def set_trace_context(self, *, qid: Optional[str]) -> None:
        self._trace_qid = qid

    def execute(self, tool_name: str, params: Dict[str, Any]) -> ToolResult:
        started = time.perf_counter()
        result: Optional[ToolResult] = None
        error: Optional[BaseException] = None
        try:
            tool = self._tools.get(tool_name)
            if tool is None:
                result = ToolResult(
                    False, {}, [],
                    f"Unknown tool '{tool_name}'. Available: {', '.join(self._tools)}",
                )
            else:
                result = tool(**(params or {}))
        except InputDataError as exc:
            error = exc
            raise                                   # data problem -> question failed (runner)
        except ToolFeedback as exc:
            error = exc
            result = ToolResult(False, {}, [], f"{tool_name}: {exc}")
        except (TypeError, ValueError) as exc:      # wrong / missing / non-numeric parameters from the agent
            error = exc
            result = ToolResult(False, {}, [], f"{tool_name} error: bad parameters {params}: {exc}")
        except Exception as exc:
            error = exc
            raise
        finally:
            duration = self._video_index.total_duration
            if result is not None and (result.images or result.crops):
                frame_count = len(result.images) + len(result.crops)
            elif tool_name == "Reflect" and isinstance((params or {}).get("frame_ids"), list):
                frame_count = len(params["frame_ids"])
            else:
                frame_count = 0
            metric = {
                "kind": "tool",
                "qid": self._trace_qid,
                "name": tool_name,
                "mode": (params or {}).get("mode") if isinstance(params, dict) else None,
                "elapsed_sec": round(time.perf_counter() - started, 4),
                "prompt_tokens": None,
                "frame_count": frame_count,
                "duration_sec": round(float(duration), 3),
                "duration_bucket": (
                    "short" if duration <= 60 else "medium" if duration <= 600 else "long"
                ),
                "success": bool(result is not None and result.success and error is None),
                "error_type": type(error).__name__ if error is not None else None,
            }
            print(f"[TAKA_METRIC] {json.dumps(metric, ensure_ascii=False, sort_keys=True)}", flush=True)
        assert result is not None
        if result.success:
            self._returned_ids.update(int(fid) for fid, _ in result.images)
        return result

    @staticmethod
    def get_tools_description() -> str:
        return get_tools_description()

    @staticmethod
    def get_openai_tools() -> List[Dict[str, Any]]:
        return get_openai_tools()


def _scene_adaptive_select(
    vi: VideoIndex,
    q_mat: np.ndarray,
    budget: int,
    positions: np.ndarray,
) -> Tuple[List[int], Dict[str, Any]]:
    """Coverage-first, query-biased frame set over the scenes inside `positions`.
    A frame's relevance is its best similarity over the query rows of q_mat.

    Ported from the offline ``scene_adaptive_select`` (build_experiment0603_*_adaptive.py):
      * more scenes than the budget: split the scene sequence into `budget` contiguous
        bins and keep the best-scoring scene of each bin (uniform temporal coverage);
      * otherwise every scene contributes its best frame and the remaining quota is
        filled with relevant frames under a temporal-NMS spacing.
    """
    frame_ids = vi._frame_indices[positions]
    scores = (vi.embeddings[positions] @ np.atleast_2d(q_mat).T).max(axis=1)
    scene_idx = vi.scene_index_of(frame_ids)
    scene_infos: List[Dict[str, Any]] = []
    # positions are ascending, so each scene is one contiguous run of scene_idx
    run_starts = np.flatnonzero(np.r_[True, scene_idx[1:] != scene_idx[:-1]])
    run_ends = np.r_[run_starts[1:], len(scene_idx)]
    for a, b in zip(run_starts, run_ends):
        vals = scores[a:b]
        order = np.argsort(vals)[::-1]
        topn = vals[order[: min(3, len(order))]]
        scene_infos.append({
            "best_frame": int(frame_ids[a + int(order[0])]),
            "score": 0.7 * float(vals[order[0]]) + 0.3 * float(np.mean(topn)),
            "span": (int(a), int(b)),
        })
    info = {"num_scenes": len(vi.scenes), "valid_scenes": len(scene_infos)}

    if len(scene_infos) > budget:
        boundaries = np.linspace(0, len(scene_infos), budget + 1, dtype=int).tolist()
        selected: List[int] = []
        for a, b in zip(boundaries[:-1], boundaries[1:]):
            if b > a:
                selected.append(max(range(a, b), key=lambda j: scene_infos[j]["score"]))
        chosen = set(selected)
        if len(selected) < budget:
            for j in sorted(range(len(scene_infos)), key=lambda x: scene_infos[x]["score"], reverse=True):
                if j not in chosen:
                    selected.append(j)
                    chosen.add(j)
                    if len(selected) >= budget:
                        break
        frames = [scene_infos[j]["best_frame"] for j in sorted(selected[:budget])]
        return sorted(set(frames)), {**info, "mode": "bin_cover"}

    selected_frames = [s["best_frame"] for s in scene_infos]
    remaining = budget - len(selected_frames)
    if remaining > 0:
        candidates = [(int(f), float(s)) for f, s in zip(frame_ids, scores)]
        span = int(frame_ids[-1] - frame_ids[0])
        min_gap = max(1, min(16, int(span / max(budget * 4, 1))))
        selected_frames.extend(_temporal_nms_pick(candidates, remaining, set(selected_frames), min_gap))
    return sorted(set(selected_frames))[:budget], {**info, "mode": "all_scene_plus_fill"}


def _coverage_floor(pool: List[int], frames: List[int], budget: int, maxgap_frac: float) -> List[int]:
    """Insert frames into temporal gaps larger than maxgap_frac of the window.

    Fill points come from the sampled frame pool (nearest to each gap's midpoint), so
    every returned id is a real, decodable frame. Caps the result at `budget`.
    """
    pool = sorted(int(x) for x in pool)
    if len(pool) < 2 or not frames:
        return sorted(set(frames))
    lo, hi = pool[0], pool[-1]
    if hi <= lo:
        return sorted(set(frames))
    thresh = maxgap_frac * (hi - lo)
    taken = set(int(f) for f in frames)

    def nearest_free(target: int) -> Optional[int]:
        i = bisect.bisect_left(pool, target)
        best, best_d = None, None
        for direction in (-1, 1):
            j = i if direction == 1 else i - 1
            while 0 <= j < len(pool) and pool[j] in taken:
                j += direction
            if 0 <= j < len(pool):
                d = abs(pool[j] - target)
                if best_d is None or d < best_d or (d == best_d and pool[j] < best):
                    best, best_d = pool[j], d
        return best

    guard = 0
    while len(taken) < budget and guard < budget * 4:
        guard += 1
        pts = [lo] + sorted(taken) + [hi]
        gaps = [pts[i + 1] - pts[i] for i in range(len(pts) - 1)]
        gi = int(np.argmax(gaps))
        if gaps[gi] <= thresh:
            break
        cand = nearest_free((pts[gi] + pts[gi + 1]) // 2)
        if cand is None:
            break
        taken.add(cand)
    return sorted(taken)


def _temporal_nms_pick(
    candidates: List[Tuple[int, float]],
    need: int,
    existing: set,
    min_gap: int,
) -> List[int]:
    """Greedy score-ranked pick with a minimum temporal gap (frame ids).

    Ported from build_experiment0603_*_adaptive.py: fill a quota with high-relevance
    frames while keeping them temporally spread; relax the gap constraint as a
    fallback so the quota is always met when possible.
    """
    picked: List[int] = []
    ranked = sorted(candidates, key=lambda x: (x[1], -x[0]), reverse=True)
    for fid, _ in ranked:
        if fid in existing:
            continue
        if all(abs(fid - prev) >= min_gap for prev in existing | set(picked)):
            picked.append(fid)
            if len(picked) >= need:
                return picked
    for fid, _ in ranked:
        if fid in existing or fid in picked:
            continue
        picked.append(fid)
        if len(picked) >= need:
            break
    return picked


def _motion_diverse_positions(
    scores: np.ndarray,
    times: List[float],
    max_frames: int,
) -> List[int]:
    """Select motion frames with enough temporal spread for VLM evidence.

    Motion scores are computed at a relatively high sampling rate to localize
    changes, but the returned frames should show distinct states rather than
    near-duplicates around a single peak.
    """
    n = len(times)
    if n <= max_frames:
        return list(range(n))
    if n == 0 or max_frames <= 0:
        return []

    t = np.asarray(times, dtype=np.float32)
    duration = max(0.0, float(t[-1] - t[0]))
    min_gap = min(2.0, max(0.5, duration / max(float(max_frames), 1.0))) if duration > 0 else 0.0
    context_gap = min(2.0, max(0.5, min_gap))
    selected: List[int] = []

    def nearest_pos(target_time: float) -> int:
        return int(np.argmin(np.abs(t - target_time)))

    def add_pos(pos: int, gap: float) -> bool:
        if len(selected) >= max_frames or pos in selected:
            return False
        if gap > 0 and any(abs(float(t[pos] - t[prev])) < gap for prev in selected):
            return False
        selected.append(pos)
        return True

    peak_order = [
        int(pos)
        for pos in np.argsort(scores)[::-1]
        if int(pos) > 0 and float(scores[int(pos)]) > 0.0
    ]
    if not peak_order:
        raise ToolFeedback("no motion peak in this time range (frames are static). "
                           "Use Extract_uniform or a different time range.")
    peak_positions: List[int] = []
    max_peaks = max(1, min(max_frames, (max_frames + 2) // 3))
    for pos in peak_order:
        if len(peak_positions) >= max_peaks:
            break
        if any(abs(float(t[pos] - t[prev])) < context_gap for prev in peak_positions):
            continue
        peak_positions.append(pos)

    for peak in peak_positions:
        peak_time = float(t[peak])
        for pos in (
            peak,
            nearest_pos(peak_time - context_gap),
            nearest_pos(peak_time + context_gap),
        ):
            add_pos(pos, min_gap)

    for gap in (min_gap, min_gap * 0.5, 0.0):
        for pos in peak_order:
            add_pos(pos, gap)
            if len(selected) >= max_frames:
                break
        if len(selected) >= max_frames:
            break

        for target_time in np.linspace(float(t[0]), float(t[-1]), max_frames):
            add_pos(nearest_pos(float(target_time)), gap)
            if len(selected) >= max_frames:
                break
        if len(selected) >= max_frames:
            break

    return sorted(selected)[:max_frames]
