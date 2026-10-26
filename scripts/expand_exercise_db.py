# -*- coding: utf-8 -*-
"""动作库扩充脚本（一次性执行，产物写回 exercise_db.json）。

背景
----
原动作库 40 条**全部是力量动作**（22 Compound + 17 Isolation + 1 Isometric），
没有任何热身、拉伸、活动度动作，也没有「阶段」维度。这导致计划生成器在
warm_up / cool_down 阶段只能在力量动作里挑选，产出「腿弯举当热身、提踵当放松」
这类明显不合理的处方。

即使接入大模型也无法解决 —— 模型只能从候选集中挑选，而候选集中不存在
合适的动作。所以这是**数据层的缺口**，必须先补数据。

本次扩充分两步：
1. 给现有 40 条补 ``name_zh`` / ``phase`` / ``motion_pattern`` / ``is_timed``
2. 新增 30 条：10 条动态热身、10 条静态拉伸、10 条激活稳定

``phase`` 字段是本次改造的核心：它让 grammar 的候选过滤从「按动作类型排序」
升级为「按阶段硬过滤」，使每个阶段只能选到该阶段该有的动作。

用法::

    python scripts/expand_exercise_db.py            # 执行扩充
    python scripts/expand_exercise_db.py --dry-run  # 只看将要写入什么
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "exercise_db.json"
FRONTEND_LABELS = ROOT / "frontend" / "lib" / "exercise-labels.ts"
BACKUP_PATH = ROOT / "exercise_db.backup.json"

# ── 现有 40 条的阶段归属与动作模式 ──────────────────────────────────────────
# id: (phase 列表, motion_pattern, 是否计时动作)
EXISTING_META: Dict[int, Tuple[List[str], str, bool]] = {
    1:  (["main_lifts"], "squat", False),
    2:  (["main_lifts"], "hinge", False),
    3:  (["main_lifts"], "push_h", False),
    4:  (["main_lifts"], "push_v", False),
    5:  (["main_lifts"], "pull_v", False),
    6:  (["main_lifts"], "pull_h", False),
    7:  (["main_lifts", "accessories"], "lunge", False),
    8:  (["accessories"], "knee_extension", False),
    9:  (["accessories", "activation"], "knee_flexion", False),
    10: (["main_lifts"], "squat", False),
    11: (["main_lifts", "accessories"], "hinge", False),
    12: (["main_lifts", "activation"], "hinge", False),
    13: (["accessories"], "calf", False),
    14: (["main_lifts"], "push_h", False),
    15: (["accessories"], "push_h", False),
    16: (["accessories"], "push_h", False),
    17: (["main_lifts"], "pull_v", False),
    18: (["main_lifts"], "pull_h", False),
    19: (["main_lifts"], "pull_h", False),
    20: (["accessories", "activation"], "pull_h", False),
    21: (["accessories"], "abduction", False),
    22: (["main_lifts"], "push_v", False),
    23: (["accessories"], "elbow_flexion", False),
    24: (["accessories"], "elbow_flexion", False),
    25: (["accessories"], "elbow_flexion", False),
    26: (["main_lifts", "accessories"], "push_h", False),
    27: (["accessories"], "elbow_extension", False),
    28: (["accessories"], "elbow_extension", False),
    29: (["accessories"], "wrist", False),
    30: (["accessories", "activation"], "core", True),
    31: (["accessories"], "core", False),
    32: (["accessories"], "core", False),
    33: (["accessories"], "core", False),
    34: (["accessories"], "hinge", False),
    35: (["accessories"], "hinge", False),
    36: (["main_lifts"], "squat", False),
    37: (["main_lifts"], "lunge", False),
    38: (["main_lifts"], "hinge", False),
    39: (["main_lifts", "accessories", "activation"], "push_h", False),
    40: (["accessories"], "shrug", False),
}

# 前端映射表里没有、或想统一口径的中文名
NAME_ZH_OVERRIDE: Dict[str, str] = {
    "Back Extension": "山羊挺身",
    "Hip Thrust": "臀推",
    "Walking Lunge": "行走弓步",
    "Wrist Curl": "腕弯举",
    "Crunch": "卷腹",
    "Hanging Leg Raise": "悬垂举腿",
    "Tricep Pushdown": "三头下压",
    "Overhead Press": "站姿推举",
}


def _ex(name: str, name_zh: str, etype: str, phases: List[str], pattern: str,
        muscle: str, joints: List[str], risk: int, timed: bool,
        equipment: List[str], substitution: str,
        alt: Dict[str, str] | None = None,
        contra: List[str] | None = None) -> Dict[str, Any]:
    """构造一条动作记录，保证字段齐整。"""
    return {
        "name": name,
        "name_zh": name_zh,
        "type": etype,
        "phase": phases,
        "motion_pattern": pattern,
        "is_timed": timed,
        "target_muscle": muscle,
        "involved_joints": joints,
        "risk_level": risk,
        "contraindications": contra or [],
        "substitution": substitution,
        "required_equipment": equipment,
        "alternatives_by_equipment": alt or {},
    }


# ── 新增 30 条 ────────────────────────────────────────────────────────────
NEW_EXERCISES: List[Dict[str, Any]] = [
    # 10 条动态热身：目标是把关节活动开、体温升起来，负荷极低
    _ex("Arm Circles", "手臂绕环", "Warmup", ["warm_up"], "mobility",
        "Deltoids", ["shoulder"], 1, False, ["bodyweight"],
        "Shoulder Pass-Through", {"band": "Shoulder Pass-Through"}),
    _ex("Leg Swings", "前后摆腿", "Warmup", ["warm_up"], "mobility",
        "Hamstrings", ["hip", "knee"], 1, False, ["bodyweight"],
        "Ankle Rocks"),
    _ex("Cat-Cow", "猫牛式", "Warmup", ["warm_up"], "mobility",
        "Erector Spinae", ["spine"], 1, False, ["bodyweight"],
        "Thoracic Rotation"),
    _ex("Hip Circles", "髋关节绕环", "Warmup", ["warm_up"], "mobility",
        "Gluteus Maximus", ["hip"], 1, False, ["bodyweight"],
        "Leg Swings"),
    _ex("Shoulder Pass-Through", "肩部绕环", "Warmup", ["warm_up"], "mobility",
        "Deltoids", ["shoulder"], 1, False, ["bodyweight", "band"],
        "Arm Circles", {"bodyweight": "Arm Circles"}),
    _ex("Inchworm", "毛毛虫爬行", "Warmup", ["warm_up"], "mobility",
        "Hamstrings", ["shoulder", "spine", "hip"], 1, False, ["bodyweight"],
        "Cat-Cow"),
    _ex("Marching in Place", "原地踏步", "Warmup", ["warm_up"], "warmup",
        "Quadriceps", ["hip", "knee"], 1, False, ["bodyweight"],
        "Leg Swings"),
    _ex("World's Greatest Stretch", "世界最伟大拉伸", "Warmup", ["warm_up"], "mobility",
        "Gluteus Maximus", ["hip", "spine", "shoulder"], 1, False, ["bodyweight"],
        "Hip Flexor Stretch"),
    _ex("Ankle Rocks", "踝关节前后倾", "Warmup", ["warm_up"], "mobility",
        "Gastrocnemius", ["ankle"], 1, False, ["bodyweight"],
        "Marching in Place"),
    _ex("Thoracic Rotation", "胸椎旋转", "Warmup", ["warm_up"], "mobility",
        "Obliques", ["spine", "shoulder"], 1, False, ["bodyweight"],
        "Cat-Cow"),

    # 10 条静态拉伸：放松段专用，全部按时间计
    _ex("Standing Hamstring Stretch", "站姿腘绳肌拉伸", "Stretch", ["cool_down"], "stretch",
        "Hamstrings", ["knee", "hip"], 1, True, ["bodyweight"],
        "Figure-4 Glute Stretch"),
    _ex("Standing Quad Stretch", "站姿股四头肌拉伸", "Stretch", ["cool_down"], "stretch",
        "Quadriceps", ["knee", "hip"], 1, True, ["bodyweight"],
        "Hip Flexor Stretch"),
    _ex("Wall Calf Stretch", "靠墙小腿拉伸", "Stretch", ["cool_down"], "stretch",
        "Gastrocnemius", ["ankle", "knee"], 1, True, ["bodyweight"],
        "Standing Hamstring Stretch"),
    _ex("Doorway Chest Stretch", "门框胸部拉伸", "Stretch", ["cool_down"], "stretch",
        "Pectorals", ["shoulder"], 1, True, ["bodyweight"],
        "Cross-Body Shoulder Stretch"),
    _ex("Child's Pose", "婴儿式", "Stretch", ["cool_down"], "stretch",
        "Erector Spinae", ["spine", "hip", "shoulder"], 1, True, ["bodyweight"],
        "Kneeling Lat Stretch"),
    _ex("Figure-4 Glute Stretch", "四字臀肌拉伸", "Stretch", ["cool_down"], "stretch",
        "Gluteus Maximus", ["hip", "knee"], 1, True, ["bodyweight"],
        "Standing Hamstring Stretch"),
    _ex("Cross-Body Shoulder Stretch", "交叉肩部拉伸", "Stretch", ["cool_down"], "stretch",
        "Rear Deltoids", ["shoulder"], 1, True, ["bodyweight"],
        "Doorway Chest Stretch"),
    _ex("Neck Side Stretch", "颈侧拉伸", "Stretch", ["cool_down"], "stretch",
        "Trapezius", ["neck"], 1, True, ["bodyweight"],
        "Cross-Body Shoulder Stretch"),
    _ex("Hip Flexor Stretch", "髂腰肌拉伸", "Stretch", ["cool_down"], "stretch",
        "Quadriceps", ["hip", "knee"], 1, True, ["bodyweight"],
        "Standing Quad Stretch"),
    _ex("Kneeling Lat Stretch", "跪姿背阔肌拉伸", "Stretch", ["cool_down"], "stretch",
        "Latissimus Dorsi", ["shoulder", "spine"], 1, True, ["bodyweight"],
        "Child's Pose"),

    # 10 条激活稳定：低负荷、重控制，放在主项之前唤醒目标肌群
    _ex("Glute Bridge", "臀桥", "Activation", ["activation", "accessories"], "hinge",
        "Gluteus Maximus", ["hip", "spine"], 1, False, ["bodyweight"],
        "Hip Thrust"),
    _ex("Bird Dog", "鸟狗式", "Activation", ["activation"], "core",
        "Rectus Abdominis", ["spine", "hip", "shoulder"], 1, False, ["bodyweight"],
        "Dead Bug"),
    _ex("Dead Bug", "死虫式", "Activation", ["activation"], "core",
        "Rectus Abdominis", ["spine", "hip"], 1, False, ["bodyweight"],
        "Bird Dog"),
    _ex("Band Pull-Apart", "弹力带拉开", "Activation", ["activation"], "pull_h",
        "Rear Deltoids", ["shoulder"], 1, False, ["band"],
        "Face Pull", {"bodyweight": "Shoulder Pass-Through"}),
    _ex("Clamshell", "蚌式开合", "Activation", ["activation"], "abduction",
        "Gluteus Maximus", ["hip", "knee"], 1, False, ["band", "bodyweight"],
        "Single-Leg Balance", {"bodyweight": "Single-Leg Balance"}),
    _ex("Wall Slide", "靠墙滑臂", "Activation", ["activation"], "push_v",
        "Deltoids", ["shoulder"], 1, False, ["bodyweight"],
        "Scapular Push-Up"),
    _ex("Pallof Press", "帕洛夫推举", "Activation", ["activation", "accessories"], "core",
        "Obliques", ["spine", "shoulder"], 2, False, ["cable", "band"],
        "Dead Bug", {"band": "Band Pull-Apart", "bodyweight": "Dead Bug"}),
    _ex("Suitcase Carry", "单侧农夫行走", "Activation", ["activation", "accessories"], "core",
        "Obliques", ["spine", "shoulder", "knee"], 2, False, ["dumbbell", "kettlebell"],
        "Pallof Press", {"bodyweight": "Dead Bug"}),
    _ex("Single-Leg Balance", "单腿站立", "Activation", ["activation"], "stability",
        "Quadriceps", ["hip", "knee", "ankle"], 1, False, ["bodyweight"],
        "Clamshell"),
    _ex("Scapular Push-Up", "肩胛俯卧撑", "Activation", ["activation"], "push_h",
        "Rhomboids", ["shoulder", "elbow"], 1, False, ["bodyweight"],
        "Wall Slide"),
]


def parse_frontend_labels() -> Dict[str, str]:
    """从 TS 文件里读出 EXERCISE_CN 映射，保证中英口径与前端一致。"""
    if not FRONTEND_LABELS.exists():
        return {}
    src = io.open(FRONTEND_LABELS, encoding="utf-8").read()
    block = src.split("export const EXERCISE_CN")[1].split("export const MUSCLE_CN")[0]
    return dict(re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', block))


def expand(dry_run: bool = False) -> Dict[str, Any]:
    db: List[Dict[str, Any]] = json.loads(io.open(DB_PATH, encoding="utf-8").read())
    labels = parse_frontend_labels()

    # 1) 给现有动作补四个字段
    patched = 0
    for ex in db:
        meta = EXISTING_META.get(int(ex["id"]))
        if meta is None:
            continue
        phases, pattern, timed = meta
        ex["phase"] = phases
        ex["motion_pattern"] = pattern
        ex["is_timed"] = timed
        if not ex.get("name_zh"):
            ex["name_zh"] = NAME_ZH_OVERRIDE.get(ex["name"]) or labels.get(ex["name"]) or ""
            if not ex["name_zh"]:
                raise SystemExit(f"动作 {ex['name']} 缺少中文名，请补 NAME_ZH_OVERRIDE")
        patched += 1

    # 2) 追加新动作，ID 接续
    next_id = max(int(e["id"]) for e in db) + 1
    existing_names = {e["name"] for e in db}
    added: List[Dict[str, Any]] = []
    for tmpl in NEW_EXERCISES:
        if tmpl["name"] in existing_names:
            continue
        rec = {"id": next_id, **tmpl}
        next_id += 1
        added.append(rec)
        existing_names.add(rec["name"])

    db.extend(added)

    # 3) 校验：每条都必须有 phase，且 phase 值合法
    valid_phases = {"warm_up", "activation", "main_lifts", "accessories", "cool_down"}
    for ex in db:
        if not ex.get("phase"):
            raise SystemExit(f"动作 {ex['name']} 缺 phase 字段")
        bad = set(ex["phase"]) - valid_phases
        if bad:
            raise SystemExit(f"动作 {ex['name']} 的 phase 非法: {bad}")

    report = {
        "patched": patched,
        "added": len(added),
        "total": len(db),
        "by_phase": {
            p: sum(1 for e in db if p in e["phase"]) for p in sorted(valid_phases)
        },
        "by_type": {},
    }
    for e in db:
        report["by_type"][e["type"]] = report["by_type"].get(e["type"], 0) + 1

    if dry_run:
        report["added_names"] = [f"{e['id']} {e['name']} / {e['name_zh']}" for e in added]
        return report

    if not BACKUP_PATH.exists():
        shutil.copy2(DB_PATH, BACKUP_PATH)

    io.open(DB_PATH, "w", encoding="utf-8").write(
        json.dumps(db, ensure_ascii=False, indent=2) + "\n"
    )

    # 4) 输出前端需要追加的映射（新增动作的中文名）
    missing_in_frontend = [
        (e["name"], e["name_zh"]) for e in db if e["name"] not in labels
    ]
    report["frontend_missing"] = missing_in_frontend
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    rep = expand(dry_run=args.dry_run)

    print(f"补字段: {rep['patched']} 条")
    print(f"新增:   {rep['added']} 条")
    print(f"总计:   {rep['total']} 条")
    print(f"阶段分布: {rep['by_phase']}")
    print(f"类型分布: {rep['by_type']}")
    if rep.get("added_names"):
        print("新增明细:")
        for n in rep["added_names"]:
            print("  " + n)
    if rep.get("frontend_missing"):
        print(f"前端映射待补 {len(rep['frontend_missing'])} 条:")
        for en, zh in rep["frontend_missing"]:
            print(f'  "{en}": "{zh}",')


if __name__ == "__main__":
    main()
