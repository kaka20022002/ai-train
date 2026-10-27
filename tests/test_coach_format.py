"""教练输出的排版契约：后端只保留「轻量 Markdown 子集」，前端才渲染得出来。

历史包袱：早期为了兼容不认 Markdown 的小程序 Text 组件，`sanitize_coach_plaintext`
把所有格式符号都剥掉，结果一份训练安排被压成一整段 —— 用户截图里的「1. 固定单车
4 分钟。 2. 踩车 20 次」就是换行被吃掉的样子。

现在后端与前端（`components/MarkdownLite.tsx`）约定同一套子集：
    ### 标题 / · 要点 / 1. 序号 / 两空格缩进的子要点
这些必须原样留下；加粗、表格、代码围栏仍要剥掉（旧客户端不会渲染）。
"""
from __future__ import annotations

import pytest

from coach_agent import (
    COACH_PROMPT_VERSION,
    COACH_SYSTEM_PROMPT,
    parse_action_request,
    sanitize_coach_plaintext,
)


class TestSanitizeKeepsLayout:
    def test_heading_survives(self) -> None:
        out = sanitize_coach_plaintext("### 结论\n\n可以做。")
        assert out.startswith("### 结论")
        assert "可以做。" in out

    def test_all_heading_levels_collapse_to_h3(self) -> None:
        out = sanitize_coach_plaintext("# 一级\n## 二级\n###### 六级")
        assert out.splitlines() == ["### 一级", "### 二级", "### 六级"]

    def test_bullet_variants_become_middot(self) -> None:
        out = sanitize_coach_plaintext("* 第一条\n- 第二条\n• 第三条\n· 第四条")
        assert out.splitlines() == ["· 第一条", "· 第二条", "· 第三条", "· 第四条"]

    def test_indented_sub_bullet_keeps_indent(self) -> None:
        src = "1. 臀桥 · 3 组 × 12 次\n  · 顶到收紧停 1 秒"
        out = sanitize_coach_plaintext(src)
        lines = out.splitlines()
        assert lines[0] == "1. 臀桥 · 3 组 × 12 次"
        assert lines[1] == "  · 顶到收紧停 1 秒"

    def test_blank_line_between_blocks_kept(self) -> None:
        out = sanitize_coach_plaintext("### 结论\n\n先说结论。\n\n· 要点")
        assert "\n\n先说结论。" in out

    def test_ordered_list_untouched(self) -> None:
        out = sanitize_coach_plaintext("1. 固定单车 · 5 分钟\n2. 臀桥 · 3 组 × 12 次")
        assert out.splitlines() == ["1. 固定单车 · 5 分钟", "2. 臀桥 · 3 组 × 12 次"]


class TestSanitizeStripsNoise:
    def test_bold_markers_removed(self) -> None:
        out = sanitize_coach_plaintext("**重要**：别蹲太深")
        assert out == "重要：别蹲太深"
        assert "**" not in out

    def test_code_fence_removed(self) -> None:
        out = sanitize_coach_plaintext("```json\n{\"a\": 1}\n```")
        assert "```" not in out
        assert '{"a": 1}' in out

    def test_table_separator_row_dropped(self) -> None:
        out = sanitize_coach_plaintext("| 动作 | 组数 |\n| --- | --- |\n| 臀桥 | 3 |")
        assert "---" not in out
        # 表格行本身留字，不渲染成表，但绝不能残留分隔线
        assert "臀桥" in out

    def test_horizontal_rule_dropped(self) -> None:
        out = sanitize_coach_plaintext("上\n\n---\n\n下")
        assert "---" not in out

    def test_excess_blank_lines_collapsed(self) -> None:
        out = sanitize_coach_plaintext("A\n\n\n\n\nB")
        assert "\n\n\n" not in out

    def test_trailing_spaces_stripped(self) -> None:
        out = sanitize_coach_plaintext("第一行   \n第二行\t")
        assert out == "第一行\n第二行"


class TestActionRequestSurvives:
    def test_block_still_parsed_after_sanitize(self) -> None:
        raw = (
            "### 结论\n\n可以练。\n\n"
            "[ACTION_REQUEST]\n"
            '{"tool": "generate_single_plan", "args": {"workout_type": "lower_body"}}\n'
            "[/ACTION_REQUEST]"
        )
        clean, action = parse_action_request(raw)
        clean = sanitize_coach_plaintext(clean)
        assert action is not None
        assert action.tool == "generate_single_plan"
        # JSON 绝不能漏进正文
        assert "generate_single_plan" not in clean
        assert "ACTION_REQUEST" not in clean


class TestPromptContract:
    def test_prompt_version_bumped(self) -> None:
        assert COACH_PROMPT_VERSION == "2.2.0"

    def test_prompt_no_longer_bans_markdown(self) -> None:
        assert "纯文本输出：不要使用 Markdown" not in COACH_SYSTEM_PROMPT

    def test_prompt_declares_layout_syntax(self) -> None:
        assert "### 标题" in COACH_SYSTEM_PROMPT
        assert "· " in COACH_SYSTEM_PROMPT
        assert "组 × " in COACH_SYSTEM_PROMPT

    def test_prompt_still_forbids_tables_and_code(self) -> None:
        assert "表格" in COACH_SYSTEM_PROMPT
        assert "代码块" in COACH_SYSTEM_PROMPT
