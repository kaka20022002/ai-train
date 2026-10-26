"""Agent 2 —— 计划生成。

职责边界：
    输入：``RiskProfile``（只读）+ ``RiskGrammar``（只读）+ 训练类型
    输出：``PlanDraft``

**权力结构（v3 起）**：模型是决策者，规则是兜底者。

    模型决定   选哪些动作、放在哪个阶段、顺序、组数、次数、负荷、休息、单动作要点
    规则兜底   ID 是否在允许集、阶段是否匹配、参数是否落在区间内、
               数量是否补齐、时长是否超限

这不是「规则裁剪后让模型从剩下的里挑」，而是「模型自由决定，越界部分被夹紧」。
区别在于模型的自由度：以前只能输出 ``exercise_id``，现在能决定「这个用户今天
深蹲做 4 组 6 次 70%」这种规则表永远给不出的个体化方案。

两种后端：
    llm           —— 主路径。模型给完整槽位，``PrescriptionBounds.clamp`` 负责夹紧
    deterministic —— 兜底。模型不可用/输出不可解析时按文法采样 + 推荐处方

为什么参数仍然要夹紧而不是全放：合规性必须可证明。区间是由动作类型与阶段
推导的，越界即违规（``PRESCRIPTION_RANGE``），所以模型无论输出什么，最终
计划都落在可行域内 —— 但它在这个域内是真的自由的。
"""
from __future__ import annotations

import random
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from agents.contracts import PHASES, PlanDraft, RiskProfile, Slot
from agents.grammar import RiskGrammar
from agents.prescription import (
    PHASE_COUNT,
    PHASE_MAX_IMPACT,
    is_bodyweight,
    prescribe,
    prescription_bounds,
    phase_impact_limit,
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

    第一轮每种 ``motion_pattern`` 只取一个（池已打乱，所以具体取哪个是随机的），
    第二轮再补满。这样辅助段不会出现「三个弯举」，主项段也不会出现
    「深蹲 + 腿举 + 前蹲」这种同模式重复。
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

    def generate(
        self,
        profile: RiskProfile,
        grammar: RiskGrammar,
        workout_type: str = "full_body",
        seed: Optional[int] = None,
    ) -> PlanDraft:
        if self._llm_plan_fn is not None:
            draft = self._generate_with_llm(profile, grammar, workout_type)
            if draft is not None:
                return draft
        return self._generate_deterministic(profile, grammar, workout_type, seed)

    # ── 候选池构建 ────────────────────────────────────────────────────────
    def _build_pool(
        self,
        profile: RiskProfile,
        grammar: RiskGrammar,
        phase: str,
        used: Sequence[int],
        rng: random.Random,
    ) -> List[int]:
        """按「严格 → 放宽 impact → 放宽阶段」三级构建候选池。"""
        ceiling = profile.impact_ceiling
        stage_cap = min(phase_impact_limit(phase), ceiling)

        strict = [
            eid
            for eid in grammar.candidates(phase, exclude=used, rng=rng)
            if grammar.impact_of(eid) <= stage_cap
        ]
        pool = list(strict)

        # 放宽 ①：阶段内 impact 上限放到档案上限（仍不越过档案）
        if len(pool) < phase_quota(phase):
            pool += [
                eid
                for eid in grammar.candidates(phase, exclude=used, rng=rng)
                if eid not in pool and grammar.impact_of(eid) <= ceiling
            ]

        # 放宽 ②：该阶段候选被档案掏空时，允许借用其它阶段的动作兜底。
        # 注意：仍然只在 allowed_ids 内，且仍受档案上限约束。
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
        """偏好软约束：候选充足时排除不喜欢的，全被讨厌时才妥协。

        规则后端没有模型那样的权衡能力，只能靠这条规则近似：
        明确不想做的动作不进候选池；只有当整个池子都是不喜欢的动作时
        才保留它们（否则阶段会空掉，那是更严重的问题）。
        加这一步是为了让「兴趣」在没接 key 时也留下可观测的差异 ——
        否则关掉模型，用户说了喜欢什么讨厌什么，结果一个字都不会变。
        """
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
        # 宁可本阶段少一个动作，也不塞一个用户明确不想做的动作；
        # 只有当候选全被讨厌时才妥协（否则阶段会空掉，那是更严重的问题）。
        return keep or ranked

    # ── 确定性后端 ────────────────────────────────────────────────────────
    def _generate_deterministic(
        self,
        profile: RiskProfile,
        grammar: RiskGrammar,
        workout_type: str,
        seed: Optional[int] = None,
    ) -> PlanDraft:
        rng = random.Random(seed if seed is not None else hash(profile.profile_hash + workout_type))
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

        return PlanDraft(
            plan_id=f"draft_{uuid.uuid4().hex[:10]}",
            user_id=profile.user_id,
            workout_type=workout_type,
            phases=phases,
            generator="deterministic",
            grammar_version=grammar.version,
            profile_hash=profile.profile_hash,
        )

    # ── LLM 后端（结构化输出）──────────────────────────────────────────────
    def build_request_payload(
        self,
        profile: RiskProfile,
        grammar: RiskGrammar,
        workout_type: str,
    ) -> Dict[str, Any]:
        """发给模型的请求体。

        比 v2 多给了三样东西，因为模型现在要真的做决策：
            1. 每个候选动作的元信息（类型、是否自重、动作模式、冲击）——
               没有这些，模型选动作等于盲选；
            2. 处方区间表 —— 告诉它每个动作能取多少组、多少次、多重；
            3. 时长上限与模式禁忌 —— 来自病历语义的约束。
        仍然不含伤病原文：模型拿到的只有已经被编译成约束的结论。
        """
        ctx = profile.user_context or {}
        prefs = ctx.get("preferences") or {}
        liked = {str(p).strip().lower() for p in (prefs.get("liked_patterns") or [])}
        disliked_patterns = {
            str(p).strip().lower() for p in (prefs.get("disliked_patterns") or [])
        }
        disliked_names = {
            str(p).strip().lower() for p in (prefs.get("disliked_exercises") or [])
        }

        phase_candidates: Dict[str, List[Dict[str, Any]]] = {}
        for phase in PHASES:
            rows: List[Dict[str, Any]] = []
            for eid in grammar.phase_allowed_ids(phase):
                meta = grammar.index.get(eid) or {}
                pattern = str(meta.get("motion_pattern") or "").strip().lower()
                name_zh = str(meta.get("name_zh") or meta.get("name") or "")
                row: Dict[str, Any] = {
                    "exercise_id": eid,
                    "name_zh": name_zh,
                    "type": meta.get("type", ""),
                    "impact": int(meta.get("risk_level", 1)),
                }
                # 只在为 true 时下发：74 行候选里这两项大多为 false，
                # 省略后 payload 少约 3KB，模型侧语义不变（缺省即 false）。
                if is_bodyweight(meta):
                    row["bodyweight"] = True
                if bool(meta.get("is_timed")) or str(meta.get("type")) in {"Stretch", "Isometric"}:
                    row["timed"] = True
                if meta.get("motion_pattern"):
                    row["motion_pattern"] = meta["motion_pattern"]
                # 偏好标记：把「用户喜欢 / 不喜欢」直接标在候选上。
                # 不写进 forbidden —— 不喜欢不是不能做，只是同等条件下让位。
                if (pattern and pattern in disliked_patterns) or name_zh.lower() in disliked_names \
                        or str(meta.get("name", "")).lower() in disliked_names:
                    row["disliked"] = True
                elif pattern and pattern in liked:
                    row["liked"] = True
                rows.append(row)
            phase_candidates[phase] = rows

        payload: Dict[str, Any] = {
            "workout_type": workout_type,
            "fitness_level": profile.fitness_level or "beginner",
            "session_cap_minutes": profile.session_cap_minutes,
            "avoid_patterns": list(profile.avoid_patterns),
            "constraints": {
                "joint_caps": dict(profile.joint_caps),
                "impact_ceiling": profile.impact_ceiling,
                "load_pct_cap": profile.load_pct_cap,
            },
            "phase_targets": {
                phase: {
                    "count": phase_quota(phase),
                    "max_impact": min(
                        phase_impact_limit(phase), profile.impact_ceiling
                    ),
                }
                for phase in PHASES
            },
            "phase_candidates": phase_candidates,
            "prescription_rules": grammar.prescription_rules(),
            "grammar_version": grammar.version,
            "profile_hash": profile.profile_hash,
        }

        # 用户需求与偏好：只在有值时下发，避免空字段占 token。
        # 这些是「软」信息 —— 影响选哪个动作、剂量偏保守还是激进，
        # 但不改变任何约束边界（禁忌与区间照旧由规则夹紧）。
        optional: Dict[str, Any] = {
            "fitness_goal": ctx.get("fitness_goal"),
            "training_frequency": ctx.get("training_frequency"),
            "available_equipment": ctx.get("available_equipment") or None,
            "preferences": ctx.get("preferences") or None,
            "user_request": ctx.get("query") or None,
            "progression_note": profile.progression_note or None,
            "capacity_note": profile.capacity_note or None,
        }
        for key, value in optional.items():
            if value:
                payload[key] = value
        return payload

    def _generate_with_llm(
        self,
        profile: RiskProfile,
        grammar: RiskGrammar,
        workout_type: str,
    ) -> Optional[PlanDraft]:
        payload = self.build_request_payload(profile, grammar, workout_type)
        schema = grammar.plan_schema()
        try:
            raw = self._llm_plan_fn(payload, schema)  # type: ignore[misc]
        except Exception:
            return None
        if not isinstance(raw, dict):
            return None

        phases: Dict[str, List[Slot]] = {}
        rejected: List[int] = []
        adjusted = 0
        used: List[int] = []

        for phase in PHASES:
            slots: List[Slot] = []
            for item in raw.get(phase, []) or []:
                if not isinstance(item, dict) or "exercise_id" not in item:
                    continue
                try:
                    eid = int(item["exercise_id"])
                except (TypeError, ValueError):
                    continue
                # 兜底层 ①：ID 白名单。enum 被绕过（模型返回提示词里的旧 ID、
                # 或干脆编一个）时在这里挡回，禁忌 ID 绝不进入 draft。
                if not grammar.is_allowed(eid):
                    rejected.append(eid)
                    continue
                # 兜底层 ②：阶段归属。把拉伸塞进主项段，即使 ID 合法也挡回。
                if not grammar.phase_matches(eid, phase):
                    rejected.append(eid)
                    continue
                if eid in used:
                    # 全局去重：同一个动作在一节课里只出现一次
                    rejected.append(eid)
                    continue

                meta = grammar.index.get(eid) or {}
                bounds = grammar.bounds(phase, eid)
                slot, was_clamped = self._build_slot(
                    phase, eid, item, bounds, meta, profile
                )
                if was_clamped:
                    adjusted += 1
                slots.append(slot)
                used.append(eid)

            # 兜底层 ③：数量补齐。模型少给了就按文法补位，多给了保留
            # （上限由 phase_quota 控制，避免一节课堆 12 个动作）。
            target = phase_quota(phase)
            if len(slots) < target:
                slots.extend(
                    self._top_up(phase, grammar, profile, used, target - len(slots))
                )
                for s in slots:
                    if s.exercise_id not in used:
                        used.append(s.exercise_id)
            phases[phase] = slots[: max(target, 1)]

        return PlanDraft(
            plan_id=f"draft_{uuid.uuid4().hex[:10]}",
            user_id=profile.user_id,
            workout_type=workout_type,
            phases=phases,
            generator="llm",
            grammar_version=grammar.version,
            prompt_version=PLAN_GEN_PROMPT_VERSION,
            profile_hash=profile.profile_hash,
            rejected_ids=tuple(rejected),
            adjusted_slots=adjusted,
        )

    def _build_slot(
        self,
        phase: str,
        eid: int,
        item: Dict[str, Any],
        bounds: Any,
        meta: Dict[str, Any],
        profile: RiskProfile,
    ) -> Tuple[Slot, bool]:
        """把模型给的一条动作转成合法槽位。

        参数缺失时退回处方推荐值（保证计划可用）；参数越界时夹紧
        （保证计划合法）。两种情况的差别在于：缺失是「模型没给」，越界是
        「模型给了但超范围」，后者才计入 ``adjusted_slots``。
        """
        clamped = False
        if "sets" in item and "reps" in item:
            sets, reps, load, clamped = bounds.clamp(
                item.get("sets"), item.get("reps"), item.get("load_pct")
            )
        else:
            pres = prescribe(phase, meta, profile.load_pct_cap)
            sets, reps, load = pres.sets, pres.reps, pres.load_pct
            clamped = True  # 模型未提供参数，视为未发挥自由度

        rest = item.get("rest_seconds")
        try:
            rest_val: Optional[int] = int(rest) if rest is not None else None
        except (TypeError, ValueError):
            rest_val = None
        if rest_val is not None:
            if rest_val < 5 or rest_val > 300:
                rest_val = min(max(rest_val, 5), 300)
                clamped = True

        note = str(item.get("note") or "").strip()[:120]

        return (
            Slot(
                exercise_id=eid,
                sets=sets,
                reps=reps,
                load_pct=load,
                impact=int(meta.get("risk_level", 1)),
                note=note,
                rest_seconds=rest_val,
            ),
            clamped,
        )

    def _top_up(
        self,
        phase: str,
        grammar: RiskGrammar,
        profile: RiskProfile,
        used: Sequence[int],
        need: int,
    ) -> List[Slot]:
        """模型给少了时按文法补位 —— 补位也走区间推导，不会塞进越界参数。"""
        out: List[Slot] = []
        taken = list(used)
        ceiling = profile.impact_ceiling
        stage_cap = min(phase_impact_limit(phase), ceiling)
        for allow_fallback in (False, True):
            if len(out) >= need:
                break
            for eid in grammar.candidates(
                phase, exclude=taken, allow_fallback=allow_fallback
            ):
                if len(out) >= need:
                    break
                if grammar.impact_of(eid) > (stage_cap if not allow_fallback else ceiling):
                    continue
                meta = grammar.index.get(eid) or {}
                pres = prescribe(phase, meta, profile.load_pct_cap)
                out.append(
                    Slot(
                        exercise_id=eid,
                        sets=pres.sets,
                        reps=pres.reps,
                        load_pct=pres.load_pct,
                        impact=grammar.impact_of(eid),
                    )
                )
                taken.append(eid)
        return out


def describe_phases(draft: PlanDraft) -> str:
    """把草稿渲染成人看的文本 —— 只在管线最外层调用，不参与 Agent 通信。"""
    lines = [f"plan_id={draft.plan_id} generator={draft.generator}"]
    for phase in PHASES:
        slots = draft.phases.get(phase, [])
        lines.append(f"  {phase}: " + ", ".join(str(s.exercise_id) for s in slots))
    return "\n".join(lines)


__all__ = ["PlanAgent", "PHASE_PRESCRIPTION", "describe_phases", "pick_diverse"]
