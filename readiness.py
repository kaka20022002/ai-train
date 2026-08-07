"""
Readiness Score Engine — Sprint 4 (#8)
======================================

Computes a 0–100 "training readiness" score from recently logged session data
(sleep, fatigue, stress, soreness, RPE load, recovery time, pain) and turns it
into an actionable recommendation for today's session.

Design
------
- A **weighted component model**: each available signal yields a 0–100 sub-score.
  Missing signals are simply dropped and the remaining weights renormalised, so
  the score degrades gracefully when a user logs only partial feedback.
- **Acute caps**: recent pain or several consecutive maximal-RPE sessions cap the
  final score regardless of the weighted average — these are safety overrides.

Bands
-----
    ≥ 80  prime     状态极佳，可冲击大重量/PR
    60–79 ready     状态良好，按计划训练
    40–59 caution   恢复不足，建议降低强度
    < 40  rest      强烈建议安排恢复/休息
"""
from __future__ import annotations

import statistics
from datetime import date
from typing import Any, Dict, List, Optional

# Component weights (relative; renormalised over available components).
_WEIGHTS = {
    "sleep": 0.30,
    "fatigue": 0.30,
    "stress": 0.15,
    "soreness": 0.10,
    "recovery": 0.15,
}


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _band(score: float) -> Dict[str, str]:
    if score >= 80:
        return {
            "band": "prime",
            "label": "状态极佳",
            "recommendation": "恢复充分，可冲击大重量或尝试 PR，按计划全力训练。",
        }
    if score >= 60:
        return {
            "band": "ready",
            "label": "状态良好",
            "recommendation": "身体已就绪，按计划正常训练，保持渐进超负荷。",
        }
    if score >= 40:
        return {
            "band": "caution",
            "label": "恢复不足",
            "recommendation": "恢复不充分，建议降低 10–20% 强度或减少 1 组，控制单次训练量。",
        }
    return {
        "band": "rest",
        "label": "建议恢复",
        "recommendation": "身体明显疲劳，建议安排主动恢复/休息日，或仅做轻度活动度训练。",
    }


def _suggested_modifier(score: float) -> float:
    """Intensity multiplier hint for the next session."""
    if score >= 80:
        return 1.05
    if score >= 60:
        return 1.0
    if score >= 40:
        return 0.85
    return 0.6


def compute_readiness(
    sessions: List[Dict[str, Any]],
    today: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute a readiness assessment from a user's recent sessions (newest first
    or any order — this function sorts internally).

    Returns a dict with score, band, label, recommendation, suggested
    intensity modifier, and a transparent list of contributing factors.
    """
    if not sessions:
        return {
            "score": None,
            "band": "unknown",
            "label": "暂无数据",
            "recommendation": "尚无训练记录，完成并记录一次训练后即可获得准备度评分。",
            "suggested_intensity_modifier": 1.0,
            "factors": [],
            "based_on_sessions": 0,
        }

    ordered = sorted(sessions, key=lambda s: s.get("date") or "", reverse=True)
    latest = ordered[0]
    ff = latest.get("fatigue_feedback") or {}

    components: Dict[str, float] = {}
    factors: List[Dict[str, Any]] = []

    # ── Sleep (latest) — higher is better ─────────────────────────────────────
    sleep = ff.get("sleep_quality_last_night")
    if sleep is not None:
        sub = _clamp(sleep / 10 * 100)
        components["sleep"] = sub
        factors.append(_factor("睡眠质量", f"{sleep}/10", sub))

    # ── Fatigue (latest) — lower is better ────────────────────────────────────
    fatigue = ff.get("overall_fatigue")
    if fatigue is not None:
        sub = _clamp((10 - fatigue) / 9 * 100)
        components["fatigue"] = sub
        factors.append(_factor("疲劳度", f"{fatigue}/10", sub))

    # ── Stress (latest) — lower is better ─────────────────────────────────────
    stress = ff.get("stress_level")
    if stress is not None:
        sub = _clamp((10 - stress) / 9 * 100)
        components["stress"] = sub
        factors.append(_factor("压力水平", f"{stress}/10", sub))

    # ── Muscle soreness (latest) — fewer areas is better ──────────────────────
    soreness = ff.get("muscle_soreness")
    if soreness is not None:
        n = len(soreness)
        sub = _clamp(100 - n * 25)  # 0→100, 1→75, ... 4+→0
        components["soreness"] = sub
        factors.append(_factor("肌肉酸痛", f"{n} 处", sub))

    # ── Recovery time since last session ──────────────────────────────────────
    days = _days_since(latest.get("date"), today)
    if days is not None:
        sub = _recovery_subscore(days)
        components["recovery"] = sub
        factors.append(_factor("距上次训练", f"{days} 天", sub))

    # ── Weighted average over available components ─────────────────────────────
    if components:
        total_w = sum(_WEIGHTS[k] for k in components)
        score = sum(components[k] * _WEIGHTS[k] for k in components) / total_w
    else:
        score = 70.0  # neutral default when only RPE/pain are known

    # ── Acute safety caps ─────────────────────────────────────────────────────
    consec_high = _consecutive_high_rpe(ordered)
    if consec_high >= 3:
        score = min(score, 45.0)
        factors.append(_factor("连续高强度", f"{consec_high} 次 RPE≥8", 30, negative=True))
    elif consec_high == 2:
        score = min(score, 65.0)
        factors.append(_factor("连续高强度", "2 次 RPE≥8", 55, negative=True))

    latest_pain = (latest.get("pain_feedback") or {})
    if latest_pain.get("has_pain"):
        sev = latest_pain.get("pain_severity") or 5
        cap = 55.0 if sev < 5 else (40.0 if sev < 7 else 25.0)
        score = min(score, cap)
        loc = latest_pain.get("pain_location") or "未知部位"
        factors.append(_factor("近期疼痛", f"{loc} {sev}/10", cap, negative=True))

    score = round(_clamp(score), 0)
    info = _band(score)

    return {
        "score": int(score),
        "band": info["band"],
        "label": info["label"],
        "recommendation": info["recommendation"],
        "suggested_intensity_modifier": _suggested_modifier(score),
        "factors": factors,
        "based_on_sessions": len(ordered),
    }


# =============================================================================
# Helpers
# =============================================================================

def _factor(label: str, value: str, sub_score: float, negative: bool = False) -> Dict[str, Any]:
    if negative or sub_score < 50:
        status = "bad"
    elif sub_score < 75:
        status = "ok"
    else:
        status = "good"
    return {"label": label, "value": value, "score": int(round(sub_score)), "status": status}


def _recovery_subscore(days: int) -> float:
    if days <= 0:
        return 55.0   # trained today already / back-to-back
    if days in (1, 2, 3):
        return 100.0  # optimal recovery window
    if days == 4:
        return 88.0
    if days == 5:
        return 80.0
    if days <= 7:
        return 72.0
    return 65.0       # long layoff — fresh but detraining begins


def _days_since(last_date: Optional[str], today: Optional[str]) -> Optional[int]:
    if not last_date:
        return None
    try:
        d_last = date.fromisoformat(last_date)
        d_today = date.fromisoformat(today) if today else date.today()
        return max(0, (d_today - d_last).days)
    except (ValueError, TypeError):
        return None


def _consecutive_high_rpe(sessions_desc: List[Dict[str, Any]]) -> int:
    """Count consecutive most-recent sessions with RPE ≥ 8."""
    count = 0
    for s in sessions_desc:
        rpe = s.get("rpe")
        if rpe is not None and rpe >= 8:
            count += 1
        else:
            break
    return count
