"""Startup validation of every environment variable the framework reads.

Invalid values are configuration errors: the run aborts BEFORE any model is loaded,
printing every problem found (instead of silently falling back to a default at the
moment a tool reads the variable). Variables of removed features also abort, so a
stale config can't make a run look like it used a feature that no longer exists.
"""
import os
import re
import sys

# Every variable below MUST be set (configs/common_env.sh sets all of them to the paper-run
# values); code defaults are never used silently.
INT_VARS = [
    "TAKA_IMAGE_MAX_SIDE", "TAKA_OBS_MAX_SIDE", "TAKA_CROP_MAX_SIDE", "TAKA_ENHANCE_MAX_SIDE",
    "TAKA_SELECTOR_ENHANCE_MAX_SIDE",
    "TAKA_REFLECT_MAX_FRAMES", "TAKA_REFLECTOR_MAX_TOOL_CALLS", "TAKA_LLM_MAX_ATTEMPTS",
    "TAKA_LEAD_MAX_SIDE", "TAKA_OBS_MAX_IMAGES", "TAKA_CONTEXT_LIMIT", "TAKA_CONTEXT_RESERVE",
    "TAKA_MOTION_GRAY_WIDTH", "TAKA_SEARCH_FOCUS_K", "TAKA_SIMILAR_K", "TAKA_TOOL_MAX_K",
    "TAKA_SEARCH_MAX_QUERIES", "TAKA_EXTRACT_MAX_INTERVALS", "TAKA_CROP_MAX_REGIONS",
    "TAKA_REVIEW_MAX_FRAMES", "TAKA_ENHANCE_MAX_FRAMES", "TAKA_CROP_MIN_SIDE", "TAKA_CROP_MIN_BOX",
    "TAKA_LOOP_WARN_AT", "TAKA_LOOP_FAIL_AT", "SEL_MAX_STEPS", "SEL_MAX_REFLECT_REJECTS",
    "TAKA_EXTRACT_UNIFORM_BROAD", "TAKA_EXTRACT_MOTION_DEFAULT", "TAKA_MOTION_MAX_RANGE",
    "TAKA_SEARCH_COVER_BUDGET_SHORT", "TAKA_SEARCH_COVER_BUDGET_MEDIUM", "TAKA_SEARCH_COVER_BUDGET_LONG",
    "TAKA_FRAME_LRU_CACHE_SIZE", "TAKA_TORCH_THREADS", "TAKA_DECODE_THREADS",
    "TAKA_LLM_FAILOVER", "TAKA_LLM_COOLDOWN_FAILS", "TAKA_LLM_MAX_CONN_PER_EP",
    "AGENT_MAX_TOKENS", "REFLECT_MAX_TOKENS", "LLM_TOP_K",
]
FLOAT_VARS = [
    "TAKA_LLM_TIMEOUT", "TAKA_LLM_COOLDOWN", "TAKA_LLM_SLOW_FACTOR", "TAKA_LLM_SLOW_MIN_SEC",
    "SCENE_SIM_THRESHOLD", "TAKA_SEARCH_COVER_MAXGAP_FRAC",
    "TAKA_SIMILAR_EXCLUDE_SEC", "TAKA_SIMILAR_MIN_GAP_SEC",
    "AGENT_TEMPERATURE", "AGENT_TOP_P", "REFLECT_TEMPERATURE", "LLM_PRESENCE_PENALTY",
]
OPTIONAL_FLOAT_VARS = ["REFLECT_TOP_P"]          # empty = not sent (server default)
FLAG_VARS = ["TAKA_DISABLE_THINKING", "TAKA_KEEP_CONVERSATION_IMAGES", "CLIP_FORCE_CPU"]
RANGE_VARS = ["TAKA_FRAME_BUDGET_SHORT", "TAKA_FRAME_BUDGET_MEDIUM", "TAKA_FRAME_BUDGET_LONG"]
STR_VARS = ["CLIP_MODEL_NAME", "TAKA_CACHE_ROOT", "TAKA_RETRIEVER"]
DEFINED_VARS = ["TAKA_DISABLE_TOOLS"]             # must be exported, may be empty
ABLATABLE_TOOLS = ("Search", "Similar", "Extract", "Review", "Enhance", "Crop")

# Removed features: setting any of these is an error (see CLAUDE/08_FALLBACKS.md).
REMOVED_VARS = {
    "TAKA_FRAME_BUDGET_LO": "the duration-independent frame range was removed; use TAKA_FRAME_BUDGET_{SHORT,MEDIUM,LONG}",
    "TAKA_FRAME_BUDGET_HI": "the duration-independent frame range was removed; use TAKA_FRAME_BUDGET_{SHORT,MEDIUM,LONG}",
    "TAKA_FRAME_BUDGET_FLOOR": "the duration-independent frame floor was removed; use TAKA_FRAME_BUDGET_{SHORT,MEDIUM,LONG}",
    "TAKA_ENABLE_SCAFFOLD": "Scaffold was merged into Search(mode=\"cover\")",
    "TAKA_SCAFFOLD_BUDGET": "Scaffold was merged into Search(mode=\"cover\"); use TAKA_SEARCH_COVER_BUDGET_*",
    "TAKA_SCAFFOLD_BUDGET_GLOBAL": "Scaffold was merged into Search(mode=\"cover\"); use TAKA_SEARCH_COVER_BUDGET_*",
    "TAKA_SCAFFOLD_MAXGAP_FRAC": "the cover-mode coverage floor is fixed at 0.06",
    "TAKA_REFLECT_MAX_CROPS": "replaced by TAKA_REFLECTOR_MAX_TOOL_CALLS (Crop calls per Reflect)",
    "TAKA_REFLECT_MAX_IMAGES": "replaced by TAKA_REFLECT_MAX_FRAMES (over the limit -> tool error to the Selector)",
    "PROMPT_PROFILE": "prompt profiles / task-type prompts were removed",
    "ENABLE_VIDEOMME_TASK_STRATEGY": "task-type prompts were removed",
    "ABLATION_LOCATE_DESIGN": "removed (was off in the paper runs)",
    "ABLATION_REJECT_RECOVERY": "REJECT-recovery guidance now follows the Reflector (on iff --max-reflect-rejects > 0)",
    "TAKA_REACT_DENSIFY_HINT": "removed (was off in the paper runs)",
    "TAKA_REFLECT_CAP80": "exit shaping (cap80 / fill56) was removed",
    "TAKA_REFLECT_FILL": "exit shaping (cap80 / fill56) was removed",
    "TAKA_FILL_N": "exit shaping (cap80 / fill56) was removed",
    "TAKA_CAP80_CAP": "exit shaping (cap80 / fill56) was removed",
    "TAKA_CAP80_MIN_SEC": "exit shaping (cap80 / fill56) was removed",
    "TAKA_FILL_MAX_SEC": "exit shaping (cap80 / fill56) was removed",
    "TAKA_MAX_FALLBACK_FRAMES": "the step-budget fallback was removed (question -> failed)",
    "TAKA_COVERAGE_PROBE": "coverage-emphasis probes were removed (every question is GLOBAL)",
    "TAKA_SCAFFOLD_ADAPTIVE_BUDGET": "coverage-emphasis routing was removed",
    "TAKA_REFLECT_BAND_ROUTING": "coverage-emphasis routing was removed (GLOBAL sections always on)",
    "TAKA_SUBMIT_MERGE_SCAFFOLD": "removed together with exit shaping",
    "TAKA_SCAFFOLD_LONG_SEC": "removed (long-video Scaffold scaling was off in the paper runs)",
    "TAKA_SCAFFOLD_MIN_BUDGET": "removed (long-video Scaffold scaling was off in the paper runs)",
    "TAKA_EXTRACT_UNIFORM_CAP": "removed (was off in the paper runs)",
    "TAKA_EXTRACT_MOTION_CAP": "removed (was off in the paper runs)",
    "TEMPERATURE": "alias removed; use AGENT_TEMPERATURE",
    "MAX_TOKEN": "alias removed; use AGENT_MAX_TOKENS",
    "AGENT_MODEL_URL": "removed; pass --api-base-url",
    "VLLM_API_BASE": "removed; pass --api-base-url",
    "AGENT_MODEL_KEY": "removed; pass --api-key",
    "VLLM_API_KEY": "removed; pass --api-key",
    "AGENT_MODEL_NAME": "removed; pass --model-name",
    "EVAL_REQUEST_TIMEOUT": "alias removed; use API_EVAL_REQUEST_TIMEOUT",
}


def validate_env() -> None:
    errors = []
    unset = lambda n: os.getenv(n) is None or os.getenv(n).strip() == ""
    missing = [n for n in INT_VARS + FLOAT_VARS + FLAG_VARS + RANGE_VARS + STR_VARS if unset(n)]
    missing += [n for n in DEFINED_VARS if os.getenv(n) is None]
    if missing:
        errors.append(f"not set: {', '.join(missing)}  (source configs/common_env.sh)")
    for name in INT_VARS:
        v = os.getenv(name, "")
        if v.strip() and not re.fullmatch(r"-?\d+", v.strip()):
            errors.append(f"{name}={v!r} is not an integer")
    for name in FLOAT_VARS + OPTIONAL_FLOAT_VARS:
        v = os.getenv(name, "")
        if v.strip():
            try:
                float(v)
            except ValueError:
                errors.append(f"{name}={v!r} is not a number")
    for name in FLAG_VARS:
        v = os.getenv(name, "")
        if v.strip() and v.strip().lower() not in ("0", "1", "true", "false", "yes", "no", "on", "off"):
            errors.append(f"{name}={v!r} is not a boolean (use 0/1)")
    for name in RANGE_VARS:
        v = os.getenv(name, "")
        if v.strip() and not re.fullmatch(r"\d+-\d+", v.strip()):
            errors.append(f"{name}={v!r} is not a range like 18-26")
    retr = os.getenv("TAKA_RETRIEVER", "").strip().lower()
    if retr and retr not in ("clip", "blip"):
        errors.append(f"TAKA_RETRIEVER={retr!r}; allowed: clip, blip")
    if retr == "clip" and not os.path.exists(os.getenv("CLIP_MODEL_NAME", "")):
        errors.append(f"CLIP_MODEL_NAME={os.getenv('CLIP_MODEL_NAME')!r} is not a local path")
    if retr == "blip":
        ckpt = os.path.join(os.getenv("TORCH_HOME", ""), "hub", "checkpoints", "model_large_retrieval_coco.pth")
        if not os.path.isfile(ckpt):
            errors.append(f"TAKA_RETRIEVER=blip but {ckpt} not found (set TORCH_HOME to the aks_blip dir)")
        bert = os.path.join(os.getenv("HF_HOME", ""), "hub", "models--bert-base-uncased")
        if not os.path.isdir(bert):
            errors.append(f"TAKA_RETRIEVER=blip but {bert} not found (set HF_HOME; LAVIS needs bert-base-uncased)")
        if os.getenv("HF_HUB_OFFLINE") != "1":
            errors.append("TAKA_RETRIEVER=blip needs HF_HUB_OFFLINE=1 (LAVIS otherwise tries to download bert and hangs)")
        try:
            import lavis  # noqa: F401
        except Exception as exc:
            errors.append(f"TAKA_RETRIEVER=blip but LAVIS cannot be imported: {type(exc).__name__}: {exc}")
    disabled = [t.strip() for t in os.getenv("TAKA_DISABLE_TOOLS", "").split(",") if t.strip()]
    bad_tools = [t for t in disabled if t not in ABLATABLE_TOOLS]
    if bad_tools:
        errors.append(f"TAKA_DISABLE_TOOLS contains unknown/undisableable tool(s) {bad_tools}; "
                      f"allowed: {', '.join(ABLATABLE_TOOLS)}")
    # Ranges and limits that must agree with each other.
    ints = {n: int(os.getenv(n)) for n in INT_VARS if re.fullmatch(r"-?\d+", (os.getenv(n) or "").strip())}
    for name in ("TAKA_OBS_MAX_SIDE", "TAKA_CROP_MAX_SIDE", "TAKA_REFLECT_MAX_FRAMES", "TAKA_LEAD_MAX_SIDE",
                 "TAKA_OBS_MAX_IMAGES", "TAKA_CONTEXT_LIMIT",
                 "TAKA_MOTION_MAX_RANGE", "TAKA_EXTRACT_UNIFORM_BROAD", "TAKA_EXTRACT_MOTION_DEFAULT"):
        if name in ints and ints[name] < 1:
            errors.append(f"{name}={ints[name]} must be >= 1")
    if ints.get("TAKA_REFLECTOR_MAX_TOOL_CALLS", 0) < 0:
        errors.append("TAKA_REFLECTOR_MAX_TOOL_CALLS must be >= 0 (0 disables the Reflector's Crop)")
    max_k = ints.get("TAKA_TOOL_MAX_K", 0)
    for name in ("TAKA_SEARCH_COVER_BUDGET_SHORT", "TAKA_SEARCH_COVER_BUDGET_MEDIUM", "TAKA_SEARCH_COVER_BUDGET_LONG",
                 "TAKA_EXTRACT_UNIFORM_BROAD", "TAKA_EXTRACT_MOTION_DEFAULT", "TAKA_SEARCH_FOCUS_K", "TAKA_SIMILAR_K"):
        if name in ints and not 1 <= ints[name] <= max_k:
            errors.append(f"{name}={ints[name]} must be in 1..TAKA_TOOL_MAX_K ({max_k})")
    for name in ("TAKA_SEARCH_MAX_QUERIES", "TAKA_EXTRACT_MAX_INTERVALS", "TAKA_CROP_MAX_REGIONS",
                 "TAKA_REVIEW_MAX_FRAMES", "TAKA_ENHANCE_MAX_FRAMES", "TAKA_LOOP_WARN_AT", "TAKA_CROP_MIN_BOX"):
        if name in ints and ints[name] < 1:
            errors.append(f"{name}={ints[name]} must be >= 1")
    if ints.get("TAKA_LOOP_FAIL_AT", 0) <= ints.get("TAKA_LOOP_WARN_AT", 0):
        errors.append("TAKA_LOOP_FAIL_AT must be greater than TAKA_LOOP_WARN_AT")
    if ints.get("TAKA_CONTEXT_RESERVE", 0) < 0:
        errors.append("TAKA_CONTEXT_RESERVE must be >= 0")
    if "TAKA_CONTEXT_LIMIT" in ints and ints.get("TAKA_CONTEXT_RESERVE", 0) + ints.get("AGENT_MAX_TOKENS", 0) >= ints["TAKA_CONTEXT_LIMIT"]:
        errors.append("TAKA_CONTEXT_RESERVE + AGENT_MAX_TOKENS must be below TAKA_CONTEXT_LIMIT")
    cap = ints.get("TAKA_REFLECT_MAX_FRAMES")
    if cap is not None and "TAKA_OBS_MAX_IMAGES" in ints and cap > ints["TAKA_OBS_MAX_IMAGES"]:
        errors.append("TAKA_REFLECT_MAX_FRAMES must not exceed TAKA_OBS_MAX_IMAGES (images per request)")
    if cap is not None:
        uppers = []
        for name in RANGE_VARS:
            m = re.fullmatch(r"\d+-(\d+)", (os.getenv(name) or "").strip())
            if m:
                uppers.append((name, int(m.group(1))))
        for name, upper in uppers:
            if upper is not None and upper > cap:
                errors.append(f"{name} allows {upper} frames but TAKA_REFLECT_MAX_FRAMES={cap}")
    for name, why in REMOVED_VARS.items():
        if os.getenv(name) is not None:
            errors.append(f"{name} is set but no longer supported: {why}. Unset it.")
    if errors:
        msg = "[config error] invalid configuration, aborting:\n  - " + "\n  - ".join(errors)
        print(msg, file=sys.stderr, flush=True)
        print(msg, flush=True)
        sys.exit(2)
    print("[config ok] all framework variables set and valid", flush=True)
