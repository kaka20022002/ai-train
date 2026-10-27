"""Tool schemas shown to the Selector / Reflector, and the numeric tool limits.

Kept free of heavy imports (cv2 / torch) so prompt rendering scripts can build the
exact schema the agent sees without a video stack.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List

# ── Configuration ───────────────────────────────────────────────────
# Every value is read from the environment set by configs/common_env.sh (the single
# source of configuration; checked at startup by agent/config_check.py). There are no
# code defaults: an unset variable aborts with a [config error].


def env_str(name: str) -> str:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        raise SystemExit(f"[config error] {name} is not set (source configs/common_env.sh)")
    return raw.strip()


def env_int(name: str) -> int:
    raw = env_str(name)
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(f"[config error] {name}={raw!r} is not a valid integer")


def env_float(name: str) -> float:
    raw = env_str(name)
    try:
        return float(raw)
    except ValueError:
        raise SystemExit(f"[config error] {name}={raw!r} is not a number")


def env_tool_set(name: str) -> set:
    """Comma-separated tool-name list (TAKA_DISABLE_TOOLS): must be defined, may be empty."""
    raw = os.environ.get(name)
    if raw is None:
        raise SystemExit(f"[config error] {name} is not set (source configs/common_env.sh)")
    return {t.strip() for t in raw.split(",") if t.strip()}


SEARCH_FOCUS_DEFAULT_K = env_int("TAKA_SEARCH_FOCUS_K")
SIMILAR_DEFAULT_K = env_int("TAKA_SIMILAR_K")
SEARCH_FOCUS_MAX_K = SEARCH_COVER_MAX_K = SIMILAR_MAX_K = EXTRACT_MAX_FRAMES = env_int("TAKA_TOOL_MAX_K")
# Batch sizes per call (as MMDR-PLANNER: TextSearch 5 queries, CropImage 10 boxes).
SEARCH_MAX_QUERIES = env_int("TAKA_SEARCH_MAX_QUERIES")
EXTRACT_MAX_INTERVALS = env_int("TAKA_EXTRACT_MAX_INTERVALS")
CROP_MAX_REGIONS = env_int("TAKA_CROP_MAX_REGIONS")
REVIEW_MAX_FRAMES = env_int("TAKA_REVIEW_MAX_FRAMES")
ENHANCE_MAX_FRAMES = env_int("TAKA_ENHANCE_MAX_FRAMES")     # Reflector: whole frames, high resolution
CROP_BOX_SCALE = 1000          # protocol, not a knob: Qwen-VL's 0-1000 relative grounding coordinates


def cover_budget_for(duration_sec: float) -> int:
    """Default Search(mode="cover") frame budget for a video of this length."""
    if duration_sec <= 60:
        return env_int("TAKA_SEARCH_COVER_BUDGET_SHORT")
    if duration_sec <= 600:
        return env_int("TAKA_SEARCH_COVER_BUDGET_MEDIUM")
    return env_int("TAKA_SEARCH_COVER_BUDGET_LONG")


# Pure literals: placeholders like <COVER_SHORT> are filled by get_tools_description().
TOOLS_SCHEMA = [
    {
        "name": "Search",
        "description": (
            "Find frames by visual text queries over the video's 1-fps index (<RETRIEVER> "
            "embeddings). mode=\"focus\" returns, for each query, the best-matching frame of the "
            "top-k most relevant scenes: pointers to where things happen. mode=\"cover\" returns "
            "k frames spread over the whole time window, biased toward scenes relevant to any "
            "query: a map for counting, ordering, summaries, or when the location is unknown. "
            "Frames are small previews (leads); verify details with Extract, Review, or Crop."
        ),
        "parameters": {
            "queries": {"type": "array", "items": {"type": "string"}, "required": True,
                        "description": "1-<SEARCH_MAX_Q> short, concrete descriptions of what is VISIBLE (people, objects, actions, scene layout); the retriever cannot read subtitles or hear speech. Put independent events in one call (e.g. [\"person picks up the cup\", \"person puts the cup down\"])."},
            "mode": {"type": "string", "enum": ["focus", "cover"], "default": "focus",
                     "description": "focus = top-k relevant scenes; cover = k frames covering the time window."},
            "k": {"type": "integer", "required": False,
                  "description": "focus: number of scenes per query (default <FOCUS_K>, max <FOCUS_MAX>). cover: number of frames (default <COVER_SHORT> / <COVER_MEDIUM> / <COVER_LONG> for short (<=60s) / medium (<=600s) / long videos, max <COVER_MAX>)."},
            "start_time": {"type": "number", "required": False, "description": "Limit the search to after this time (seconds)."},
            "end_time": {"type": "number", "required": False, "description": "Limit the search to before this time (seconds)."},
        },
    },
    {
        "name": "Similar",
        "description": (
            "Find other moments that look like a given frame (same person, object, place, or "
            "layout) by image-to-image similarity. Use it to re-identify a subject, count "
            "recurrences, or find where a scene returns. Frames are small previews (leads)."
        ),
        "parameters": {
            "frame_id": {"type": "integer", "required": True, "description": "A frame id returned by an earlier tool call."},
            "k": {"type": "integer", "required": False, "description": "Number of frames (default <SIMILAR_K>, max <SIMILAR_MAX>)."},
            "start_time": {"type": "number", "required": False, "description": "Limit the search to after this time (seconds)."},
            "end_time": {"type": "number", "required": False, "description": "Limit the search to before this time (seconds)."},
        },
    },
    {
        "name": "Extract",
        "description": (
            "Read frames from known time intervals. mode=\"uniform\" samples evenly (appearance, "
            "state, balanced local context). mode=\"motion\" picks action boundaries and visible "
            "state changes (actions, transitions, before/after); each motion interval is limited "
            "to <MOTION_MAX_RANGE>s. Put independent intervals in one call."
        ),
        "parameters": {
            "intervals": {"type": "array", "required": True,
                          "items": {"type": "array", "items": {"type": "number"}},
                          "description": "1-<EXTRACT_MAX_IV> intervals. List of [start_time, end_time] pairs in SECONDS with start_time < end_time, e.g. [[12, 20], [95, 101]]. For one moment t use [t - 1, t + 1]. Frame ids are not times: use Review to look at frames by id."},
            "mode": {"type": "string", "enum": ["uniform", "motion"], "default": "uniform",
                     "description": "uniform = evenly spaced frames; motion = frames at visual changes."},
            "max_frames": {"type": "integer", "required": False,
                           "description": "Maximum frames per interval (default <UNIFORM_DEFAULT> for uniform, <MOTION_DEFAULT> for motion; max <EXTRACT_MAX>)."},
        },
    },
    {
        "name": "Review",
        "description": (
            "Look again at frames returned by earlier tool calls. Earlier observation images are "
            "removed from your context; use Review to re-check what specific frames show before "
            "relying on them or choosing Reflect frames."
        ),
        "parameters": {
            "frame_ids": {"type": "array", "items": {"type": "integer"}, "required": True,
                          "description": "Frame ids returned by earlier tool calls (at most <REVIEW_MAX>)."},
        },
    },
    {
        "name": "Enhance",
        "description": (
            "Look at whole frames returned earlier at higher resolution (long side <SEL_ENHANCE_SIDE> px) "
            "to confirm an attribute (color, clothing, identity, posture, layout) before relying on it. "
            "For one small region (text, icon, small object), Crop is sharper."
        ),
        "parameters": {
            "frame_ids": {"type": "array", "items": {"type": "integer"}, "required": True,
                          "description": "1-<ENHANCE_MAX> frame ids returned by earlier tool calls."},
        },
    },
    {
        "name": "Crop",
        "description": (
            "Zoom into regions of frames at native resolution. Observation frames are "
            "downscaled; use Crop to read small text or inspect small objects, faces, or fine "
            "detail. Several regions (of one or several frames) can be cropped in one call. "
            "Returns one crop id per region."
        ),
        "parameters": {
            "regions": {"type": "array", "required": True,
                        "items": {"type": "object",
                                  "properties": {"frame_id": {"type": "integer"},
                                                 "box": {"type": "array", "items": {"type": "integer"}}},
                                  "required": ["frame_id", "box"]},
                        "description": "1-<CROP_MAX_R> regions. List of {\"frame_id\": id returned by an earlier tool call, \"box\": [x1, y1, x2, y2] in 0-1000 relative coordinates ([0, 0] = top-left, [1000, 1000] = bottom-right)}."},
        },
    },
    {
        "name": "Reflect",
        "description": (
            "Send the selected frames (and optionally crops of them) to the Reflector, which "
            "independently answers from the visible evidence. CONFIRM ends the task with an "
            "answer; REJECT returns an evidence gap and a recovery suggestion; after a REJECT the "
            "Reflector may also end the task with BEST_GUESS when the missing fact cannot be "
            "shown by any frame."
        ),
        "parameters": {
            "frame_ids": {"type": "array", "items": {"type": "integer"}, "required": True,
                          "description": "Frame ids returned by earlier tool calls (at most <REFLECT_MAX> frames)."},
            "crop_ids": {"type": "array", "items": {"type": "string"}, "required": False,
                         "description": "Crop ids (returned by Crop) of submitted frames to show the Reflector as well."},
        },
    },
]

# The Reflector's own Crop: same tool, restricted to the submitted frames.
REFLECTOR_CROP_REGIONS_DESCRIPTION = (
    "1-10 regions. List of {\"frame_id\": one of the submitted frame ids, \"box\": [x1, y1, x2, y2] in 0-1000 "
    "relative coordinates ([0, 0] = top-left, [1000, 1000] = bottom-right)}."
)


def _placeholders() -> Dict[str, str]:
    retriever = env_str("TAKA_RETRIEVER").lower()
    return {
        "<RETRIEVER>": "BLIP" if retriever == "blip" else "CLIP",
        "<FOCUS_K>": str(SEARCH_FOCUS_DEFAULT_K),
        "<FOCUS_MAX>": str(SEARCH_FOCUS_MAX_K),
        "<COVER_SHORT>": str(cover_budget_for(30)),
        "<COVER_MEDIUM>": str(cover_budget_for(300)),
        "<COVER_LONG>": str(cover_budget_for(3600)),
        "<COVER_MAX>": str(SEARCH_COVER_MAX_K),
        "<SIMILAR_K>": str(SIMILAR_DEFAULT_K),
        "<SIMILAR_MAX>": str(SIMILAR_MAX_K),
        "<MOTION_MAX_RANGE>": str(env_int("TAKA_MOTION_MAX_RANGE")),
        "<UNIFORM_DEFAULT>": str(env_int("TAKA_EXTRACT_UNIFORM_BROAD")),
        "<MOTION_DEFAULT>": str(env_int("TAKA_EXTRACT_MOTION_DEFAULT")),
        "<EXTRACT_MAX>": str(EXTRACT_MAX_FRAMES),
        "<REVIEW_MAX>": str(REVIEW_MAX_FRAMES),
        "<SEL_ENHANCE_SIDE>": str(env_int("TAKA_SELECTOR_ENHANCE_MAX_SIDE")),
        "<ENHANCE_MAX>": str(ENHANCE_MAX_FRAMES),
        "<SEARCH_MAX_Q>": str(SEARCH_MAX_QUERIES),
        "<EXTRACT_MAX_IV>": str(EXTRACT_MAX_INTERVALS),
        "<CROP_MAX_R>": str(CROP_MAX_REGIONS),
        "<REFLECT_MAX>": str(env_int("TAKA_REFLECT_MAX_FRAMES")),
    }


def _fill(text: str, values: Dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace(key, value)
    return text


def get_tools_description() -> str:
    """JSON schema of the enabled Selector tools (Reflect is never disabled)."""
    disabled = env_tool_set("TAKA_DISABLE_TOOLS")
    rendered = _fill(json.dumps(TOOLS_SCHEMA, ensure_ascii=False), _placeholders())
    schema = [t for t in json.loads(rendered)
              if t["name"] == "Reflect" or t["name"] not in disabled]
    return json.dumps(schema, indent=2, ensure_ascii=False)


def to_openai_tools(schemas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tools = []
    for schema in schemas:
        properties = {}
        required = []
        for name, raw_spec in schema.get("parameters", {}).items():
            spec = dict(raw_spec)
            if spec.pop("required", False):
                required.append(name)
            properties[name] = spec
        parameters: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            parameters["required"] = required
        tools.append({
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": parameters,
            },
        })
    return tools


def get_openai_tools() -> List[Dict[str, Any]]:
    """The enabled Selector tools as OpenAI-compatible function definitions."""
    return to_openai_tools(json.loads(get_tools_description()))


REFLECTOR_ENHANCE_SCHEMA = {
    "name": "Enhance",
    "description": (
        "View whole submitted frames again at high resolution (long side <ENHANCE_SIDE> px, from "
        "the native frame) when the default view is too small to judge the scene. For one small "
        "region, Crop is sharper."
    ),
    "parameters": {
        "frame_ids": {"type": "array", "items": {"type": "integer"}, "required": True,
                      "description": "1-<ENHANCE_MAX> submitted frame ids."},
    },
}


def get_reflector_openai_tools() -> List[Dict[str, Any]]:
    """The Reflector's tools: Crop (regions, native resolution) and Enhance (whole frames at
    high resolution), both restricted to the submitted frames."""
    crop = json.loads(json.dumps(next(t for t in TOOLS_SCHEMA if t["name"] == "Crop")))
    # (the Reflector's Enhance is REFLECTOR_ENHANCE_SCHEMA: submitted frames, TAKA_ENHANCE_MAX_SIDE)
    crop["description"] = (
        "Zoom into regions of submitted frames at native resolution, to read small text or "
        "inspect small objects, faces, or fine detail that the downscaled frames do not show "
        "clearly. Several regions can be cropped in one call."
    )
    crop["parameters"]["regions"]["description"] = REFLECTOR_CROP_REGIONS_DESCRIPTION
    enhance = json.loads(_fill(json.dumps(REFLECTOR_ENHANCE_SCHEMA), {
        "<ENHANCE_SIDE>": str(env_int("TAKA_ENHANCE_MAX_SIDE")),
        "<ENHANCE_MAX>": str(ENHANCE_MAX_FRAMES)}))
    return to_openai_tools([crop, enhance])
