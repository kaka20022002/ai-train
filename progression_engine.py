"""
Progressive Overload Engine — Sprint 4 (#3)
===========================================

Turns per-exercise performance logs (the ``exercise_performance`` field of
completed training sessions) into actionable next-session prescriptions.

Core ideas
----------
1. **1RM estimation** — Epley formula ``1RM = w · (1 + reps/30)`` gives a
   load-agnostic strength proxy so we can compare sessions with different
   weight×reps combinations.
2. **Per-exercise history** — aggregate every logged set of an exercise into a
   chronological time series (estimated 1RM, top-set, total volume).
3. **Double progression** — the recommendation rule:
     · every working set reached the top of the goal rep range  → add load
     · otherwise                                                → keep load,
       push reps toward the top of the range.

The engine is pure-Python and data-source agnostic: callers pass plain session
dicts (see ``crud.session_to_feedback_dict``), so it is trivially unit-testable.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional

# Goal → working rep range used for the double-progression rule.
_GOAL_REP_RANGE: Dict[str, tuple] = {
    "strength": (3, 6),
    "hypertrophy": (8, 12),
    "general_fitness": (8, 15),
}
_DEFAULT_RANGE = (8, 12)

# Big lower-body / posterior-chain lifts tolerate larger load jumps.
_LARGE_JUMP_MUSCLES = {
    "Quadriceps", "Hamstrings", "Gluteus Maximus", "Erector Spinae",
}


# =============================================================================
# 1RM estimation
# =============================================================================

def estimate_1rm(weight_kg: Optional[float], reps: Optional[int]) -> Optional[float]:
    """
    Estimate a one-rep max from a weight×reps set using the Epley formula.

    Returns None when inputs are missing or non-positive. Reps above 12 become
    increasingly inaccurate, so we cap the multiplier's effective reps at 12.
    """
    if not weight_kg or not reps or weight_kg <= 0 or reps <= 0:
        return None
    if reps == 1:
        return round(float(weight_kg), 1)
    eff_reps = min(reps, 12)
    return round(weight_kg * (1 + eff_reps / 30.0), 1)


def _round_to_plate(kg: float, step: float = 2.5) -> float:
    """Round a target load to the nearest achievable plate increment."""
    return round(round(kg / step) * step, 1)


# =============================================================================
# Per-exercise history
# =============================================================================

def build_exercise_history(sessions: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Aggregate ``exercise_performance`` across sessions into per-exercise series.

    Each output entry is one session's record of one exercise:
        {date, weight_kg, sets_completed, reps_per_set,
         top_set_reps, est_1rm, volume_kg}

    Entries are sorted chronologically (oldest → newest).
    """
    history: Dict[str, List[Dict[str, Any]]] = {}

    # Sort sessions oldest → newest so each exercise series is chronological.
    ordered = sorted(sessions, key=lambda s: s.get("date") or "", reverse=False)

    for s in ordered:
        date = s.get("date")
        for p in (s.get("exercise_performance") or []):
            name = (p.get("name") or "").strip()
            if not name:
                continue
            weight = p.get("weight_kg")
            reps_per_set = [r for r in (p.get("reps_per_set") or []) if r is not None]
            sets_completed = p.get("sets_completed") or (len(reps_per_set) or None)

            top_reps = max(reps_per_set) if reps_per_set else None
            # Best estimated 1RM across all logged sets of this exercise.
            est = None
            if weight and reps_per_set:
                est = max(
                    (estimate_1rm(weight, r) or 0) for r in reps_per_set
                ) or None
            volume = None
            if weight and reps_per_set:
                volume = round(weight * sum(reps_per_set), 1)

            history.setdefault(name, []).append({
                "date": date,
                "weight_kg": weight,
                "sets_completed": sets_completed,
                "reps_per_set": reps_per_set,
                "top_set_reps": top_reps,
                "est_1rm": est,
                "volume_kg": volume,
            })

    return history


# =============================================================================
# Suggestion logic
# =============================================================================

def _muscle_for(name: str, exercise_db: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    if not exercise_db:
        return None
    for ex in exercise_db:
        if ex.get("name") == name:
            return ex.get("target_muscle")
    return None


def _increment_for(name: str, exercise_db: Optional[List[Dict[str, Any]]]) -> float:
    muscle = _muscle_for(name, exercise_db)
    return 5.0 if muscle in _LARGE_JUMP_MUSCLES else 2.5


def suggest_next_set(
    entries: List[Dict[str, Any]],
    goal: str = "general_fitness",
    increment_kg: float = 2.5,
) -> Dict[str, Any]:
    """
    Produce a next-session prescription for a single exercise from its history.

    Returns a dict:
        {
          suggested_weight_kg, suggested_reps, action, rationale,
          last_weight_kg, last_reps, est_1rm, trend
        }
    where *action* ∈ {"increase_load", "increase_reps", "hold", "deload", "start"}.
    """
    min_reps, max_reps = _GOAL_REP_RANGE.get(goal, _DEFAULT_RANGE)

    if not entries:
        return {
            "suggested_weight_kg": None,
            "suggested_reps": f"{min_reps}-{max_reps}",
            "action": "start",
            "rationale": "暂无历史记录，先以可控重量建立基线（动作标准为先）。",
            "last_weight_kg": None,
            "last_reps": None,
            "est_1rm": None,
            "trend": "unknown",
        }

    last = entries[-1]
    weight = last.get("weight_kg")
    reps_per_set = last.get("reps_per_set") or []
    est_1rm = last.get("est_1rm")

    # ── 1RM trend across the series ───────────────────────────────────────────
    est_series = [e["est_1rm"] for e in entries if e.get("est_1rm")]
    trend = "unknown"
    if len(est_series) >= 2:
        delta = est_series[-1] - est_series[0]
        if delta > 1.0:
            trend = "increasing"
        elif delta < -1.0:
            trend = "decreasing"
        else:
            trend = "stable"

    # ── Bodyweight / no-load exercise → progress via reps ─────────────────────
    if not weight:
        target = max_reps if not reps_per_set else min(max(reps_per_set) + 2, max_reps + 5)
        return {
            "suggested_weight_kg": None,
            "suggested_reps": str(target),
            "action": "increase_reps",
            "rationale": f"自重动作：目标每组提升至 {target} 次（必要时增加难度变式）。",
            "last_weight_kg": None,
            "last_reps": reps_per_set,
            "est_1rm": est_1rm,
            "trend": trend,
        }

    # ── Double progression on loaded exercise ─────────────────────────────────
    all_sets_at_top = bool(reps_per_set) and all(r >= max_reps for r in reps_per_set)
    any_set_below = bool(reps_per_set) and any(r < max_reps for r in reps_per_set)

    if all_sets_at_top:
        new_weight = _round_to_plate(weight + increment_kg)
        return {
            "suggested_weight_kg": new_weight,
            "suggested_reps": str(min_reps),
            "action": "increase_load",
            "rationale": (
                f"上次各组均达 {max_reps} 次上限 → 加重至 {new_weight} kg，"
                f"从 {min_reps} 次重新爬坡（双重渐进）。"
            ),
            "last_weight_kg": weight,
            "last_reps": reps_per_set,
            "est_1rm": est_1rm,
            "trend": trend,
        }

    if trend == "decreasing":
        return {
            "suggested_weight_kg": _round_to_plate(weight),
            "suggested_reps": f"{min_reps}-{max_reps}",
            "action": "deload",
            "rationale": (
                f"估算 1RM 近期下降，维持 {weight} kg 巩固动作质量，"
                "确认恢复后再加重。"
            ),
            "last_weight_kg": weight,
            "last_reps": reps_per_set,
            "est_1rm": est_1rm,
            "trend": trend,
        }

    # Default: keep load, chase reps toward the top of the range.
    return {
        "suggested_weight_kg": _round_to_plate(weight),
        "suggested_reps": f"{max_reps}",
        "action": "increase_reps",
        "rationale": (
            f"保持 {weight} kg，目标每组逼近 {max_reps} 次；"
            "全部达标后下次再加重。"
        ),
        "last_weight_kg": weight,
        "last_reps": reps_per_set,
        "est_1rm": est_1rm,
        "trend": trend,
    }


def analyze_progression(
    sessions: List[Dict[str, Any]],
    goal: str = "general_fitness",
    exercise_db: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Build progression reports for every exercise with logged performance data.

    Returns a list (sorted by most recently trained) of:
        {
          exercise_name, sessions_tracked, current_weight_kg, best_est_1rm,
          est_1rm_change_kg, trend, history (compact), suggestion
        }
    """
    history = build_exercise_history(sessions)
    reports: List[Dict[str, Any]] = []

    for name, entries in history.items():
        if not entries:
            continue
        increment = _increment_for(name, exercise_db)
        suggestion = suggest_next_set(entries, goal=goal, increment_kg=increment)

        est_series = [e["est_1rm"] for e in entries if e.get("est_1rm")]
        best_1rm = max(est_series) if est_series else None
        change = (
            round(est_series[-1] - est_series[0], 1)
            if len(est_series) >= 2 else None
        )

        reports.append({
            "exercise_name": name,
            "sessions_tracked": len(entries),
            "current_weight_kg": entries[-1].get("weight_kg"),
            "best_est_1rm": best_1rm,
            "est_1rm_change_kg": change,
            "trend": suggestion["trend"],
            "last_date": entries[-1].get("date"),
            "history": [
                {
                    "date": e["date"],
                    "weight_kg": e["weight_kg"],
                    "reps_per_set": e["reps_per_set"],
                    "est_1rm": e["est_1rm"],
                }
                for e in entries[-6:]  # last 6 sessions for a compact sparkline
            ],
            "suggestion": suggestion,
        })

    # Most recently trained exercises first.
    reports.sort(key=lambda r: r.get("last_date") or "", reverse=True)
    return reports
