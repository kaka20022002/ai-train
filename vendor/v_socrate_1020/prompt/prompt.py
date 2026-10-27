"""Backward-compatible exports for the split Selector and Reflector prompts.

New code may import directly from ``selector`` or ``reflector``. Existing runners
continue to import from ``prompt`` so experiment entry points remain unchanged.
"""

from .reflector import (
    REFLECT_EXTENDED_VIDEO_SECTION,
    REFLECT_LONG_VIDEO_SECTION,
    REFLECT_MEDIUM_VIDEO_SECTION,
    REFLECT_SYSTEM_PROMPT_SELFROUTE,
    get_reflector_duration_section,
)
from .selector import (
    ABLATABLE_TOOLS,
    MEDIUM_VIDEO_MAX_SEC,
    REACT_LONG_VIDEO_SECTION,
    REACT_MEDIUM_VIDEO_SECTION,
    REACT_SHORT_VIDEO_SECTION,
    REACT_SYSTEM_PROMPT,
    REJECT_RECOVERY_SECTION,
    SHORT_VIDEO_MAX_SEC,
    TRAJECTORY_LEDGER_SECTION,
    get_coverage_precision_section,
    get_disabled_tools,
    get_disabled_tools_notice,
    get_duration_section,
    get_duration_routing,
    get_evidence_ledger_section,
    get_exploration_strategy_section,
    get_frame_budget_section,
    get_label_strategy_section,
    get_start_broad_rule,
    get_video_length_band,
    scrub_disabled_tool_guidance,
)

__all__ = [
    "ABLATABLE_TOOLS",
    "MEDIUM_VIDEO_MAX_SEC",
    "REACT_LONG_VIDEO_SECTION",
    "REACT_MEDIUM_VIDEO_SECTION",
    "REACT_SHORT_VIDEO_SECTION",
    "REACT_SYSTEM_PROMPT",
    "REFLECT_EXTENDED_VIDEO_SECTION",
    "REFLECT_LONG_VIDEO_SECTION",
    "REFLECT_MEDIUM_VIDEO_SECTION",
    "REFLECT_SYSTEM_PROMPT_SELFROUTE",
    "REJECT_RECOVERY_SECTION",
    "SHORT_VIDEO_MAX_SEC",
    "TRAJECTORY_LEDGER_SECTION",
    "get_coverage_precision_section",
    "get_disabled_tools",
    "get_disabled_tools_notice",
    "get_duration_section",
    "get_duration_routing",
    "get_evidence_ledger_section",
    "get_exploration_strategy_section",
    "get_frame_budget_section",
    "get_label_strategy_section",
    "get_reflector_duration_section",
    "get_start_broad_rule",
    "get_video_length_band",
    "scrub_disabled_tool_guidance",
]
