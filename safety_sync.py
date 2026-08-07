"""
Safety sync — propagate injury-based forbidden exercises across the app.

- Coach context: full forbidden list for LLM hard constraints
- Program / plan revalidation when medical_history changes
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import crud
from exercise_meta import sanitize_exercise_name
from risk_engine import ForbiddenExercise, RiskAssessmentEngine
from sqlalchemy.orm import Session


@dataclass
class RevalidateReport:
    programs_scanned: int = 0
    programs_updated: int = 0
    plans_scanned: int = 0
    plans_updated: int = 0
    exercises_replaced: int = 0
    replacements: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "programs_scanned": self.programs_scanned,
            "programs_updated": self.programs_updated,
            "plans_scanned": self.plans_scanned,
            "plans_updated": self.plans_updated,
            "exercises_replaced": self.exercises_replaced,
            "replacements": self.replacements[:20],
        }


_engine: Optional[RiskAssessmentEngine] = None


def _get_engine() -> RiskAssessmentEngine:
    global _engine
    if _engine is None:
        _engine = RiskAssessmentEngine()
    return _engine


def get_risk_snapshot(user_profile: Dict[str, Any]) -> Tuple[List[ForbiddenExercise], List[str]]:
    return _get_engine().analyze_static_risk(user_profile)


def format_forbidden_context_for_coach(
    forbidden: List[ForbiddenExercise],
    safe_count: int,
) -> str:
    lines = [
        "🚫 禁止动作清单（硬约束 — 不得推荐、安排或替代为以下动作）：",
    ]
    if not forbidden:
        lines.append("  · 当前伤病史下无绝对禁止动作")
    else:
        for ex in forbidden[:40]:
            sub = ex.substitution or "休息或咨询康复师"
            joints = "、".join(ex.involved_joints) if ex.involved_joints else "—"
            lines.append(f"  · {ex.name}（风险 {ex.risk_level}/5，关节：{joints}）")
            lines.append(f"    原因：{ex.reason}")
            lines.append(f"    可推荐替代：{sub}")
    lines.append(f"  · 安全动作池共 {safe_count} 个（仅从此池或等效低风险动作中选择）")
    return "\n".join(lines)


def _forbidden_map(forbidden: List[ForbiddenExercise]) -> Dict[str, ForbiddenExercise]:
    return {ex.name.lower(): ex for ex in forbidden}


def _safe_lookup(safe: List[str]) -> Dict[str, str]:
    return {name.lower(): name for name in safe}


def _match_name_in_text(text: str, candidates: List[str]) -> Optional[str]:
    if not text:
        return None
    lower = text.lower()
    for name in sorted(candidates, key=len, reverse=True):
        if name.lower() in lower:
            return name
    return None


def resolve_safe_exercise_name(
    name: str,
    forbidden: List[ForbiddenExercise],
    safe: List[str],
) -> Tuple[str, bool]:
    """Return (resolved_name, was_replaced)."""
    if not name:
        return sanitize_exercise_name("", safe), False

    fb_map = _forbidden_map(forbidden)
    safe_by_lower = _safe_lookup(safe)
    forbidden_lower = set(fb_map.keys())

    if name.lower() not in forbidden_lower:
        if name.lower() in safe_by_lower:
            return safe_by_lower[name.lower()], False
        resolved = sanitize_exercise_name(name, safe)
        return resolved, resolved.lower() != name.lower()

    record = fb_map[name.lower()]
    substitution = (record.substitution or "").strip()

    for candidate in (safe + list(safe_by_lower.values())):
        matched = _match_name_in_text(substitution, [candidate])
        if matched and matched.lower() in safe_by_lower and matched.lower() not in forbidden_lower:
            return safe_by_lower[matched.lower()], True

    matched_any = _match_name_in_text(substitution, safe)
    if matched_any and matched_any.lower() in safe_by_lower:
        return safe_by_lower[matched_any.lower()], True

    for candidate in safe:
        if candidate.lower() not in forbidden_lower:
            return candidate, True

    return sanitize_exercise_name("", safe), True


def _replace_in_exercise_list(
    exercises: List[Dict[str, Any]],
    forbidden: List[ForbiddenExercise],
    safe: List[str],
    report: RevalidateReport,
    context: str,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ex in exercises:
        if not isinstance(ex, dict):
            out.append(ex)
            continue
        item = dict(ex)
        old_name = item.get("name", "")
        new_name, replaced = resolve_safe_exercise_name(old_name, forbidden, safe)
        item["name"] = new_name
        if replaced and old_name:
            report.exercises_replaced += 1
            report.replacements.append({
                "context": context,
                "from": old_name,
                "to": new_name,
            })
        out.append(item)
    return out


def revalidate_program_data(
    program_data: Dict[str, Any],
    forbidden: List[ForbiddenExercise],
    safe: List[str],
    report: RevalidateReport,
    program_id: str,
) -> Dict[str, Any]:
    data = copy.deepcopy(program_data)
    changed = False

    for week in data.get("weeks") or []:
        week_no = week.get("week_number", "?")
        for session in week.get("sessions") or []:
            sess_no = session.get("session_number", "?")
            ctx = f"program:{program_id} W{week_no} S{sess_no}"
            before = [ex.get("name") for ex in session.get("key_exercises") or [] if isinstance(ex, dict)]
            session["key_exercises"] = _replace_in_exercise_list(
                session.get("key_exercises") or [], forbidden, safe, report, ctx,
            )
            after = [ex.get("name") for ex in session.get("key_exercises") or [] if isinstance(ex, dict)]
            if before != after:
                changed = True

    if changed:
        data["forbidden_exercise_count"] = len(forbidden)
        data["safe_exercise_count"] = len(safe)
        data["safety_revalidated_at"] = datetime.now(timezone.utc).isoformat()

    return data, changed


def revalidate_plan_data(
    plan_data: Dict[str, Any],
    forbidden: List[ForbiddenExercise],
    safe: List[str],
    report: RevalidateReport,
    plan_id: str,
) -> Tuple[Dict[str, Any], bool]:
    data = copy.deepcopy(plan_data)
    changed = False
    phases = data.get("phases")
    if not isinstance(phases, dict):
        return data, False

    new_phases: Dict[str, Any] = {}
    for phase_key, exercises in phases.items():
        if not isinstance(exercises, list):
            new_phases[phase_key] = exercises
            continue
        ctx = f"plan:{plan_id}:{phase_key}"
        before = [ex.get("name") for ex in exercises if isinstance(ex, dict)]
        new_phases[phase_key] = _replace_in_exercise_list(exercises, forbidden, safe, report, ctx)
        after = [ex.get("name") for ex in new_phases[phase_key] if isinstance(ex, dict)]
        if before != after:
            changed = True

    if changed:
        data["phases"] = new_phases
        ra = data.get("risk_analysis")
        if isinstance(ra, dict):
            ra["forbidden_exercises"] = [
                {
                    "name": ex.name,
                    "reason": ex.reason,
                    "involved_joints": ex.involved_joints,
                    "risk_level": ex.risk_level,
                    "substitution": ex.substitution,
                }
                for ex in forbidden
            ]
            ra["safe_exercise_count"] = len(safe)
            data["risk_analysis"] = ra

    return data, changed


def revalidate_user_training_data(
    db: Session,
    user_id: str,
    user_profile: Dict[str, Any],
    *,
    plan_limit: int = 15,
) -> RevalidateReport:
    """Re-scan active/paused programs and recent plans after injury profile changes."""
    report = RevalidateReport()
    forbidden, safe = get_risk_snapshot(user_profile)

    for status in ("active", "paused"):
        programs = crud.get_user_programs(db, user_id, status=status, limit=50)
        for record in programs:
            report.programs_scanned += 1
            data = dict(record.program_data or {})
            new_data, changed = revalidate_program_data(
                data, forbidden, safe, report, record.program_id,
            )
            if changed:
                crud.update_program(db, record.program_id, new_data)
                report.programs_updated += 1

    plans = crud.get_user_plans(db, user_id, limit=plan_limit)
    for record in plans:
        report.plans_scanned += 1
        data = dict(record.plan_data or {})
        new_data, changed = revalidate_plan_data(
            data, forbidden, safe, report, record.plan_id,
        )
        if changed:
            crud.update_generated_plan(db, record.plan_id, new_data)
            report.plans_updated += 1

    return report
