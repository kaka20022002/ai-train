"""
Training History Analyzer — Phase 2 of Adaptive Coaching System
================================================================

Transforms raw training session records into two outputs:

1. HistorySummary  — structured dataclass with all computed metrics
2. llm_context_text — natural-language block injected into the LLM system prompt

Analysis covers:
  - RPE trend detection  (overtraining / undertraining / stable)
  - Pain recurrence pattern recognition
  - Fatigue & sleep accumulation scoring
  - Deload week recommendation (rule-based)
  - Training consistency vs target frequency
  - Intensity direction recommendation for next session
  - Progressive overload readiness (when exercise_performance data is present)

Usage
-----
    from history_analyzer import analyze_history

    summary = analyze_history(sessions_dicts, user_profile_dict)
    print(summary.llm_context_text)    # inject into LLM prompt
    print(summary.intensity_direction)  # "reduce" | "maintain" | "increase"
    print(summary.deload_recommended)   # True / False
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Dict, List, Optional


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class ProgressionSignal:
    """
    Indicates whether a specific exercise is showing progressive overload.
    Populated only when exercise_performance data is present in sessions.
    """
    exercise_name: str
    sessions_tracked: int
    avg_weight_kg: Optional[float] = None
    weight_trend: str = "unknown"          # "increasing" | "stable" | "decreasing" | "unknown"
    avg_reps_last: Optional[float] = None  # average reps in last tracked set
    recommendation: str = ""


@dataclass
class HistorySummary:
    """
    All computed metrics from the user's recent training history.
    The *llm_context_text* field is a pre-formatted string ready for injection
    into the LLM system / user prompt.
    """

    # ── Basic ─────────────────────────────────────────────────────────────────
    session_count: int = 0
    calendar_days_span: int = 0        # days between oldest and newest session

    # ── RPE ───────────────────────────────────────────────────────────────────
    avg_rpe: float = 0.0
    latest_rpe: Optional[int] = None
    rpe_trend: str = "stable"          # "increasing" | "stable" | "decreasing"
    consecutive_high_rpe: int = 0      # consecutive sessions (tail) with RPE ≥ 8
    consecutive_low_rpe: int = 0       # consecutive sessions (tail) with RPE ≤ 4

    # ── Pain / injury ─────────────────────────────────────────────────────────
    pain_sessions_count: int = 0
    recurring_pain_locations: List[str] = field(default_factory=list)
    latest_pain_location: Optional[str] = None
    latest_pain_severity: Optional[int] = None

    # ── Fatigue & sleep ───────────────────────────────────────────────────────
    avg_fatigue: Optional[float] = None
    avg_sleep_quality: Optional[float] = None
    high_fatigue_sessions: int = 0     # sessions where fatigue ≥ 7
    poor_sleep_sessions: int = 0       # sessions where sleep ≤ 4

    # ── Completion ────────────────────────────────────────────────────────────
    avg_completion_rate: Optional[float] = None

    # ── Progressive overload ─────────────────────────────────────────────────
    progression_signals: List[ProgressionSignal] = field(default_factory=list)

    # ── Coaching decisions ────────────────────────────────────────────────────
    deload_recommended: bool = False
    deload_reason: Optional[str] = None
    intensity_direction: str = "maintain"   # "reduce" | "maintain" | "increase"
    volume_direction: str = "maintain"      # "reduce" | "maintain" | "increase"
    coaching_notes: List[str] = field(default_factory=list)

    # ── LLM context (output) ─────────────────────────────────────────────────
    llm_context_text: str = ""


# =============================================================================
# Public API
# =============================================================================

def analyze_history(
    sessions: List[Dict[str, Any]],
    user_profile: Optional[Dict[str, Any]] = None,
    window: int = 10,
) -> HistorySummary:
    """
    Analyze the most recent *window* training sessions.

    Args:
        sessions : List of session dicts. Each dict must contain at minimum
                   { "date": "YYYY-MM-DD", "rpe": int,
                     "pain_feedback": {"has_pain": bool, ...} }.
                   Optionally: fatigue_feedback, completion_rate,
                   exercise_performance.
        user_profile : Optional user profile dict. Used for consistency check
                       (training_frequency target vs actual).
        window   : Maximum number of recent sessions to analyse (default 10).

    Returns:
        HistorySummary — all fields populated, llm_context_text ready to inject.
    """
    if not sessions:
        s = HistorySummary()
        s.llm_context_text = (
            "【历史训练记录】\n"
            "  暂无历史数据，这是用户的第一次训练。请根据用户当前档案生成一份适合入门/热身的基础训练计划。"
        )
        return s

    # Sort by date descending, take window, then re-sort ascending for trends
    recent_desc = sorted(
        sessions, key=lambda s: s.get("date", ""), reverse=True
    )[:window]
    chronological = list(reversed(recent_desc))

    summary = HistorySummary(session_count=len(chronological))

    _compute_calendar_span(summary, chronological)
    _compute_rpe_metrics(summary, chronological)
    _compute_pain_metrics(summary, chronological)
    _compute_fatigue_metrics(summary, chronological)
    _compute_completion_metrics(summary, chronological)
    _compute_progression_signals(summary, chronological)
    _apply_coaching_logic(summary, user_profile, chronological)
    summary.llm_context_text = _build_llm_context(summary, user_profile, chronological)

    return summary


# =============================================================================
# Internal computation helpers
# =============================================================================

def _compute_calendar_span(summary: HistorySummary, sessions: List[Dict]) -> None:
    dates = []
    for s in sessions:
        d = s.get("date")
        if d:
            try:
                dates.append(date.fromisoformat(d))
            except ValueError:
                pass
    if len(dates) >= 2:
        summary.calendar_days_span = (max(dates) - min(dates)).days


def _compute_rpe_metrics(summary: HistorySummary, sessions: List[Dict]) -> None:
    rpe_values = [s["rpe"] for s in sessions if s.get("rpe") is not None]
    if not rpe_values:
        return

    summary.avg_rpe = round(statistics.mean(rpe_values), 1)
    summary.latest_rpe = rpe_values[-1]

    # Trend: compare average of first half vs second half
    mid = max(len(rpe_values) // 2, 1)
    first_half = statistics.mean(rpe_values[:mid])
    second_half = statistics.mean(rpe_values[mid:]) if len(rpe_values) > mid else first_half
    delta = second_half - first_half

    if delta >= 1.0:
        summary.rpe_trend = "increasing"
    elif delta <= -1.0:
        summary.rpe_trend = "decreasing"
    else:
        summary.rpe_trend = "stable"

    # Consecutive high / low RPE (scan from tail)
    for rpe in reversed(rpe_values):
        if rpe >= 8:
            summary.consecutive_high_rpe += 1
        else:
            break

    for rpe in reversed(rpe_values):
        if rpe <= 4:
            summary.consecutive_low_rpe += 1
        else:
            break


def _compute_pain_metrics(summary: HistorySummary, sessions: List[Dict]) -> None:
    location_counts: Dict[str, int] = {}

    for s in sessions:
        pf = s.get("pain_feedback") or {}
        if pf.get("has_pain"):
            summary.pain_sessions_count += 1
            loc = (pf.get("pain_location") or "").lower().strip()
            if loc:
                location_counts[loc] = location_counts.get(loc, 0) + 1

    # Recurring = appears in ≥ 2 sessions
    summary.recurring_pain_locations = [
        loc for loc, cnt in location_counts.items() if cnt >= 2
    ]

    latest_pf = sessions[-1].get("pain_feedback") or {}
    if latest_pf.get("has_pain"):
        summary.latest_pain_location = latest_pf.get("pain_location")
        summary.latest_pain_severity = latest_pf.get("pain_severity")


def _compute_fatigue_metrics(summary: HistorySummary, sessions: List[Dict]) -> None:
    fatigue_vals, sleep_vals = [], []

    for s in sessions:
        ff = s.get("fatigue_feedback") or {}
        f = ff.get("overall_fatigue")
        sl = ff.get("sleep_quality_last_night")
        if f is not None:
            fatigue_vals.append(f)
            if f >= 7:
                summary.high_fatigue_sessions += 1
        if sl is not None:
            sleep_vals.append(sl)
            if sl <= 4:
                summary.poor_sleep_sessions += 1

    if fatigue_vals:
        summary.avg_fatigue = round(statistics.mean(fatigue_vals), 1)
    if sleep_vals:
        summary.avg_sleep_quality = round(statistics.mean(sleep_vals), 1)


def _compute_completion_metrics(summary: HistorySummary, sessions: List[Dict]) -> None:
    vals = [s["completion_rate"] for s in sessions if s.get("completion_rate") is not None]
    if vals:
        summary.avg_completion_rate = round(statistics.mean(vals), 2)


def _compute_progression_signals(
    summary: HistorySummary, sessions: List[Dict]
) -> None:
    """
    Build per-exercise progression signals from exercise_performance data.
    Only sessions that include exercise_performance contribute.
    """
    # exercise_name → list of {weight_kg, reps_per_set} across sessions
    exercise_history: Dict[str, List[Dict]] = {}

    for s in sessions:
        perfs = s.get("exercise_performance") or []
        for p in perfs:
            name = p.get("name", "").strip()
            if not name:
                continue
            if name not in exercise_history:
                exercise_history[name] = []
            exercise_history[name].append(p)

    for name, history in exercise_history.items():
        if len(history) < 2:
            continue  # need at least 2 data points for a trend

        weights = [h.get("weight_kg") for h in history if h.get("weight_kg") is not None]
        signal = ProgressionSignal(
            exercise_name=name,
            sessions_tracked=len(history),
        )

        if len(weights) >= 2:
            signal.avg_weight_kg = round(statistics.mean(weights), 1)
            w_delta = weights[-1] - weights[0]
            if w_delta > 0:
                signal.weight_trend = "increasing"
                signal.recommendation = f"重量持续提升（+{round(w_delta, 1)} kg），保持渐进超负荷"
            elif w_delta < -2.5:
                signal.weight_trend = "decreasing"
                signal.recommendation = "重量有所下降，可能存在疲劳或技术问题，暂维持当前重量"
            else:
                signal.weight_trend = "stable"
                signal.recommendation = "重量稳定，可考虑微小增重（+2.5 kg）或增加组数"

        # Last-session average reps
        last_reps = history[-1].get("reps_per_set") or []
        if last_reps:
            signal.avg_reps_last = round(statistics.mean(last_reps), 1)

        summary.progression_signals.append(signal)


# =============================================================================
# Coaching logic
# =============================================================================

def _apply_coaching_logic(
    summary: HistorySummary,
    user_profile: Optional[Dict[str, Any]],
    sessions: List[Dict],
) -> None:
    """
    Apply rule-based coaching decisions. Mutates summary in place.

    Deload trigger rules (any one is sufficient):
      R1. ≥ 3 consecutive sessions with RPE ≥ 8
      R2. avg_fatigue ≥ 7 AND avg_sleep_quality ≤ 5
      R3. ≥ 1 recurring pain location (same joint ≥ 2 sessions)
      R4. high_fatigue_sessions >= ceil(session_count * 0.6) — majority fatigued
    """
    deload_reasons = []

    # R1 — chronic overexertion
    if summary.consecutive_high_rpe >= 3:
        deload_reasons.append(
            f"连续 {summary.consecutive_high_rpe} 次训练 RPE ≥ 8（疲劳持续积累）"
        )

    # R2 — high fatigue + poor sleep
    if (
        summary.avg_fatigue is not None
        and summary.avg_sleep_quality is not None
        and summary.avg_fatigue >= 7
        and summary.avg_sleep_quality <= 5
    ):
        deload_reasons.append(
            f"平均疲劳度 {summary.avg_fatigue}/10 + 平均睡眠 {summary.avg_sleep_quality}/10（恢复不足）"
        )

    # R3 — recurring pain
    if summary.recurring_pain_locations:
        locs = "、".join(summary.recurring_pain_locations)
        deload_reasons.append(f"反复疼痛部位：{locs}（需要减负恢复）")

    # R4 — majority of sessions were high-fatigue
    if (
        summary.session_count >= 3
        and summary.high_fatigue_sessions >= round(summary.session_count * 0.6)
    ):
        deload_reasons.append(
            f"{summary.high_fatigue_sessions}/{summary.session_count} 次训练疲劳度 ≥ 7"
        )

    summary.deload_recommended = bool(deload_reasons)
    summary.deload_reason = "；".join(deload_reasons) if deload_reasons else None

    # ── Intensity direction ───────────────────────────────────────────────────
    if summary.deload_recommended:
        summary.intensity_direction = "reduce"
        summary.volume_direction = "reduce"
    elif summary.consecutive_low_rpe >= 2 or (
        summary.avg_rpe < 5 and summary.rpe_trend != "increasing"
    ):
        summary.intensity_direction = "increase"
        summary.volume_direction = "maintain"
    elif summary.rpe_trend == "increasing" and summary.avg_rpe >= 7.5:
        # Trending up and already moderate-high — hold before pushing further
        summary.intensity_direction = "maintain"
        summary.volume_direction = "maintain"
    else:
        summary.intensity_direction = "maintain"
        summary.volume_direction = "maintain"

    # ── Coaching notes ────────────────────────────────────────────────────────
    if summary.avg_completion_rate is not None and summary.avg_completion_rate < 0.70:
        summary.coaching_notes.append(
            f"计划完成率偏低（{int(summary.avg_completion_rate*100)}%），"
            "建议适当减少训练量或缩短单次时长。"
        )

    if summary.progression_signals:
        stalling = [
            p.exercise_name for p in summary.progression_signals
            if p.weight_trend == "stable" and p.sessions_tracked >= 3
        ]
        if stalling:
            summary.coaching_notes.append(
                f"以下动作重量已停滞 ≥3 次，可考虑微调（+2.5 kg 或改变训练变量）：{', '.join(stalling)}"
            )


# =============================================================================
# LLM context builder
# =============================================================================

def _build_llm_context(
    summary: HistorySummary,
    user_profile: Optional[Dict[str, Any]],
    sessions: List[Dict],
) -> str:
    lines: List[str] = [
        "=" * 60,
        "📊 用户历史训练分析（AI 教练上下文）",
        "=" * 60,
        f"分析范围：最近 {summary.session_count} 次训练"
        + (f"（跨度 {summary.calendar_days_span} 天）" if summary.calendar_days_span > 0 else ""),
        "",
    ]

    # ── RPE ──────────────────────────────────────────────────────────────────
    lines.append("【训练强度趋势 (RPE)】")
    lines.append(f"  平均 RPE：{summary.avg_rpe}/10 ｜ 最新：{summary.latest_rpe}/10")
    trend_label = {
        "increasing": "⬆️ 持续攀升（疲劳积累风险）",
        "decreasing": "⬇️ 逐渐下降（身体适应或训练量不足）",
        "stable":     "➡️ 基本平稳",
    }.get(summary.rpe_trend, summary.rpe_trend)
    lines.append(f"  RPE 趋势：{trend_label}")
    if summary.consecutive_high_rpe >= 2:
        lines.append(
            f"  ⚠️  已连续 {summary.consecutive_high_rpe} 次 RPE ≥ 8"
        )
    if summary.consecutive_low_rpe >= 2:
        lines.append(
            f"  📈 已连续 {summary.consecutive_low_rpe} 次 RPE ≤ 4（负荷可能不足）"
        )
    lines.append("")

    # ── Pain ─────────────────────────────────────────────────────────────────
    lines.append("【疼痛与伤病信号】")
    if summary.pain_sessions_count == 0:
        lines.append("  无疼痛报告 ✅")
    else:
        lines.append(
            f"  有疼痛记录的训练次数：{summary.pain_sessions_count}/{summary.session_count}"
        )
        if summary.recurring_pain_locations:
            lines.append(
                f"  🔴 反复疼痛部位（≥2次）：{', '.join(summary.recurring_pain_locations)}"
            )
        if summary.latest_pain_location:
            sev_str = (
                f"（严重度 {summary.latest_pain_severity}/10）"
                if summary.latest_pain_severity else ""
            )
            lines.append(f"  最新疼痛部位：{summary.latest_pain_location}{sev_str}")
    lines.append("")

    # ── Fatigue & sleep ───────────────────────────────────────────────────────
    if summary.avg_fatigue is not None or summary.avg_sleep_quality is not None:
        lines.append("【疲劳与恢复状态】")
        if summary.avg_fatigue is not None:
            lines.append(
                f"  平均疲劳度：{summary.avg_fatigue}/10"
                + (f"  （{summary.high_fatigue_sessions} 次高疲劳≥7）"
                   if summary.high_fatigue_sessions else "")
            )
        if summary.avg_sleep_quality is not None:
            lines.append(
                f"  平均睡眠质量：{summary.avg_sleep_quality}/10"
                + (f"  （{summary.poor_sleep_sessions} 次睡眠不足≤4）"
                   if summary.poor_sleep_sessions else "")
            )
        lines.append("")

    # ── Completion ───────────────────────────────────────────────────────────
    if summary.avg_completion_rate is not None:
        lines.append("【训练完成率】")
        pct = int(summary.avg_completion_rate * 100)
        emoji = "✅" if pct >= 85 else ("⚠️" if pct >= 70 else "🔴")
        lines.append(f"  平均完成率：{pct}% {emoji}")
        lines.append("")

    # ── Progression signals ──────────────────────────────────────────────────
    if summary.progression_signals:
        lines.append("【动作进步追踪】")
        for sig in summary.progression_signals[:5]:  # top 5
            trend_emoji = {"increasing": "📈", "stable": "➡️", "decreasing": "📉"}.get(
                sig.weight_trend, "❓"
            )
            weight_str = f" | 均重 {sig.avg_weight_kg} kg" if sig.avg_weight_kg else ""
            lines.append(
                f"  {trend_emoji} {sig.exercise_name}{weight_str} — {sig.recommendation}"
            )
        lines.append("")

    # ── Coaching decision ────────────────────────────────────────────────────
    lines.append("【AI 教练指令（本次计划方向）】")
    if summary.deload_recommended:
        lines.append("  🔴 本次必须安排减量训练（Deload Week）")
        if summary.deload_reason:
            lines.append(f"  触发原因：{summary.deload_reason}")
        lines.append(
            "  执行要求：组数减少 30-40%，重量降低 20-30%，"
            "注重动作控制和关节活动度，不追求强度。"
        )
    elif summary.intensity_direction == "increase":
        lines.append("  📈 用户恢复良好，本次可实施渐进超负荷")
        lines.append(
            "  执行要求：在上一次计划基础上适度增重（+2.5~5 kg）"
            "或每个主项增加 1 组，保持技术规范。"
        )
    else:
        lines.append("  ✅ 维持当前训练强度，保持训练一致性")

    if summary.coaching_notes:
        lines.append("")
        lines.append("  附加提示：")
        for note in summary.coaching_notes:
            lines.append(f"    · {note}")

    # ── Recent session log ───────────────────────────────────────────────────
    lines.append("")
    lines.append("【最近训练流水（最多显示最近 5 次）】")
    shown = sessions[-5:]
    for i, s in enumerate(shown, 1):
        pf = s.get("pain_feedback") or {}
        pain_str = ""
        if pf.get("has_pain"):
            pain_str = f" | 疼痛:{pf.get('pain_location', '?')}"
        cr_str = ""
        if s.get("completion_rate") is not None:
            cr_str = f" | 完成率:{int(s['completion_rate'] * 100)}%"
        lines.append(
            f"  {i}. {s.get('date', '?')} — "
            f"RPE {s.get('rpe', '?')}/10 | 类型:{s.get('workout_type', '?')}"
            f"{cr_str}{pain_str}"
        )

    lines.append("=" * 60)
    return "\n".join(lines)
