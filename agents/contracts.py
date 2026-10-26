"""Agent 之间的唯一数据契约。

原则：跨 Agent 只传这些结构，任何一环都不允许把自然语言塞进通道。
``Slot`` 就是论文里要写的那五个字段：``{exercise_id, sets, reps, load_pct, impact}``。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

PHASES: Tuple[str, ...] = (
    "warm_up",
    "activation",
    "main_lifts",
    "accessories",
    "cool_down",
)

# 违规码：评估 Agent 只返回这些枚举，不返回自由文本理由
VIOLATION_CODES: Dict[str, str] = {
    "FORBIDDEN_ID": "命中禁止动作清单",
    "UNKNOWN_ID": "动作 ID 不在知识库中",
    "JOINT_CAP": "负荷超过受伤关节允许上限",
    "IMPACT_CEILING": "冲击等级超过整体上限",
    "LOAD_PCT": "训练强度超过动态约束上限",
    "DUPLICATE": "同一阶段内动作重复",
    "STALE_PROFILE": "计划基于过期的风险档案生成",
    "SEQUENCE": "阶段安排不合理（仅由 LLM 审查通道产出）",
}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Slot:
    """计划中的一个动作槽位 —— 跨 Agent 传递的最小单元。"""

    exercise_id: int
    sets: int
    reps: str
    load_pct: Optional[int] = None
    impact: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exercise_id": self.exercise_id,
            "sets": self.sets,
            "reps": self.reps,
            "load_pct": self.load_pct,
            "impact": self.impact,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Slot":
        return cls(
            exercise_id=int(data["exercise_id"]),
            sets=int(data.get("sets", 3)),
            reps=str(data.get("reps", "10")),
            load_pct=None if data.get("load_pct") is None else int(data["load_pct"]),
            impact=int(data.get("impact", 1)),
        )


@dataclass(frozen=True)
class RuleSpec:
    """一条可审计的谓词规则（只描述、不含可执行代码）。"""

    rule_id: str
    kind: str          # joint_cap | impact_ceiling | forbidden_id | load_pct
    subject: str       # 关节名 / "*" / 动作 ID
    threshold: int
    source: str        # severity | feedback | knowledge_base

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "kind": self.kind,
            "subject": self.subject,
            "threshold": self.threshold,
            "source": self.source,
        }


@dataclass
class RiskProfile:
    """状态与风险分析 Agent 的产物：用户专属的可执行约束集。"""

    user_id: str
    allowed_ids: Tuple[int, ...]
    forbidden_reasons: Dict[int, str]
    joint_caps: Dict[str, int]
    impact_ceiling: int
    load_pct_cap: Optional[int]
    rules: Tuple[RuleSpec, ...] = ()
    profile_hash: str = ""
    # ── LLM 增强通道的痕迹（仅供审计，不参与谓词判定）──────────────────────
    llm_forbidden: Tuple[int, ...] = ()      # LLM 追加的禁忌 ID（规则集之外）
    llm_joint_caps: Dict[str, int] = field(default_factory=dict)  # LLM 下调的关节上限
    llm_rationale: str = ""
    llm_status: str = ""                     # skipped | applied | empty | error
    llm_prompt_version: str = ""

    def __post_init__(self) -> None:
        self.allowed_ids = tuple(sorted(int(i) for i in self.allowed_ids))
        self.forbidden_reasons = {int(k): str(v) for k, v in (self.forbidden_reasons or {}).items()}
        self.joint_caps = {str(k): int(v) for k, v in (self.joint_caps or {}).items()}
        self.llm_forbidden = tuple(sorted(int(i) for i in (self.llm_forbidden or ())))
        self.llm_joint_caps = {
            str(k): int(v) for k, v in (self.llm_joint_caps or {}).items()
        }
        if not self.profile_hash:
            self.profile_hash = self.compute_hash()

    def compute_hash(self) -> str:
        payload = {
            "user_id": self.user_id,
            "allowed_ids": list(self.allowed_ids),
            "forbidden": sorted(self.forbidden_reasons.keys()),
            "joint_caps": self.joint_caps,
            "impact_ceiling": self.impact_ceiling,
            "load_pct_cap": self.load_pct_cap,
            "rules": [r.to_dict() for r in self.rules],
        }
        return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "allowed_ids": list(self.allowed_ids),
            "forbidden_reasons": {str(k): v for k, v in sorted(self.forbidden_reasons.items())},
            "joint_caps": dict(sorted(self.joint_caps.items())),
            "impact_ceiling": self.impact_ceiling,
            "load_pct_cap": self.load_pct_cap,
            "rules": [r.to_dict() for r in self.rules],
            "profile_hash": self.profile_hash,
            "llm_forbidden": list(self.llm_forbidden),
            "llm_joint_caps": dict(sorted(self.llm_joint_caps.items())),
            "llm_rationale": self.llm_rationale,
            "llm_status": self.llm_status,
            "llm_prompt_version": self.llm_prompt_version,
        }


@dataclass
class PlanDraft:
    """计划生成 Agent 的产物：只有槽位，没有自然语言描述。"""

    plan_id: str
    user_id: str
    workout_type: str
    phases: Dict[str, List[Slot]]
    generator: str                 # deterministic | llm
    grammar_version: str
    prompt_version: str = ""
    profile_hash: str = ""
    rejected_ids: Tuple[int, ...] = ()   # 生成阶段被文法挡回的 ID（LLM 幻觉审计）

    def iter_slots(self) -> Iterable[Tuple[str, Slot]]:
        for phase in PHASES:
            for slot in self.phases.get(phase, []):
                yield phase, slot

    def all_ids(self) -> List[int]:
        return [s.exercise_id for _, s in self.iter_slots()]

    def slot_count(self) -> int:
        return sum(len(self.phases.get(p, [])) for p in PHASES)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "user_id": self.user_id,
            "workout_type": self.workout_type,
            "phases": {p: [s.to_dict() for s in self.phases.get(p, [])] for p in PHASES},
            "generator": self.generator,
            "grammar_version": self.grammar_version,
            "prompt_version": self.prompt_version,
            "profile_hash": self.profile_hash,
            "rejected_ids": list(self.rejected_ids),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanDraft":
        return cls(
            plan_id=data["plan_id"],
            user_id=data["user_id"],
            workout_type=data.get("workout_type", "full_body"),
            phases={
                p: [Slot.from_dict(s) for s in data.get("phases", {}).get(p, [])]
                for p in PHASES
            },
            generator=data.get("generator", "deterministic"),
            grammar_version=data.get("grammar_version", ""),
            prompt_version=data.get("prompt_version", ""),
            profile_hash=data.get("profile_hash", ""),
            rejected_ids=tuple(int(i) for i in data.get("rejected_ids", []) or []),
        )


@dataclass(frozen=True)
class Violation:
    """一条违规记录 —— 只有枚举码和结构化定位，便于统计与审计。"""

    code: str
    exercise_id: int
    phase: str
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "exercise_id": self.exercise_id,
            "phase": self.phase,
            "detail": self.detail,
            "label": VIOLATION_CODES.get(self.code, ""),
        }


@dataclass
class SafetyReport:
    """安全评估 Agent 的产物。"""

    passed: bool
    violations: Tuple[Violation, ...] = ()
    checked_slots: int = 0
    masked_count: int = 0          # 候选池里被文法屏蔽掉的禁忌动作数量
    adversarial_probes: int = 0    # 对抗探针：主动注入禁忌 ID 后仍被拦下的次数
    adversarial_blocked: int = 0
    # ── LLM 审查通道（合取验收，只能加严不能放宽）────────────────────────
    llm_verdict: str = "skipped"   # pass | fail | error | skipped
    llm_disagreed: bool = False    # LLM 结论与规则结论不一致
    llm_rationale: str = ""
    llm_prompt_version: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "checked_slots": self.checked_slots,
            "masked_count": self.masked_count,
            "adversarial_probes": self.adversarial_probes,
            "adversarial_blocked": self.adversarial_blocked,
            "llm_verdict": self.llm_verdict,
            "llm_disagreed": self.llm_disagreed,
            "llm_rationale": self.llm_rationale,
            "llm_prompt_version": self.llm_prompt_version,
        }
