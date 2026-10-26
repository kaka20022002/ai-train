# -*- coding: utf-8 -*-
"""通过真实 HTTP 请求验证计划生成质量（v2）。

不直接调函数，而是打接口 —— 这样能同时验证响应模型、字段序列化、
以及 /generate_plan 内部真的走了三 Agent 管线。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8127"

KNEE = {
    "user_profile": {
        "user_id": "u_http_v2_knee",
        "basic_info": {"age": 28, "gender": "male"},
        "fitness_level": "beginner",
        "medical_history": [
            {"location": "knee", "condition": "meniscus_tear", "severity": "high"},
            {"location": "shoulder", "condition": "shoulder_impingement", "severity": "low"},
        ],
    },
    "workout_type": "full_body",
}

PHASE_CN = {
    "warm_up": "热身",
    "activation": "激活",
    "main_lifts": "主项",
    "accessories": "辅助",
    "cool_down": "放松",
}


def post(path: str, payload: dict, timeout: int = 90):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read())


def get(path: str, timeout: int = 30):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.status, json.loads(r.read())


def main() -> None:
    problems: list[str] = []

    st, health = get("/health")
    print(f"[health] {st}  动作库 {health['exercise_count']} 条")
    if health["exercise_count"] < 70:
        problems.append(f"动作库仍是 {health['exercise_count']} 条，服务可能没重启")

    st, data = post("/generate_plan", KNEE)
    print(f"[generate_plan] {st}  generator={data['generator_version']}")
    print(f"  时长 {data['estimated_duration_minutes']} 分钟\n")

    for phase, cn in PHASE_CN.items():
        items = data["phases"][phase]
        print(f"  {cn} {len(items)} 个:")
        for it in items:
            zh = it.get("name_zh") or it["name"]
            print(
                f"    - {zh:16} {it['sets']} 组 × {it['reps']:12} "
                f"休息 {it['rest_seconds']:3}s  {it['target_muscle']}"
            )
            if not it.get("name_zh"):
                problems.append(f"{phase}: {it['name']} 缺 name_zh")

    print()
    s = data.get("safety") or {}
    print(
        f"  安全: passed={s.get('passed')} 检查={s.get('checked_slots')} "
        f"屏蔽={s.get('masked_count')} 探针={s.get('adversarial_blocked')}/{s.get('adversarial_probes')}"
    )
    print(f"  审计: {[e['stage'] for e in (data.get('audit') or [])]}")
    for note in data["safety_notes"]:
        print("    " + note)

    # 关键断言
    forbidden = {ex["name"] for ex in data["risk_analysis"]["forbidden_exercises"]}
    planned = {it["name"] for slots in data["phases"].values() for it in slots}
    if forbidden & planned:
        problems.append(f"计划里出现禁忌动作: {forbidden & planned}")

    # 处方合理性：拉伸必须是秒，力量必须是次数
    for it in data["phases"]["cool_down"]:
        if "秒" not in it["reps"]:
            problems.append(f"放松段 {it['name']} 未按时间计: {it['reps']}")
    for it in data["phases"]["main_lifts"]:
        if "秒" in it["reps"]:
            problems.append(f"主项段 {it['name']} 按时间计，不合理: {it['reps']}")

    print()
    if problems:
        print(f"失败 {len(problems)} 项:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("全部通过")


if __name__ == "__main__":
    main()
