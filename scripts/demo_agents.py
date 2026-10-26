# -*- coding: utf-8 -*-
"""演示多 Agent 管线：膝伤 HIGH 用户从档案到计划再到审计。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.contracts import PHASES  # noqa: E402
from agents.pipeline import run_pipeline  # noqa: E402

OUT = Path(r"C:\Users\黑大帅X\WorkBuddy\红鸟项目\agents_demo.txt")
db = json.loads((ROOT / "exercise_db.json").read_text(encoding="utf-8"))
index = {int(e["id"]): e for e in db}

PROFILE = {
    "user_id": "demo_knee",
    "basic_info": {"age": 28, "gender": "male"},
    "fitness_level": "beginner",
    "medical_history": [
        {"location": "knee", "condition": "meniscus_tear", "severity": "high"},
        {"location": "shoulder", "condition": "mild_impingement", "severity": "low"},
    ],
}

res = run_pipeline(db, PROFILE, workout_type="full_body", seed=2026)
L = []
L.append("=" * 64)
L.append("输入档案：膝 HIGH（半月板撕裂） + 肩 LOW（轻度撞击）")
L.append("=" * 64)

p = res.profile
L.append("")
L.append("【Stage 1】状态与风险分析 Agent 输出（结构化）")
L.append("  profile_hash : %s" % p.profile_hash)
L.append("  允许动作     : %d 个" % len(p.allowed_ids))
L.append("  禁止动作     : %d 个" % len(p.forbidden_reasons))
L.append("  关节上限     : %s" % p.joint_caps)
L.append("  impact 上限  : %d" % p.impact_ceiling)
L.append("  强度上限     : %s" % (p.load_pct_cap or "无"))
L.append("  谓词规则     : %d 条" % len(p.rules))
for r in p.rules[:8]:
    L.append("     - [%s] %s <= %s  (%s)" % (r.kind, r.subject, r.threshold, r.source))
if len(p.rules) > 8:
    L.append("     … 另有 %d 条" % (len(p.rules) - 8))

L.append("")
L.append("【Stage 2】计划生成 Agent 输出（只有 exercise_id/sets/reps/load_pct/impact）")
L.append("  generator=%s   grammar=%s   槽位 %d 个"
         % (res.draft.generator, res.draft.grammar_version, res.draft.slot_count()))
for phase in PHASES:
    slots = res.draft.phases.get(phase, [])
    L.append("  %s:" % phase)
    for s in slots:
        name = index.get(s.exercise_id, {}).get("name", "?")
        L.append("     id=%-3d %-32s %dx%-10s %s%%  impact=%d"
                 % (s.exercise_id, name, s.sets, s.reps,
                    "-" if s.load_pct is None else s.load_pct, s.impact))

rep = res.report
L.append("")
L.append("【Stage 3】安全评估 Agent 输出")
L.append("  通过         : %s" % ("是 ✅" if rep.passed else "否 ❌"))
L.append("  校验槽位     : %d" % rep.checked_slots)
L.append("  违规         : %d 条" % len(rep.violations))
L.append("  判定者       : %s" % {"agent": "审查 Agent", "baseline": "基线谓词（未接模型）",
                                  "baseline_fallback": "基线谓词（审查调用失败）"}.get(rep.review_mode, rep.review_mode))
L.append("  模型结论     : %s" % rep.llm_verdict)
L.append("  基线提示     : %d 项（证据，非判决）" % len(rep.baseline_flags))
L.append("  会审回炉     : %d 轮" % res.review_rounds)

L.append("")
L.append("【交叉验证】计划里出现的 ID 与禁止集求交集：")
ids = set(res.draft.all_ids())
overlap = ids & set(p.forbidden_reasons)
L.append("  计划动作 %d 个，交集 %d 个 → %s"
         % (len(ids), len(overlap), "无违规 ✅" if not overlap else "有违规 ❌"))
L.append("  被禁但从未出现（示例）：%s"
         % ", ".join("%d:%s" % (i, index[i]["name"]) for i in sorted(p.forbidden_reasons)[:4]))

L.append("")
L.append("【审计链】")
for e in res.audit.to_dict()["entries"]:
    L.append("  #%d %-12s in=%s" % (e["seq"], e["stage"], json.dumps(e["in"], ensure_ascii=False)[:70]))
    L.append("      out=%s" % json.dumps(e["out"], ensure_ascii=False)[:110])

OUT.write_text("\n".join(L), encoding="utf-8")
print("done")
