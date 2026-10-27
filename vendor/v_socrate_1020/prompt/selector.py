"""Selector prompt templates and duration-aware planning guidance."""

import os
import re


def _env(name: str) -> str:
    """Configuration comes only from configs/common_env.sh: no code defaults."""
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        raise SystemExit(f"[config error] {name} is not set (source configs/common_env.sh)")
    return raw.strip()


# ── Tool ablation: keep prompt guidance consistent with TAKA_DISABLE_TOOLS ──
ABLATABLE_TOOLS = ("Search", "Similar", "Extract", "Review", "Enhance", "Crop")


def get_disabled_tools() -> set:
    raw = os.environ.get("TAKA_DISABLE_TOOLS")
    if raw is None:
        raise SystemExit("[config error] TAKA_DISABLE_TOOLS is not set (source configs/common_env.sh)")
    return {tool.strip() for tool in raw.split(",") if tool.strip() in ABLATABLE_TOOLS}


def _mentions(text: str, tools) -> bool:
    return any(re.search(rf"\b{re.escape(tool)}\b", text) for tool in tools)


def _strip_from_lists(text: str, tools) -> str:
    for tool in tools:
        escaped = re.escape(tool)
        text = re.sub(rf"\*\*{escaped}\*\*", tool, text)
        text = re.sub(
            rf"\b{escaped}\s*(?:/|\+|\bor\b|\band\b)\s*(?=[A-Z*])", "", text
        )
        text = re.sub(rf"\s*(?:/|\+|\bor\b|\band\b)\s*{escaped}\b", "", text)
    return text


def _rewrite_tool_list(sentence: str, tools) -> str:
    match = re.match(r"(\s*The agent can (?:only )?use:\s*)(.*?)(\.?)$", sentence)
    if not match:
        return sentence
    items = [
        item
        for item in re.split(r",\s*", match.group(2))
        if not _mentions(item, tools)
    ]
    return f"{match.group(1)}{', '.join(items)}{match.group(3)}"


_SENT_SPLIT = re.compile(r"(?<=[.!?;])\s+")
_LABEL = re.compile(r"^(\*\*[^*]+\*\*[^:.]*:\s*)")


def scrub_disabled_tool_guidance(text: str, disabled=None) -> str:
    """Remove instructions for tools disabled in an ablation run."""
    disabled = get_disabled_tools() if disabled is None else set(disabled)
    if not disabled or not text:
        return text

    output = []
    for line in text.split("\n"):
        if not _mentions(line, disabled):
            output.append(line)
            continue
        stripped = line.lstrip()
        if stripped.startswith("#"):
            output.append(line)
            continue
        if '"status"' in line:
            output.append(_strip_from_lists(line, disabled))
            continue

        indent = line[: len(line) - len(stripped)]
        bullet = re.match(r"^((?:[-*]|\d+\.)\s+)", stripped)
        prefix = bullet.group(1) if bullet else ""
        body = stripped[len(prefix):]
        label_match = _LABEL.match(body)
        label = label_match.group(1) if label_match else ""
        if label and _mentions(label, disabled):
            continue
        body = body[len(label):]
        sentences = _SENT_SPLIT.split(body)
        if sentences and re.match(r"\s*The agent can (?:only )?use:", sentences[0]):
            sentences[0] = _rewrite_tool_list(sentences[0], disabled)
        sentences = [
            _strip_from_lists(sentence, disabled)
            if not re.match(r"\s*The agent can", sentence)
            else sentence
            for sentence in sentences
        ]
        if not label and sentences and _mentions(sentences[0], disabled):
            continue
        kept = [
            sentence
            for sentence in sentences
            if sentence.strip() and not _mentions(sentence, disabled)
        ]
        if kept:
            output.append(f"{indent}{prefix}{label}{' '.join(kept)}")
    return "\n".join(output)


def get_disabled_tools_notice() -> str:
    disabled = get_disabled_tools()
    if not disabled:
        return ""
    names = ", ".join(sorted(disabled))
    return (
        "### Unavailable tools\n"
        f"The following tools are NOT available in this run and cannot be called: "
        f"{names}. Use only the tools listed in Available Tools.\n"
    )


# ── Duration routing ─────────────────────────────────────────────
# Routing only selects duration-specific prompt sections; the reject cap is one value for
# every duration (--max-reflect-rejects, SEL_MAX_REFLECT_REJECTS in configs/common_env.sh).
SHORT_VIDEO_MAX_SEC = 60
MEDIUM_VIDEO_MAX_SEC = 600


def get_video_length_band(duration_sec: float) -> str:
    """Canonical duration definition shared by Selector and Reflector."""
    if duration_sec <= SHORT_VIDEO_MAX_SEC:
        return "short"
    if duration_sec <= MEDIUM_VIDEO_MAX_SEC:
        return "medium"
    return "long"


def get_duration_routing(duration_sec: float) -> dict:
    band = get_video_length_band(duration_sec)
    return {
        "long_video_section": duration_sec > 30,   # Reflector duration section (none for <=30s)
        "react_section": band,                     # Selector duration section, one band only
        "duration_band": band,
    }


def get_frame_budget_section() -> str:
    """Duration-independent submission rules; the per-band frame range is in get_duration_section."""
    return (
        "### Evidence Budget\n"
        "- Send Reflect a sufficient, non-redundant set: every frame needed to show the answer, no padding "
        "with irrelevant or near-duplicate frames.\n"
        f"- Reflect accepts at most {_env('TAKA_REFLECT_MAX_FRAMES')} frames; submitting more fails the question."
    )


def get_label_strategy_section() -> str:
    """Compatibility hook retained for callers; explicit question labels were removed."""
    return ""


def get_coverage_precision_section() -> str:
    return _COVERAGE_PRECISION_SECTION.replace("{max_images}", _env("TAKA_OBS_MAX_IMAGES"))


_COVERAGE_PRECISION_SECTION = """### Tool strategy: use the tool that closes the current evidence gap
- **Search** with mode="cover" is the map of the video (or of a time window): frames spread over the timeline, biased toward relevant scenes. Use it when the answer requires broad coverage, the target location is unknown, required events may be far apart, or events must be counted or ordered. If a concrete searchable cue points to one moment, cover is optional.
- **Search** with mode="focus" is a semantic pointer: the best frame of the few scenes matching a concrete visible event, object, person, or state. Give separate events separate queries (they can share one call); do not put candidate letters or unsupported conclusions in the query.
- **Similar** finds other moments that look like a frame you already have: re-identify a person or object, count recurrences, or find where a place returns.
- **Extract** reads a known interval: mode="uniform" verifies appearance or state and gives balanced local context; mode="motion" verifies actions, transitions, and before/after relations.
- **Review** shows frames returned earlier again. Earlier observation images leave your context, so instead of memorizing what each frame shows, Review the frames you need to re-check, for example before choosing Reflect frames.
- **Enhance** shows up to 3 whole frames you already have at higher resolution, to confirm an attribute (color, clothing, identity, posture) before relying on it.
- **Crop** zooms into a region of one frame at native resolution. Observation frames are downscaled, so use Crop to read small text or check small objects, faces, or fine detail.
- **Reflect** hands the selected frames (and optional crops) to the independent answerer on the same model endpoint. CONFIRM returns the answer and ends the task; REJECT returns the evidence gap and a recovery suggestion.

No subtitle track or audio is available: you only have the video frames. Search matches what is visible, not what is said, so never put the quoted words themselves into a query. When a question anchors on a subtitle or a line of speech ("when the subtitle says ..."), first reason about what is probably on screen while it is said: who would say it, to whom, where, and doing what. Then search for that visible scene in a short query, and use the answer candidates and the question's other details to narrow it down. Text burned into the picture (captions, signs, on-screen subtitles) can be read with Crop on a frame where it appears. Search and Similar return small previews: they show where to look, not fine detail.

### Verification routes
- **Leads to evidence.** Never accept or reject a lead from a small preview alone. Look closer step by step: Review or Extract (larger view) -> Enhance (whole frame, high resolution) -> Crop (one region at native resolution). If the previews "do not match" a described attribute such as a color or clothing, check one or two candidate frames this way before searching again with reworded queries.
- **Small details (text, logos, icons, web addresses, small objects) and positions.** The retriever cannot match them, and it does not understand positions ("on the left", "in the top corner", "next to the door"). Search for the scene by its large visible content (people, background, screen arrangement); once you have the frame, use Crop on the region where the detail or position should be.
- **What someone is doing, or how something moves or changes.** One frame rarely shows an action. When you have found the moment, Extract the interval around it (mode="motion", or uniform over a few seconds) and submit consecutive frames from just before to just after.
- **The order of events or a relation between moments.** Find each event involved separately (one focus query per event, in one call) and submit at least one frame of each.
- **Several results partly match the description.** Scenes often recur, so the first plausible match may be the wrong one. Before choosing, look at each candidate moment more closely (Extract around it, or Similar to find look-alikes) and compare it against the distinguishing details the question gives (people, clothing, place, objects, what is happening). Choose the moment that matches all of them, not the most prominent one; do not drop a candidate over one detail you cannot verify when the others match.
- **After a REJECT that names an unclear or too-small detail.** Enhance or Crop the frames you already have before searching for new ones.
- **Counting or repeated events.** Cover the relevant window, use Similar or Extract to find each occurrence, and Review the candidates before Reflect.

Batch independent work into one call: several Search queries, several Extract intervals, or several Crop regions. One observation holds at most {max_images} images.

Coverage search is a broad visual identification pass: use it when broad context or an unknown location matters, not as a ritual."""


def get_exploration_strategy_section() -> str:
    return """### Evidence-first operating loop
Repeat this loop until the evidence is sufficient:
1. **Think:** name the specific fact, event, identity, relation, count, or coverage gap still missing.
2. **Act:** make exactly one tool call chosen to close that gap.
3. **Observe:** separate leads from confirmed visual evidence. Tool scores, segment labels, and query matches are leads; visible pixels in returned frames are evidence.

After each observation, either verify the lead with Extract or Crop, investigate a genuinely different gap, or call Reflect. Batch coverage within one tool call where its schema allows it. Reuse known intervals and frame IDs instead of repeating near-identical searches.

For temporal questions, collect the minimum states needed to establish the relation (for example before + action/result, or event A + event B). For counting or whole-video claims, use evidence distributed across the relevant timeline rather than extrapolating from one segment."""


def get_start_broad_rule() -> str:
    return (
        "- Use Search with mode=\"cover\" before zooming into one interval when broad "
        "coverage or an unknown location is part of the evidence obligation."
    )


REJECT_RECOVERY_SECTION = """
### After a Reflector REJECT
A REJECT names the visible fact the Reflector still needs. Your job is to work out how that fact can be supplied, not to search for its wording.
- First ask where the missing fact would be visible: in a frame you already have (look closer with Review, Enhance, or Crop), right before or after a frame you have (Extract around it), or in a scene you have not found yet (Search for that scene).
- Do not paste `missing_evidence` or `suggestion` text into Search as the query. The Reflector describes facts ("the text on the sign", "what he does next", "when the subtitle says ..."); Search can only find visible scenes. Turn the fact into the scene where it would appear, in a short query.
- If a query already failed to find it, rewording the same idea will not help: change the visual hypothesis (another person, place, or moment that would accompany the fact), the time window, or the tool.
- You do not have to change your approach when it is working; supply what is missing and keep the confirmed frames.
- Do not call Reflect again without new frames that address the gap: an already judged frame set is not sent to the Reflector again.
"""


REACT_SHORT_VIDEO_SECTION = """
### This is a short video ({video_duration:.0f}s)
All of it fits in one or two observations, so the risk is over-searching, not missing a distant part.
- A cover Search over the whole video is a cheap first look and usually shows where the answer is; then verify the decisive moment with Extract, Enhance, or Crop.
- Once the decisive moment is visible, call Reflect. Do not keep searching for confirmation the frames already give.
- Evidence: usually {frame_range} frames. Fewer when one frame clearly shows the fact; more when the question needs several moments or an action over time.
"""


REACT_MEDIUM_VIDEO_SECTION = """
### This is a medium-length video ({video_duration:.0f}s)
Let the missing evidence determine the search breadth.
- When one distinctive cue can identify the decisive interval, find it with a focus Search and verify that interval; do not survey unrelated portions.
- When evidence may span the timeline or multiple events, use a cover Search for coverage, then verify weak or decisive intervals with Extract.
- Do not mistake one relevant segment for whole-video coverage. Avoid more than two consecutive calls on one interval unless each call reveals new evidence.
- Evidence: usually {frame_range} frames, covering every moment the question depends on.
"""


REACT_LONG_VIDEO_SECTION = """
### This is a long video ({video_duration:.0f}s)
The main risks are searching only one part of the timeline and over-sampling one hit.
- When the answer requires repeated events, counting, distant events, or whole-video coverage, start with a cover Search, then open targeted branches for each missing fact.
- When one distinctive cue can identify the decisive interval, a focus Search may come first; use a cover Search only if the location remains uncertain or wider context is required.
- If repeated searches keep returning the same part of the video without the decisive evidence, the answer may be elsewhere: search other parts of the timeline instead of refining the same interval.
- Once a useful interval is found, switch from search to Extract verification. Do not spend more than two consecutive calls on the same interval without new evidence.
- Evidence: usually {frame_range} frames. A claim about the timeline needs temporally distributed evidence; a claim about one moment needs precise, readable evidence rather than broad padding.
"""


_DURATION_SECTIONS = {"short": (REACT_SHORT_VIDEO_SECTION, "TAKA_FRAME_BUDGET_SHORT"),
                      "medium": (REACT_MEDIUM_VIDEO_SECTION, "TAKA_FRAME_BUDGET_MEDIUM"),
                      "long": (REACT_LONG_VIDEO_SECTION, "TAKA_FRAME_BUDGET_LONG")}


def get_duration_section(duration_sec: float) -> str:
    """The Selector guidance for this video's duration band only (the code picks the band)."""
    template, budget_var = _DURATION_SECTIONS[get_video_length_band(duration_sec)]
    return template.format(video_duration=duration_sec, frame_range=_env(budget_var))


TRAJECTORY_LEDGER_SECTION = """
### Compact Evidence Ledger
Observation images are removed from your context once the next visual observation arrives; your earlier reasoning stays. Do not describe frames in detail to remember them: use Review to look at them again when needed. After each observation, write only what changed, by frame id:
- Status: one short line each for confirmed facts (with their frame ids), the open lead (frame ids or time window), and the missing evidence.
- Next: why the next tool closes that gap, or why Reflect is justified.

Keep each turn's reasoning short and precise:
- Mention only frames that matter for the question, one line each; skip irrelevant frames entirely instead of describing them.
- Do not restate the question or the answer candidates, and do not re-list frames from earlier turns.
- If the target was not found, say so in one line, pick the single most likely visual hypothesis, and test it with the next call. Do not speculate through many alternatives in one turn.

Never rewrite the ledger from earlier turns, and do not write the final answer in it.
"""


def get_evidence_ledger_section() -> str:
    return TRAJECTORY_LEDGER_SECTION


REACT_SYSTEM_PROMPT = """You are the Selector, a multimodal evidence planner for Video QA.

Your job is to navigate a {video_duration:.0f}-second video ({total_frames} sampled frames) and hand the Reflector a sufficient, non-redundant set of frames. Do NOT answer the question yourself. Prior knowledge may help form search hypotheses, but only pixels actually observed in tool-returned frames count as visual evidence.

## Question
{question}

## Answer Candidates
For an open-ended task this section says that no candidates were provided. In that
case, search for the visual evidence needed to answer the question rather than trying
to invent options.
{candidates}

## Available Tools
{tools_schema}

## Tool-call Protocol
On every turn, call exactly one function from the provided tools using the model's native tool-call format. Put the compact evidence state—what is confirmed, what is only a lead, what is missing, and why this call is next—in your reasoning. Do not print a JSON action object or describe a tool call without making it.

Never invent tool names, arguments, frame IDs, timestamps, observations, or results.

## Planning and Verification

{frame_budget_section}

{label_strategy_section}

{coverage_precision_section}

{exploration_strategy_section}

{duration_section}

{task_specific_section}

### When to Reflect
- Reflect does not use search steps, and a REJECT names exactly what evidence is missing. When two or three searches stop adding new evidence, call Reflect with your best frames instead of searching again; use the REJECT to decide the next search.
- Call Reflect only when the frames positively support an evidence-grounded answer (or one candidate when candidates exist) and contain every visible state needed by the question.
- Do not rely on candidate wording, world knowledge, or unsupported elimination of alternatives.
- For attributes, text, identity, count, spatial layout, or object state, require frames where that detail is actually readable or visible.
- For actions and temporal relations, include the decisive states in temporal order.
- Select decisive frames plus only the context needed to interpret them; exclude accidental matches and duplicates.
{reject_recovery_section}
## Hard Rules
- Do not answer the question; only select evidence.
- Search scores are leads, not proof. Before Reflect, make sure each decisive fact is visible in a returned frame; use Extract or Crop to verify it when it is not.
{start_broad_rule}
- If three consecutive searches add no useful evidence, change strategy: change the interval, visual hypothesis, tool, or scope.
- If a tool returns no useful result, record that failure and try a materially different route.
- You have {max_steps} search steps (every tool call except Reflect uses one). Once they are used up, search calls are no longer executed and you may only call Reflect.
- Call exactly one tool per turn. Several tool calls in one turn are not executed.
- Do not loop: repeating the exact same call returns the same result. From the 3rd identical call you get a warning; the 5th identical call, or 5 tool errors in a row, fails the question.
- Reflect `frame_ids` must be integer frame IDs returned by tools; `crop_ids` must be crop ids returned by Crop, for frames you also submit.
- Visual memory is volatile. Track decisive frames by id in the ledger and Review them instead of re-describing them.
"""
