"""Agent 2 —— 计划生成。

职责边界：
    输入：``RiskProfile``（基线证据，只读）+ ``ExerciseCatalog``（全量动作库）
    输出：``PlanDraft``

**权力结构（v4 起）：模型是全权决策者。**

    v2  规则裁剪候选 → 模型从剩下的里挑 ID → 规则夹紧参数
    v3  规则裁剪候选 → 模型给完整槽位 → 规则夹紧参数
    v4  全库给模型 → 模型自己判断哪些动作不该做 → 参数原样落库
        （唯一保留的动作是「渲染前必须能对上号」的结构清洗：未知 ID 丢弃）

也就是说：中间那层「候选裁剪 / enum 掩码 / 阶段硬过滤 / 处方区间夹紧 /
数量补位」全部移除。模型看到 77 条动作的全部信息（类型、模式、冲击、
阶段归属、器械、偏好标记、上游的基线禁忌清单），它自己决定选哪些、放哪个
阶段、做几组几次多重、休息多久。

为什么可以这样做
----------------
安全性不再由「生成端不可能输出」保证，而由第 3 个 Agent **事后会审**保证：
计划生成完，审查 Agent 拿到计划 + 病历 + 基线提示，逐条裁决；判 fail 就把
违规项反馈回来，让同一个生成 Agent 自己改（``revise``），最多 N 轮。

两种后端：
    llm           —— 主路径，全库自由生成
    deterministic —— 降级路径（没配 key）。此时才用 ``RiskGrammar`` 的
                     候选裁剪与处方推荐值，因为没有任何模型可以判断
"""

from __future__ import annotations

import random
import uuid
import zlib
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from agents.catalog import ExerciseCatalog
from agents.contracts import PHASES, PlanDraft, RiskProfile, Slot
from agents.prescription import (
    PHASE_COUNT,
    PHASE_MAX_IMPACT,
    prescribe,
    phase_quota,
)
from agents.prompts import PLAN_GEN_PROMPT_VERSION

# 兼容旧引用：pipeline 等处仍按 ``PHASE_PRESCRIPTION[phase]["count"]`` 取数量
PHASE_PRESCRIPTION: Dict[str, Dict[str, Any]] = {
    phase: {"count": PHASE_COUNT[phase], "max_impact": PHASE_MAX_IMPACT[phase]}
    for phase in PHASES
}

LLMPlanFn = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


def _pattern_of(index: Dict[int, Dict[str, Any]], eid: int) -> str:
    meta = index.get(eid) or {}
    return str(meta.get("motion_pattern") or meta.get("type") or "other")


def pick_diverse(
    pool: Sequence[int],
    quota: int,
    index: Dict[int, Dict[str, Any]],
) -> List[int]:
    """从候选池里挑 ``quota`` 个动作，优先覆盖不同的动作模式。

    只服务降级后端：确定性采样没有模型那样的全局视野，只能靠这条规则
    避免「三个弯举」。
    """
    picked: List[int] = []
    seen: set = set()
    for eid in pool:
        if len(picked) >= quota:
            break
        pat = _pattern_of(index, eid)
        if pat in seen:
            continue
        seen.add(pat)
        picked.append(eid)
    if len(picked) < quota:
        for eid in pool:
            if len(picked) >= quota:
                break
            if eid not in picked:
                picked.append(eid)
    return picked


class PlanAgent:
    """计划生成 Agent。"""

    name = "plan_gen"

    def __init__(self, llm_plan_fn: Optional[LLMPlanFn] = None) -> None:
        self._llm_plan_fn = llm_plan_fn

    @property
    def can_revise(self) -> bool:
        """能否按审查意见自行重写（只有接了模型才可以）。"""
        return self._llm_plan_fn is not None

    def generate(
        self,
        profile: RiskProfile,
        catalog: ExerciseCatalog,
        workout_type: str = "full_body",
        seed: Optional[int] = None,
    ) -> PlanDraft:
        if self._llm_plan_fn is not None:
            draft = self._generate_free(profile, catalog, workout_type)
            if draft is not None:
                return draft
        return self._generate_deterministic(profile, catalog, workout_type, seed)

    # ── 全库自由生成（主路径）──────────────────────────────────────────────
    def _generate_free(
        self,
        profile: RiskProfile,
        catalog: ExerciseCatalog,
        workout_type: str,
    ) -> Optional[PlanDraft]:
        payload = self.build_request_payload(profile, catalog, workout_type)
        return self._call_and_parse(payload, profile, catalog, workout_type, mode="fresh")

    def revise(
        self,
        profile: RiskProfile,
        catalog: ExerciseCatalog,
        draft: PlanDraft,
        violations: Sequence[Any],
        rationale: str = "",
        user_request: str = "",
    ) -> Optional[PlanDraft]:
        """在上一版计划上重写 —— 由**同一个**生成 Agent 自己改，而不是规则补位。

        两种触发：
        - 审查驳回：``violations`` 有内容，模型要看到自己错在哪；
        - 用户改稿：``user_request`` 是用户原话（「深蹲去掉」「减到 30 分钟」），
          此时按用户要求改，其余部分尽量保持不变。
        """
        if self._llm_plan_fn is None:
            return None
        payload = self.build_request_payload(profile, catalog, draft.workout_type)
        payload["review_feedback"] = {
            "violations": [
                v.to_dict() if hasattr(v, "to_dict") else dict(v) for v in violations
            ],
            "rationale": rationale,
            "user_request": user_request,
        }
        payload["previous_attempt"] = _compact_draft(draft, catalog)
        return self._call_and_parse(payload, profile, catalog, draft.workout_type, mode="revise")

    def _call_and_parse(
        self,
        payload: Dict[str, Any],
        profile: RiskProfile,
        catalog: ExerciseCatalog,
        workout_type: str,
        mode: str,
    ) -> Optional[PlanDraft]:
        try:
            raw = self._llm_plan_fn(payload, catalog.slot_schema())  # type: ignore[misc]
        except Exception:  # noqa: BLE001 - 模型不可用时退回降级后端
            return None
        if not isinstance(raw, dict):
            return None

        phases: Dict[str, List[Slot]] = {}
        rejected: List[int] = []
        defaulted = 0
        used: set = set()

        for phase in PHASES:
            slots: List[Slot] = []
            for item in raw.get(phase, []) or []:
                if not isinstance(item, dict) or "exercise_id" not in item:
                    continue
                try:
                    eid = int(item["exercise_id"])
                except (TypeError, ValueError):
                    continue
                # 唯一的硬清洗：ID 必须能在库里对上号，否则渲染不出名字。
                # 「这个动作不该做」不在这里判 —— 那是审查 Agent 的活。
                if not catalog.has(eid):
                    rejected.append(eid)
                    continue
                if eid in used:
                    # 同一个动作整节课只留一次（纯结构，避免前端重复渲染）
                    continue
                slot, was_defaulted = self._build_slot(
                    phase, eid, item, catalog, profile
                )
                defaulted += int(was_defaulted)
                slots.append(slot)
                used.add(eid)
            phases[phase] = slots

        if not any(phases.values()):
            # 一条可用动作都没有：与其交出一份空计划，不如退回确定性后端，
            # 并在 generator 字段里如实体现（审计能看到是模型输出不可用）。
            return None

        return PlanDraft(
            plan_id=f"draft_{uuid.uuid4().hex[:10]}",
            user_id=profile.user_id,
            workout_type=workout_type,
            phases=phases,
            generator="llm" if mode == "fresh" else "llm_revised",
            grammar_version=catalog.version,
            prompt_version=PLAN_GEN_PROMPT_VERSION,
            profile_hash=profile.profile_hash,
            rejected_ids=tuple(rejected),
            adjusted_slots=defaulted,
        )

    @staticmethod
    def _build_slot(
        phase: str,
        eid: int,
        item: Dict[str, Any],
        catalog: ExerciseCatalog,
        profile: RiskProfile,
    ) -> Tuple[Slot, bool]:
        """把模型给的一条动作转成槽位 —— **原样采纳，不夹紧**。

        唯一会被改写的情况是「模型没给」：缺 sets / reps 时用工具体系里的
        推荐值补齐，保证前端不会渲染出空值。模型给了什么就是什么，哪怕
        超出常识范围 —— 那由审查 Agent 判，不在这里悄悄改掉。
        """
        meta = catalog.meta(eid)
        defaulted = False

        sets = _as_int(item.get("sets"))
        if sets is None or sets <= 0:
            sets = prescribe(phase, meta, profile.load_pct_cap).sets
            defaulted = True

        reps = str(item.get("reps") or "").strip()
        if not reps:
            reps = prescribe(phase, meta, profile.load_pct_cap).reps
            defaulted = True

        if "load_pct" in item:
            load = _as_int(item.get("load_pct"))
        else:
            load = prescribe(phase, meta, profile.load_pct_cap).load_pct
            defaulted = True

        rest = _as_int(item.get("rest_seconds"))
        if rest is not None:
            # 只为渲染兜底（负数/天文数字会让时长估算失真），不是安全判定
            rest = min(max(rest, 0), 600)

        return (
            Slot(
                exercise_id=eid,
                sets=sets,
                reps=reps,
                load_pct=load,
                impact=catalog.impact_of(eid),
                note=str(item.get("note") or "").strip()[:120],
                rest_seconds=rest,
            ),
            defaulted,
        )

    # ── 请求体 ────────────────────────────────────────────────────────────
    def build_request_payload(
        self,
        profile: RiskProfile,
        catalog: ExerciseCatalog,
        workout_type: str,
    ) -> Dict[str, Any]:
        """发给模型的请求体：全量目录 + 完整用户输入 + 阶段一的风险报告。

        三个上游输入按权威度排列：

        ``risk_report``   阶段一的医学结论（判断层）。首要依据。
        ``baseline``      同一结论的机器可执行版本（禁忌与硬上限）。下限。
        用户需求与偏好     目标、器械、偏好、本次原话。决定"练什么"。
        """
        ctx = profile.user_context or {}
        payload: Dict[str, Any] = {
            "workout_type": workout_type,
            "fitness_level": profile.fitness_level or "beginner",
            "session_cap_minutes": profile.session_cap_minutes,
            # 没有模型时它也是基线报告，形状始终完整 —— 下游不必判空
            "risk_report": dict(profile.risk_report or {}),
            "exercise_catalog": catalog.rows(ctx.get("preferences") or {}),
            "baseline": {
                "note": "阶段一结论的机器可执行投影（禁忌清单与上限）：不是硬约束，"
                        "但越线会被审查员逐条追问；与 risk_report 冲突时按更严的一方执行",
                "forbidden_exercises": [
                    {"exercise_id": eid, "reason": reason}
                    for eid, reason in sorted(profile.forbidden_reasons.items())
                    if not reason.startswith("EQUIPMENT")
                ],
                "unavailable_exercises": [
                    {"exercise_id": eid, "reason": reason}
                    for eid, reason in sorted(profile.forbidden_reasons.items())
                    if reason.startswith("EQUIPMENT")
                ],
                "avoid_patterns": list(profile.avoid_patterns),
                "joint_caps": dict(sorted(profile.joint_caps.items())),
                "impact_ceiling": profile.impact_ceiling,
                "load_pct_cap": profile.load_pct_cap,
                "progression_note": profile.progression_note or None,
                "capacity_note": profile.capacity_note or None,
                "rationale": profile.llm_rationale or None,
            },
            "reference_doses": catalog.reference_doses(),
            "catalog_version": catalog.version,
            "profile_hash": profile.profile_hash,
        }

        # 用户需求与偏好：只在有值时下发，避免空字段占 token
        optional: Dict[str, Any] = {
            "fitness_goal": ctx.get("fitness_goal"),
            "training_frequency": ctx.get("training_frequency"),
            "available_equipment": ctx.get("available_equipment") or None,
            "preferences": ctx.get("preferences") or None,
            "user_request": ctx.get("query") or None,
            "medical_history": _medical_digest(profile),
        }
        for key, value in optional.items():
            if value:
                payload[key] = value
        return payload

    # ── 降级后端（没有模型可用时的确定性生成）──────────────────────────────
    def _generate_deterministic(
        self,
        profile: RiskProfile,
        catalog: ExerciseCatalog,
        workout_type: str,
        seed: Optional[int] = None,
    ) -> PlanDraft:
        """没有模型时的兜底：此时才动用语法的候选裁剪与处方推荐值。

        分工很明确 —— 模型在的时候用不上这套；模型不在的时候，没有它就只能
        输出无法执行的东西。生成器标记为 ``deterministic``，响应里也会注明
        「本次未经 Agent 审查」。
        """
        from agents.grammar import RiskGrammar  # 局部导入：只在降级路径用

        grammar = RiskGrammar(profile, catalog.index)
        # 种子必须跨进程稳定：内置 hash() 受 PYTHONHASHSEED 影响，同一份档案
        # 重启一次服务就换一套计划，「确定性后端」就名不副实了。
        rng = random.Random(
            seed
            if seed is not None
            else zlib.crc32((profile.profile_hash + workout_type).encode("utf-8"))
        )
        phases: Dict[str, List[Slot]] = {}
        used: List[int] = []

        for phase in PHASES:
            pool = self._build_pool(profile, grammar, phase, used, rng)
            picked = pick_diverse(pool, phase_quota(phase), grammar.index)

            slots: List[Slot] = []
            for eid in picked:
                meta = grammar.index.get(eid) or {}
                pres = prescribe(phase, meta, profile.load_pct_cap)
                slots.append(
                    Slot(
                        exercise_id=eid,
                        sets=pres.sets,
                        reps=pres.reps,
                        load_pct=pres.load_pct,
                        impact=grammar.impact_of(eid),
                    )
                )
                used.append(eid)
            phases[phase] = slots

        if not any(phases.values()):
            # 一条可用动作都没有：与其交出一份空计划，不如退回确定性后端，
            # 并在 generator 字段里如实体现（审计能看到是模型输出不可用）。
            return None

        return PlanDraft(
            plan_id=f"draft_{uuid.uuid4().hex[:10]}",
            user_id=profile.user_id,
            workout_type=workout_type,
            phases=phases,
            generator="deterministic",
            grammar_version=catalog.version,
            profile_hash=profile.profile_hash,
        )

    def _build_pool(
        self,
        profile: RiskProfile,
        grammar: Any,
        phase: str,
        used: Sequence[int],
        rng: random.Random,
    ) -> List[int]:
        """按「严格 → 放宽 impact → 放宽阶段」三级构建候选池（仅降级后端）。"""
        from agents.prescription import phase_impact_limit

        ceiling = profile.impact_ceiling
        stage_cap = min(phase_impact_limit(phase), ceiling)

        strict = [
            eid
            for eid in grammar.candidates(phase, exclude=used, rng=rng)
            if grammar.impact_of(eid) <= stage_cap
        ]
        pool = list(strict)

        if len(pool) < phase_quota(phase):
            pool += [
                eid
                for eid in grammar.candidates(phase, exclude=used, rng=rng)
                if eid not in pool and grammar.impact_of(eid) <= ceiling
            ]

        if len(pool) < phase_quota(phase):
            loose = grammar.candidates(
                phase, exclude=used, rng=rng, allow_fallback=True
            )
            pool += [
                eid
                for eid in loose
                if eid not in pool and grammar.impact_of(eid) <= ceiling
            ]
        return self._apply_preferences(pool, profile, grammar.index)

    @staticmethod
    def _apply_preferences(
        pool: List[int],
        profile: RiskProfile,
        index: Dict[int, Dict[str, Any]],
    ) -> List[int]:
        """偏好软约束（仅降级后端）：候选充足时排除不喜欢的，全被讨厌时才妥协。"""
        prefs = (profile.user_context or {}).get("preferences") or {}
        liked = {str(p).strip().lower() for p in (prefs.get("liked_patterns") or [])}
        disliked_patterns = {
            str(p).strip().lower() for p in (prefs.get("disliked_patterns") or [])
        }
        disliked_names = {
            str(p).strip().lower() for p in (prefs.get("disliked_exercises") or [])
        }
        if not (liked or disliked_patterns or disliked_names):
            return pool

        def rank(eid: int) -> int:
            meta = index.get(eid) or {}
            pattern = str(meta.get("motion_pattern") or "").strip().lower()
            names = {
                str(meta.get("name") or "").strip().lower(),
                str(meta.get("name_zh") or "").strip().lower(),
            }
            if pattern in disliked_patterns or names & disliked_names:
                return 2
            return 0 if pattern in liked else 1

        ranked = sorted(pool, key=rank)  # sorted 稳定，同档保持原随机顺序
        keep = [eid for eid in ranked if rank(eid) < 2]
        return keep or ranked


# ── 辅助 ────────────────────────────────────────────────────────────────────
def _as_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _medical_digest(profile: RiskProfile) -> List[Dict[str, Any]]:
    """把病历原文摘给生成端。

    以前生成端只看得到「已编译成约束」的结论（禁忌 ID、关节上限），看不到
    伤在哪、为什么。v4 把原文一并给过去 —— 否则它无从判断某条基线禁忌
    是否适用于本次训练。
    """
    out: List[Dict[str, Any]] = []
    for item in (profile.user_context or {}).get("medical_history") or []:
        if not isinstance(item, dict):
            continue
        row = {
            k: item.get(k)
            for k in ("location", "condition", "severity", "pain_trigger", "notes")
            if item.get(k)
        }
        if row:
            out.append(row)
    return out


def _compact_draft(draft: PlanDraft, catalog: ExerciseCatalog) -> Dict[str, Any]:
    """上一版计划的紧凑表示，供修订轮使用。"""
    return {
        "plan_id": draft.plan_id,
        "phases": {
            phase: [
                {
                    "exercise_id": s.exercise_id,
                    "name": catalog.name(s.exercise_id),
                    "sets": s.sets,
                    "reps": s.reps,
                    "load_pct": s.load_pct,
                }
                for s in draft.phases.get(phase, [])
            ]
            for phase in PHASES
        },
    }


def describe_phases(draft: PlanDraft) -> str:
    """把草稿渲染成人看的文本 —— 只在管线最外层调用，不参与 Agent 通信。"""
    lines = [f"plan_id={draft.plan_id} generator={draft.generator}"]
    for phase in PHASES:
        slots = draft.phases.get(phase, [])
        lines.append(f"  {phase}: " + ", ".join(str(s.exercise_id) for s in slots))
    return "\n".join(lines)


__all__ = ["PlanAgent", "PHASE_PRESCRIPTION", "describe_phases", "pick_diverse"]
