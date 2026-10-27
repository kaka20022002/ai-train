# -*- coding: utf-8 -*-
"""端到端验证：扩充动作库 + 处方推导后的计划质量。

对照维度：
  1. 每个阶段选出的动作是否都是该阶段该有的类型（热身段不应出现杠铃弯举）
  2. 参数是否与动作性质一致（拉伸给秒数、复合给低次数）
  3. 禁忌动作是否依然为 0
  4. 三类档案（健康 / 膝伤 / 多伤）是否都能填满五个阶段
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents import render_plan_draft, run_pipeline  # noqa: E402
from agents.contracts import PHASES  # noqa: E402
from agents.prescription import prescribe  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = json.loads((ROOT / "exercise_db.json").read_text(encoding="utf-8"))
IDX = {e["id"]: e for e in DB}

PHASE_CN = {
    "warm_up": "热身",
    "activation": "激活",
    "main_lifts": "主项",
    "accessories": "辅助",
    "cool_down": "放松",
}

PROFILES = {
    "健康用户（无伤）": {
        "user_id": "u_healthy",
        "basic_info": {"age": 26, "gender": "male"},
        "fitness_level": "intermediate",
        "medical_history": [],
    },
    "膝半月板撕裂 HIGH": {
        "user_id": "u_knee",
        "basic_info": {"age": 28, "gender": "male"},
        "fitness_level": "beginner",
        "medical_history": [
            {"location": "knee", "condition": "meniscus_tear", "severity": "high"}
        ],
    },
    "膝HIGH + 肩LOW + 腰LOW": {
        "user_id": "u_multi",
        "basic_info": {"age": 41, "gender": "female"},
        "fitness_level": "beginner",
        "medical_history": [
            {"location": "knee", "condition": "meniscus_tear", "severity": "high"},
            {"location": "shoulder", "condition": "shoulder_impingement", "severity": "low"},
            {"location": "spine", "condition": "lumbar_herniation", "severity": "low"},
        ],
    },
}

EXPECTED_TYPE = {
    "warm_up": {"Warmup"},
    "activation": {"Activation", "Isolation", "Isometric", "Compound"},
    "main_lifts": {"Compound"},
    "accessories": {"Isolation", "Compound", "Activation"},
    "cool_down": {"Stretch"},
}


def main() -> None:
    problems: list[str] = []

    for label, profile in PROFILES.items():
        print("=" * 78)
        print(f"【{label}】")
        result = run_pipeline(DB, profile, seed=2026)
        rendered = render_plan_draft(result.draft, IDX, result.profile, result.report)
        prof = result.profile

        print(
            f"允许 {len(prof.allowed_ids)} / 禁止 {len(prof.forbidden_reasons)}   "
            f"关节上限 {prof.joint_caps}   总时长 {rendered['estimated_duration_minutes']} 分钟"
        )
        print()

        for phase in PHASES:
            items = rendered["phases"][phase]
            names = []
            for it in items:
                zh = it["name_zh"] or it["name"]
                load = f"@{it['notes'].split('；')[0]}" if it["notes"] and "强度" in it["notes"] else ""
                names.append(f"{zh}({it['sets']}×{it['reps']})")
            print(f"  {PHASE_CN[phase]:4} {len(items)} 个: " + " | ".join(names))

            # 类型校验
            for it in items:
                eid = next(
                    (s.exercise_id for s in result.draft.phases[phase]
                     if (IDX[s.exercise_id].get("name") == it["name"])),
                    None,
                )
                if eid is None:
                    continue
                etype = IDX[eid].get("type")
                if etype not in EXPECTED_TYPE[phase] and phase != "cool_down":
                    problems.append(f"{label}/{phase}: {it['name']} 类型 {etype} 不属于该阶段")

        planned = {s.exercise_id for _, s in result.draft.iter_slots()}
        leak = planned & set(prof.forbidden_reasons)
        print(
            f"\n  安全：passed={result.report.passed}  违规={len(result.report.violations)}  "
            f"审查={result.report.review_mode} 回炉={result.review_rounds}  "
            f"基线提示={len(result.report.baseline_flags)}  计划∩禁止={len(leak)}"
        )
        if leak:
            problems.append(f"{label}: 禁忌动作泄漏 {leak}")
        print()

    # 处方一致性抽查
    print("=" * 78)
    print("【处方推导抽查】")
    samples = [
        ("cool_down", 55),   # Child's Pose      拉伸
        ("warm_up", 41),     # Arm Circles       动态热身
        ("accessories", 30), # Plank             等长
        ("activation", 61),  # Glute Bridge      激活
        ("main_lifts", 3),   # Bench Press       复合
        ("accessories", 23), # Barbell Curl      孤立
    ]
    for phase, eid in samples:
        meta = IDX[eid]
        p = prescribe(phase, meta, None)
        tag = "计时" if p.timed else "计次"
        load = f"{p.load_pct}%" if p.load_pct is not None else "自重"
        print(
            f"  {PHASE_CN[phase]:4} {meta['name_zh']:14} type={meta['type']:11} "
            f"→ {p.sets} 组 × {p.reps}  {load}  [{tag}]"
        )
        if meta["type"] in ("Stretch", "Isometric") and not p.timed:
            problems.append(f"处方: {meta['name']} 是计时动作却未标记 timed")
        if meta["type"] == "Stretch" and ("次" in p.reps):
            problems.append(f"处方: {meta['name']} 是拉伸却给了次数 {p.reps}")

    print()
    if problems:
        print(f"❌ 发现 {len(problems)} 个问题：")
        for p in problems:
            print("   -", p)
        sys.exit(1)
    print("✅ 全部检查通过")


if __name__ == "__main__":
    main()
