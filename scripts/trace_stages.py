"""逐阶段追踪：给定一份输入，打印每个 Agent 的完整产物。

用法：
    python scripts/trace_stages.py            # 当前后端（无 key → 基线降级）
    python scripts/trace_stages.py --agent    # 用假模型模拟三通道，看完整形状
    python scripts/trace_stages.py --llm      # 用 .env 里的真 key 跑，看真实产物

输出同时写到 stdout 与 trace_stages.txt。
"""

from __future__ import annotations

import io
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, ".")

from agents import (  # noqa: E402
    ExerciseCatalog,
    PlanAgent,
    SafetyEvalAgent,
    StateRiskAgent,
    build_safety_notes,
    run_pipeline,
)
from agents.contracts import PHASES  # noqa: E402

DB = json.load(open("exercise_db.json", encoding="utf-8"))

USER_PROFILE: Dict[str, Any] = {
    "user_id": "u_demo",
    "basic_info": {"age": 30, "gender": "male", "height_cm": 178, "weight_kg": 76},
    "fitness_level": "beginner",
    "fitness_goal": "strength",
    "training_frequency": 2,
    "available_equipment": ["bodyweight", "dumbbell"],
    "medical_history": [
        {
            "location": "knee",
            "condition": "meniscus_tear",
            "severity": "high",
            "notes": "蹲到底膝内侧刺痛，术后两年仍不敢全幅度深蹲",
        },
        {
            "location": "shoulder",
            "condition": "impingement",
            "severity": "low",
            "notes": "过顶推举到最后会有点夹",
        },
    ],
    "preferences": {"liked_patterns": ["hinge"], "disliked_patterns": ["jump"]},
}

FEEDBACK: Dict[str, Any] = {
    "last_rpe": 8,
    "sleep_quality": "poor",
    "pain_feedback": {"knee": 3},
    "soreness": {"hamstring": 2},
}

WORKOUT_TYPE = "lower_body"
QUERY = "今天只有三十分钟，想练下肢，别让膝盖难受"

OUT: List[str] = []


def p(line: str = "") -> None:
    OUT.append(line)


def head(title: str) -> None:
    p()
    p("═" * 74)
    p(title)
    p("═" * 74)


def dump(obj: Any, indent: int = 2, max_len: int = 100_000) -> None:
    blob = json.dumps(obj, ensure_ascii=False, indent=indent)
    if len(blob) > max_len:
        blob = blob[:max_len] + "\n  …(截断)"
    for line in blob.splitlines():
        p("  " + line)


def brief(title: str, obj: Any) -> None:
    p(f"  {title}:")
    dump(obj, indent=2)


# ══════════════════════════════════════════════════════════════════════════
# 假模型：模拟「接了 key」之后三个通道实际会返回什么
# ══════════════════════════════════════════════════════════════════════════
STATE_FAKE = {
    "overall": {
        "risk_level": "high",
        "clearance": "conditional",
        "summary": "下肢只能做无痛幅度内的髋主导动作，本次控制在 30 分钟内",
    },
    "injuries": [
        {
            "location": "knee",
            "condition": "meniscus_tear",
            "severity": "high",
            "functional_impact": "屈膝超过 90° 出现内侧刺痛，闭链屈膝耐受差，术后两年未恢复全幅度",
            "contraindications": ["深屈膝闭合链负荷", "跳跃落地缓冲", "跪姿动作"],
            "safe_substitutes": ["髋主导", "低冲击", "等长收缩"],
            "impact_cap": 2,
            "load_pct_ceiling": 55,
        },
        {
            "location": "shoulder",
            "condition": "impingement",
            "severity": "low",
            "functional_impact": "过顶推举末端有夹挤感，本次为下肢日，影响有限",
            "contraindications": ["过顶推举末端幅度"],
            "safe_substitutes": ["肩胛平面推举"],
            "impact_cap": 3,
            "load_pct_ceiling": 70,
        },
    ],
    "constraints": {
        "additional_forbidden": [],
        "avoid_patterns": ["squat", "jump"],
        "additional_joint_caps": {"knee": 2},
        "impact_ceiling_override": 3,
        "load_pct_cap_override": 55,
        "session_cap_minutes": 30,
    },
    "dose_guidance": {
        "volume": "单次不超过 12 个工作组",
        "intensity": "主项 ≤55% 1RM，留 3 次余力",
        "rest": "主项组间 90-120 秒，辅助 60 秒",
        "progression": "两周内只恢复无痛幅度，不加负荷",
    },
    "watch_items": [
        "膝内侧出现刺痛立即停止该动作",
        "组间膝部发胀则减少一组",
        "睡眠差，本次不追 RPE",
    ],
    "rationale": "notes 明确写「蹲到底膝内侧刺痛」，追加 squat 模式回避；睡眠差与高 RPE 叠加，容量下调。",
}

_PLAN_CALLS = {"n": 0}


def _pattern(row: Dict[str, Any]) -> str:
    """catalog.rows() 里字段名是 pattern，不是 motion_pattern。"""
    return str(row.get("pattern") or row.get("motion_pattern") or "")


def plan_fake(payload: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    """第一版故意越线（深蹲 + 五组），被打回后改走髋主导。"""
    _PLAN_CALLS["n"] += 1
    rows = payload["exercise_catalog"]
    blocked = {
        item["exercise_id"]
        for key in ("unavailable_exercises", "forbidden_exercises")
        for item in (payload.get("baseline") or {}).get(key) or []
    }
    usable = [r for r in rows if r["exercise_id"] not in blocked]
    by_phase = {ph: [r for r in usable if ph in r["phases"]] for ph in PHASES}
    report = payload.get("risk_report") or {}
    avoid = set((report.get("constraints") or {}).get("avoid_patterns") or [])
    if not avoid:
        avoid = {"squat", "lunge"}  # 基线模式下报告没有 constraints，按 notes 自己判

    knee_unsafe = [r for r in by_phase["main_lifts"] if _pattern(r) in avoid]
    if _PLAN_CALLS["n"] == 1 and knee_unsafe:
        # 初版：模型没读 notes，照常规选了被回避的模式
        return {
            "main_lifts": [
                {"exercise_id": knee_unsafe[0]["exercise_id"], "sets": 5,
                 "reps": "5", "load_pct": 80, "rest_seconds": 180,
                 "note": "力量主项"}
            ]
        }
    hinge = [r for r in by_phase["main_lifts"] if _pattern(r) == "hinge"]
    out: Dict[str, List[Dict[str, Any]]] = {}
    for ph in ("warm_up", "activation", "main_lifts", "accessories", "cool_down"):
        rows_ph = [r for r in by_phase[ph] if _pattern(r) not in avoid]
        if not rows_ph:
            continue
        pick = hinge[0] if ph == "main_lifts" and hinge else rows_ph[0]
        timed = bool(pick.get("timed"))
        out[ph] = [
            {
                "exercise_id": pick["exercise_id"],
                "sets": 3 if ph == "main_lifts" else 2,
                "reps": "30" if timed else ("8" if ph == "main_lifts" else "12"),
                "load_pct": 50 if ph == "main_lifts" else None,
                "rest_seconds": 90 if ph == "main_lifts" else 45,
                "note": "幅度到无痛范围" if ph == "main_lifts" else "控制节奏",
            }
        ]
    return out


def safety_fake(payload: Dict[str, Any]) -> Dict[str, Any]:
    """照基线命中项裁决：有禁忌动作就 fail 并回灌。"""
    bad = [f for f in payload["baseline_flags"] if f["code"] == "FORBIDDEN_ID"]
    if bad:
        return {
            "verdict": "fail",
            "violations": [
                {
                    "code": "CONTRAINDICATION",
                    "exercise_id": bad[0]["exercise_id"],
                    "phase": bad[0]["phase"],
                    "reason": "病历写「蹲到底膝内侧刺痛」，该动作要求全幅度深屈膝",
                }
            ],
            "rationale": "主项动作与膝伤禁忌直接冲突，打回重写",
        }
    breach = [f for f in payload["baseline_flags"] if f["code"] == "REPORT_BREACH"]
    if breach:
        return {
            "verdict": "fail",
            "violations": [
                {
                    "code": "REPORT_BREACH",
                    "exercise_id": breach[0]["exercise_id"],
                    "phase": breach[0]["phase"],
                    "reason": "动作模式落在风险报告的 avoid_patterns 里",
                }
            ],
            "rationale": "违反阶段一报告明确列出的回避模式",
        }
    return {"verdict": "pass", "violations": [], "rationale": "未发现违规，剂量符合报告口径"}


# ══════════════════════════════════════════════════════════════════════════
def _real_bridges():
    """按 .env 配置装配三个 Agent 的真实 LLM 后端；配置不全时返回 None。"""

    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
    except ImportError:
        pass

    if os.getenv("USE_REAL_LLM", "false").strip().lower() not in ("1", "true", "yes"):
        print("  ❌ USE_REAL_LLM 不是 true，--llm 模式需要先在 .env 里打开它")
        return None
    if not os.getenv("OPENAI_API_KEY", "").strip():
        print("  ❌ OPENAI_API_KEY 为空，--llm 模式需要先填 key")
        return None

    from llm_client import LLMClient

    from agents.llm_bridge import build_bridges

    return build_bridges(LLMClient())


def main() -> None:
    use_dummy = "--agent" in sys.argv
    use_llm = "--llm" in sys.argv

    bridges = None
    if use_llm:
        bridges = _real_bridges()
        if bridges is None:
            raise SystemExit(2)

    use_agent = use_dummy or bridges is not None

    head("阶段 0｜输入")
    p("  POST /generate_plan")
    p("  ── user_profile（身体状况）──")
    dump(USER_PROFILE)
    p("  ── feedback（上次训练反馈）──")
    dump(FEEDBACK)
    p("  ── 本次需求 ──")
    p(f'  workout_type = "{WORKOUT_TYPE}"')
    p(f'  query        = "{QUERY}"')

    # ── 阶段一 ──────────────────────────────────────────────────────────
    if bridges is not None:
        state_agent = StateRiskAgent(DB, llm_enhance_fn=bridges.state_fn)
    elif use_dummy:
        state_agent = StateRiskAgent(DB, llm_enhance_fn=lambda payload: STATE_FAKE)
    else:
        state_agent = StateRiskAgent(DB)
    profile = state_agent.analyze(
        USER_PROFILE, FEEDBACK, workout_type=WORKOUT_TYPE, query=QUERY
    )

    head("阶段 1｜state_risk —— 身体情况 → 风险报告")
    p("  ① 发给模型的请求（节选）")
    brief(
        "in",
        {
            "basic_info": USER_PROFILE["basic_info"],
            "fitness_level": USER_PROFILE["fitness_level"],
            "medical_history": USER_PROFILE["medical_history"],
            "recent_feedback": FEEDBACK,
            "current_request": {"workout_type": WORKOUT_TYPE, "query": QUERY},
            "baseline_constraints": {
                "joint_caps": profile.joint_caps,
                "impact_ceiling": profile.impact_ceiling,
                "load_pct_cap": profile.load_pct_cap,
                "forbidden_count": len(profile.forbidden_reasons),
            },
        },
    )
    p("  ② 产物：risk_report（报告主体，给人看也给下游看）")
    dump(profile.risk_report)
    p("  ③ 产物：约束投影（同一判断的机器可执行形态）")
    brief(
        "constraints",
        {
            "allowed_ids_count": len(profile.allowed_ids),
            "forbidden_reasons": {
                str(k): v for k, v in sorted(profile.forbidden_reasons.items())
            },
            "joint_caps": profile.joint_caps,
            "impact_ceiling": profile.impact_ceiling,
            "load_pct_cap": profile.load_pct_cap,
            "avoid_patterns": list(profile.avoid_patterns),
            "session_cap_minutes": profile.session_cap_minutes,
            "risk_level": profile.risk_level,
            "clearance": profile.clearance,
            "profile_hash": profile.profile_hash,
        },
    )
    p("  ④ 通道状态")
    brief(
        "llm",
        {
            "llm_status": profile.llm_status,
            "llm_prompt_version": profile.llm_prompt_version,
            "llm_forbidden": list(profile.llm_forbidden),
            "llm_rationale": profile.llm_rationale,
        },
    )

    # ── 阶段二 ──────────────────────────────────────────────────────────
    catalog = ExerciseCatalog(DB)
    probe_plan = PlanAgent()  # 只为拿到 payload 形状
    plan_payload = probe_plan.build_request_payload(profile, catalog, WORKOUT_TYPE)

    head("阶段 2｜plan_gen —— 风险报告 + 需求 → 计划")
    p("  ① 发给模型的请求（结构摘要）")
    brief(
        "in",
        {
            "workout_type": plan_payload.get("workout_type"),
            "fitness_level": plan_payload.get("fitness_level"),
            "session_cap_minutes": plan_payload.get("session_cap_minutes"),
            "user_request": plan_payload.get("user_request"),
            "preferences": plan_payload.get("preferences"),
            "available_equipment": plan_payload.get("available_equipment"),
            "exercise_catalog_rows": len(plan_payload.get("exercise_catalog") or []),
            "reference_doses": len(plan_payload.get("reference_doses") or {}),
            "risk_report_keys": sorted((plan_payload.get("risk_report") or {}).keys()),
            "baseline.forbidden_exercises": len(
                (plan_payload.get("baseline") or {}).get("forbidden_exercises") or []
            ),
            "baseline.unavailable_exercises": len(
                (plan_payload.get("baseline") or {}).get("unavailable_exercises") or []
            ),
            "payload_bytes": len(
                json.dumps(plan_payload, ensure_ascii=False, separators=(",", ":"))
            ),
        },
    )
    p("  ② risk_report 原样透传给生成端（首要依据）")
    dump(plan_payload.get("risk_report"))
    p("  ③ 候选目录里的前 3 行（全库视图，无裁剪）")
    dump((plan_payload.get("exercise_catalog") or [])[:3])

    # ── 阶段三 ──────────────────────────────────────────────────────────
    if bridges is not None:
        plan_agent = PlanAgent(llm_plan_fn=bridges.plan_fn)
        safety_agent = SafetyEvalAgent(llm_judge_fn=bridges.safety_fn)
    elif use_dummy:
        plan_agent = PlanAgent(llm_plan_fn=plan_fake)
        safety_agent = SafetyEvalAgent(llm_judge_fn=safety_fake)
    else:
        plan_agent = PlanAgent()
        safety_agent = SafetyEvalAgent()

    draft = plan_agent.generate(profile, catalog, WORKOUT_TYPE)
    head("阶段 2｜产物：PlanDraft")
    brief(
        "draft",
        {
            "plan_id": draft.plan_id,
            "generator": draft.generator,
            "prompt_version": draft.prompt_version,
            "grammar_version": draft.grammar_version,
            "rejected_ids": list(draft.rejected_ids),
            "adjusted_slots": draft.adjusted_slots,
            "slot_count": draft.slot_count(),
        },
    )
    for ph in PHASES:
        slots = draft.phases.get(ph, [])
        p(f"  {ph}（{len(slots)} 个）:")
        for s in slots:
            name = next(
                (r["name"] for r in catalog.rows() if r["exercise_id"] == s.exercise_id),
                "?",
            )
            p(
                f"    #{s.exercise_id:<3} {name:<28} "
                f"{s.sets}×{s.reps:<6} load={s.load_pct} "
                f"impact={s.impact} rest={s.rest_seconds} | {s.note}"
            )

    judge_payload = safety_agent.build_judge_payload(draft, profile, catalog)
    head("阶段 3｜safety_eval —— 计划 + 报告 → 裁决")
    p("  ① 发给模型的请求（结构摘要）")
    plan_block = judge_payload.get("plan") or {}
    user_block = judge_payload.get("user_profile") or {}
    brief(
        "in",
        {
            "plan.workout_type": plan_block.get("workout_type"),
            "plan.generator": plan_block.get("generator"),
            "plan_slots": sum(len(v) for v in (plan_block.get("phases") or {}).values()),
            "user_profile.fitness_level": user_block.get("fitness_level"),
            "user_profile.medical_history": len(
                user_block.get("medical_history") or []
            ),
            "user_profile.current_request": user_block.get("current_request"),
            "session_cap_minutes": judge_payload.get("session_cap_minutes"),
            "risk_report_keys": sorted((judge_payload.get("risk_report") or {}).keys()),
            "baseline_flags": len(judge_payload.get("baseline_flags") or []),
        },
    )
    p("  ② 基线命中项（证据，不是判决）")
    dump(judge_payload.get("baseline_flags") or [])

    report = safety_agent.evaluate(draft, profile, catalog, )

    # 会审回路（仅 agent 模式会真的迭代）
    head("阶段 3｜产物：SafetyReport")
    brief(
        "report",
        {
            "passed": report.passed,
            "review_mode": report.review_mode,
            "llm_verdict": report.llm_verdict,
            "llm_disagreed": report.llm_disagreed,
            "llm_rationale": report.llm_rationale,
            "llm_prompt_version": report.llm_prompt_version,
            "checked_slots": report.checked_slots,
            "violations": [v.to_dict() for v in report.violations],
            "baseline_flags": [v.to_dict() for v in report.baseline_flags],
        },
    )

    # ── 完整链路（含会审回路）─────────────────────────────────────────────
    _PLAN_CALLS["n"] = 0
    result = run_pipeline(
        DB,
        USER_PROFILE,
        FEEDBACK,
        workout_type=WORKOUT_TYPE,
        query=QUERY,
        state_agent=(
            None
            if not use_agent
            else StateRiskAgent(
                DB,
                llm_enhance_fn=(
                    bridges.state_fn
                    if bridges is not None
                    else (lambda payload: STATE_FAKE)
                ),
            )
        ),
        plan_agent=plan_agent if use_agent else None,
        safety_agent=safety_agent if use_agent else None,
    )

    head("完整链路结果（含会审回路）")
    p(f"  review_rounds   = {result.review_rounds}")
    p(f"  reviewed_by_agent = {result.reviewed_by_agent}")
    p(f"  generator       = {result.draft.generator}")
    p(f"  passed          = {result.report.passed}")
    p(f"  review_mode     = {result.report.review_mode}")
    p(f"  llm_verdict     = {result.report.llm_verdict}")
    final_ids = result.draft.all_ids()
    p(f"  最终动作 {len(final_ids)} 个: {final_ids}")

    head("审计链（每阶段的输入摘要与输出骨架）")
    for entry in result.audit.to_dict()["entries"]:
        p(f"  · {entry['stage']}")
        p(f"      in  = {json.dumps(entry['in'], ensure_ascii=False)}")
        p(f"      out = {json.dumps(entry['out'], ensure_ascii=False)[:400]}")

    head("对外响应里的 safety_notes（用户看到的话）")
    for note in build_safety_notes(result.profile, result.report, result.draft):
        p(f"  {note}")

    text = "\n".join(OUT)
    print(text)
    mode = "llm" if bridges is not None else ("agent" if use_dummy else "baseline")
    out_name = f"trace_stages_{mode}.txt"
    with io.open(out_name, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text + "\n")
    print(f"\n（已写入 {out_name}）")


if __name__ == "__main__":
    main()
