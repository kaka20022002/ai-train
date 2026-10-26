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

# 违规码：评估 Agent 只返回这些枚举，不返回自由文本理由。
# v3 起前七项由「基线谓词」算出并作为**证据**交给审查 Agent，后六项只能由
# 模型在审查时产出 —— 两条来源最终都汇进同一份 violations 通道。
VIOLATION_CODES: Dict[str, str] = {
    "FORBIDDEN_ID": "命中禁止动作清单",
    "UNKNOWN_ID": "动作 ID 不在知识库中",
    "JOINT_CAP": "负荷超过受伤关节允许上限",
    "IMPACT_CEILING": "冲击等级超过整体上限",
    "LOAD_PCT": "训练强度超过动态约束上限",
    "DUPLICATE": "同一阶段内动作重复",
    "STALE_PROFILE": "计划基于过期的风险档案生成",
    "PRESCRIPTION_RANGE": "组数/次数/强度与该动作性质明显不符",
    "SEQUENCE": "阶段安排不合理",
    "VOLUME": "总容量超出用户当前承受水平",
    "INTENSITY": "强度与用户训练水平不匹配",
    "RECOVERY": "恢复安排不足",
    "CONTRAINDICATION": "病历明示但基线谓词未覆盖的禁忌",
    "EQUIPMENT_UNAVAILABLE": "使用了用户没有的器械（可执行性问题）",
    "REPORT_BREACH": "违反阶段一风险报告明确列出的限制",
}

# 基线谓词判得出（模型也能补充判断）与只能由模型判断的维度
BASELINE_CODES = frozenset(
    {
        "FORBIDDEN_ID",
        "UNKNOWN_ID",
        "JOINT_CAP",
        "IMPACT_CEILING",
        "LOAD_PCT",
        "DUPLICATE",
        "STALE_PROFILE",
        "EQUIPMENT_UNAVAILABLE",
        # 动作模式禁忌能机械比对；报告里那些只能靠阅读的限制不在此列
        "REPORT_BREACH",
    }
)

LLM_ONLY_CODES = frozenset(
    {"SEQUENCE", "VOLUME", "INTENSITY", "RECOVERY", "CONTRAINDICATION", "PRESCRIPTION_RANGE"}
)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Slot:
    """计划中的一个动作槽位 —— 跨 Agent 传递的最小单元。

    前五个字段是不变量（``{exercise_id, sets, reps, load_pct, impact}``），
    保证任何一份计划都能被谓词集直接校验；后两个是模型给出的**表达性**
    字段（单动作要点、组间休息），不参与合规判定，只影响可读性与体验。
    """

    exercise_id: int
    sets: int
    reps: str
    load_pct: Optional[int] = None
    impact: int = 1
    note: str = ""
    rest_seconds: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exercise_id": self.exercise_id,
            "sets": self.sets,
            "reps": self.reps,
            "load_pct": self.load_pct,
            "impact": self.impact,
            "note": self.note,
            "rest_seconds": self.rest_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Slot":
        rest = data.get("rest_seconds")
        return cls(
            exercise_id=int(data["exercise_id"]),
            sets=int(data.get("sets", 3)),
            reps=str(data.get("reps", "10")),
            load_pct=None if data.get("load_pct") is None else int(data["load_pct"]),
            impact=int(data.get("impact", 1)),
            note=str(data.get("note") or ""),
            rest_seconds=None if rest is None else int(rest),
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
    # ── LLM 增强通道的痕迹（参与约束，但不来自阈值表）──────────────────────
    llm_forbidden: Tuple[int, ...] = ()      # LLM 追加的禁忌 ID（规则集之外）
    llm_joint_caps: Dict[str, int] = field(default_factory=dict)  # LLM 下调的关节上限
    llm_rationale: str = ""
    llm_status: str = ""                     # skipped | applied | empty | error
    llm_prompt_version: str = ""
    # 规则表结构性算不出来的约束：来自病历自由文本的语义抽取
    avoid_patterns: Tuple[str, ...] = ()     # 需回避的动作模式（如 deep_knee_flexion）
    session_cap_minutes: Optional[int] = None  # 单次训练时长上限
    progression_note: str = ""               # 进阶/退阶的整体方向说明
    capacity_note: str = ""                  # 对当前训练容量的判断
    fitness_level: str = ""                  # 训练水平（生成端定剂量时需要）
    # ── 用户上下文透传（不参与合规判定，但生成端必须看到）──────────────────
    # 结构化字段：目标、器械、偏好、本次需求。故意不进 profile_hash：
    # 换目标或换器械不会让已生成的计划变得「过期」，合规性也不因此改变。
    user_context: Dict[str, Any] = field(default_factory=dict)
    # ── 阶段一的对外产物：风险报告 ────────────────────────────────────────
    # 上面那些字段是「结论的机器可执行投影」，这份报告才是给下游 Agent 和
    # 用户看的**判断本身**：整体风险等级、能否开练、每条伤情的功能影响、
    # 明确禁忌、剂量口径、需要盯的信号。
    # 故意不进 profile_hash：报告含叙述文本，同输入重跑一次措辞就会变，
    # 不能让 hash 抖动导致下游误判 STALE_PROFILE。
    risk_report: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.allowed_ids = tuple(sorted(int(i) for i in self.allowed_ids))
        self.forbidden_reasons = {int(k): str(v) for k, v in (self.forbidden_reasons or {}).items()}
        self.joint_caps = {str(k): int(v) for k, v in (self.joint_caps or {}).items()}
        self.llm_forbidden = tuple(sorted(int(i) for i in (self.llm_forbidden or ())))
        self.llm_joint_caps = {
            str(k): int(v) for k, v in (self.llm_joint_caps or {}).items()
        }
        self.avoid_patterns = tuple(
            sorted({str(p).strip().lower() for p in (self.avoid_patterns or ()) if str(p).strip()})
        )
        if not self.profile_hash:
            self.profile_hash = self.compute_hash()

    # ── 风险报告的两个高频取值（下游不必层层 .get）────────────────────────
    @property
    def risk_level(self) -> str:
        return str((self.risk_report or {}).get("overall", {}).get("risk_level") or "")

    @property
    def clearance(self) -> str:
        return str((self.risk_report or {}).get("overall", {}).get("clearance") or "")

    def compute_hash(self) -> str:
        payload = {
            "user_id": self.user_id,
            "allowed_ids": list(self.allowed_ids),
            "forbidden": sorted(self.forbidden_reasons.keys()),
            "joint_caps": self.joint_caps,
            "impact_ceiling": self.impact_ceiling,
            "load_pct_cap": self.load_pct_cap,
            "avoid_patterns": list(self.avoid_patterns),
            "session_cap_minutes": self.session_cap_minutes,
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
            "avoid_patterns": list(self.avoid_patterns),
            "session_cap_minutes": self.session_cap_minutes,
            "progression_note": self.progression_note,
            "capacity_note": self.capacity_note,
            "user_context": dict(self.user_context),
            "risk_report": dict(self.risk_report or {}),
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
    rejected_ids: Tuple[int, ...] = ()   # 知识库里不存在的 ID（模型幻觉审计）
    adjusted_slots: int = 0              # 参数缺失、由处方兜底补全的槽位数

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
            "adjusted_slots": self.adjusted_slots,
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
            adjusted_slots=int(data.get("adjusted_slots", 0) or 0),
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
    """安全评估 Agent 的产物。

    v3 起判定权归属审查 Agent 本身：

        review_mode="agent"    模型裁决。``baseline_flags`` 只是上游规则的
                               提示，模型可以确认、也可以否决，但必须给理由。
        review_mode="baseline" 没有审查 Agent（未配 key）时的降级路径，
                               由基线谓词直接判定，响应里会明确标注。
        review_mode="baseline_fallback"
                               Agent 调用失败（超时 / 坏 JSON），退回基线判定。
    """

    passed: bool
    violations: Tuple[Violation, ...] = ()
    # 基线谓词的命中项 —— 证据，不是判决。只在降级模式下直接当违规用。
    baseline_flags: Tuple[Violation, ...] = ()
    checked_slots: int = 0
    review_mode: str = "baseline"
    # ── 审查 Agent 的痕迹 ─────────────────────────────────────────────────
    llm_verdict: str = "skipped"   # pass | fail | error | skipped
    llm_disagreed: bool = False    # 模型结论与基线提示不一致（论文里的分歧指标）
    llm_rationale: str = ""
    llm_prompt_version: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "baseline_flags": [v.to_dict() for v in self.baseline_flags],
            "checked_slots": self.checked_slots,
            "review_mode": self.review_mode,
            "llm_verdict": self.llm_verdict,
            "llm_disagreed": self.llm_disagreed,
            "llm_rationale": self.llm_rationale,
            "llm_prompt_version": self.llm_prompt_version,
        }
