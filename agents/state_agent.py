"""Agent 1 —— 身体状态评估：产出**风险报告**。

职责边界：
    输入：完整用户档案（含病历原文）、可选训练反馈、本次需求
    输出：``RiskProfile``，其中 ``risk_report`` 是对外的那份报告

三阶段语义（v4）：
    阶段一 读身体情况 → 风险报告（判断：能不能练、哪里不能练、怎么练）
    阶段二 读报告 + 需求 → 计划
    阶段三 读计划 + 报告 → 是否合格

报告与约束是**同一判断的两种形态**，不重复计算：

    risk_report      给人读、给下游 Agent 读的判断
                     （整体风险等级 / 能否开练 / 每条伤情的功能影响与禁忌 /
                       剂量口径 / 要盯的信号）
    profile 字段     同一判断的机器可执行投影
                     （allowed_ids / forbidden_reasons / joint_caps /
                       impact_ceiling / load_pct_cap / avoid_patterns / 时长上限）

两者都由这里产出，所以不会出现「报告说能做、约束说不能做」的分裂。规则先给
一份基线报告（``source="baseline"``），能连模型时由模型改写或补全
（``source="agent"``）；模型一旦缺席，报告退回基线，但**形状不变** ——
下游两个 Agent 永远拿得到一份报告，不必到处判空。

LLM 通道对**约束**仍然只能更严（提议放宽会被静默丢弃并计入 ``llm_status``）。
对**报告**则允许改写判断：报告是意见，约束才是可执行的下限 —— 意见可以
不同，下限不能松动。
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from agents.contracts import RuleSpec, RiskProfile
from agents.grammar import joint_cap_for_severity
from agents.prompts import STATE_RISK_PROMPT_VERSION

# 与 RiskAssessmentEngine 保持一致的阻断阈值
HIGH_THRESHOLD = 3
MEDIUM_THRESHOLD = 4
LOW_THRESHOLD = 5

SEVERITY_THRESHOLD: Dict[str, int] = {
    "high": HIGH_THRESHOLD,
    "medium": MEDIUM_THRESHOLD,
    "low": LOW_THRESHOLD,
}

EnhanceFn = Callable[[Dict[str, Any]], Dict[str, Any]]

# 风险报告的两个枚举维度 —— 模型给的自由措辞一律归一到这里
RISK_LEVELS: Tuple[str, ...] = ("low", "moderate", "high", "very_high")
CLEARANCES: Tuple[str, ...] = ("cleared", "conditional", "not_cleared")

_SEVERITY_RANK: Dict[str, int] = {"low": 1, "medium": 2, "high": 3}

# 报告是给用户看的，关节名不能直接甩英文；未收录的原样保留（不猜）
_JOINT_ZH: Dict[str, str] = {
    "knee": "膝", "back": "腰背", "lower_back": "下背", "shoulder": "肩",
    "ankle": "踝", "hip": "髋", "elbow": "肘", "wrist": "腕", "neck": "颈",
}


class StateRiskAgent:
    """状态与风险分析 Agent。"""

    name = "state_risk"

    def __init__(
        self,
        exercise_db: Sequence[Dict[str, Any]],
        llm_enhance_fn: Optional[EnhanceFn] = None,
    ) -> None:
        self.exercise_db = [ex for ex in exercise_db if "id" in ex]
        self._llm_enhance_fn = llm_enhance_fn

    # ── 主入口 ────────────────────────────────────────────────────────────
    def analyze(
        self,
        user_profile: Dict[str, Any],
        feedback: Optional[Dict[str, Any]] = None,
        workout_type: str = "full_body",
        query: Optional[str] = None,
    ) -> RiskProfile:
        """规则算基线 → 组装上下文 → 基线风险报告 →（可选）模型改写报告。

        ``workout_type`` 与 ``query`` 会一并进入上下文：同样是膝伤，
        「今天练腿」和「今天练上肢」的风险权重完全不同，模型需要知道
        这一次要练什么，而不只是知道用户有什么伤。
        """
        base = self._analyze_rules(user_profile, feedback)
        base = replace(
            base,
            user_context=self._build_user_context(user_profile, workout_type, query),
        )
        # 报告在调模型**之前**就要成型：模型失败时下游仍拿得到一份完整报告
        base = replace(base, risk_report=self._baseline_report(base))
        if self._llm_enhance_fn is None:
            return self._finalize(replace(base, llm_status="skipped"))
        return self._finalize(self._enhance(base, user_profile, feedback))

    @staticmethod
    def _finalize(profile: RiskProfile) -> RiskProfile:
        """允许集与禁忌集必须互斥；不成立说明编译出错，应立即失败。"""
        overlap = set(profile.allowed_ids) & set(profile.forbidden_reasons)
        if overlap:
            raise AssertionError(f"允许集与禁忌集重叠: {sorted(overlap)[:5]}")
        return profile

    # ── 风险报告 ──────────────────────────────────────────────────────────
    @staticmethod
    def _baseline_report(profile: RiskProfile) -> Dict[str, Any]:
        """规则算出的基线报告 —— 报告的**形状**由它定义。

        规则能给的是「有哪几处伤、各自什么程度、对应多严的冲击上限」，
        给不了「这个动作为什么不行」「这周该练多少」。后者留空由模型补，
        而不是编一段模板话术糊过去 —— 空的字段在审查端是「未评估」，
        编出来的字段是「错误的安全感」。
        """
        ctx = profile.user_context or {}
        history = [h for h in (ctx.get("medical_history") or []) if isinstance(h, dict)]

        injuries: List[Dict[str, Any]] = []
        for item in history[:6]:
            joint = str(item.get("location") or "").strip().lower()
            injuries.append(
                {
                    "location": joint or "unspecified",
                    "condition": str(item.get("condition") or "")[:80],
                    "severity": str(item.get("severity") or "").lower(),
                    # 规则读不懂叙述，但病历里的 notes / pain_trigger 至少能原样带出
                    "functional_impact": str(
                        item.get("notes") or item.get("pain_trigger") or ""
                    )[:160],
                    "contraindications": [],
                    "safe_substitutes": [],
                    "impact_cap": profile.joint_caps.get(joint),
                    "load_pct_ceiling": profile.load_pct_cap,
                    "source": "baseline",
                }
            )

        worst = max(
            (_SEVERITY_RANK.get(str(h.get("severity") or "").lower(), 0) for h in history),
            default=0,
        )
        risk_level = {3: "high", 2: "moderate"}.get(worst, "low")

        if not profile.allowed_ids:
            clearance = "not_cleared"
        elif profile.joint_caps or profile.avoid_patterns or profile.forbidden_reasons:
            clearance = "conditional"
        else:
            clearance = "cleared"

        if injuries:
            joints = "、".join(
                sorted({_JOINT_ZH.get(i["location"], i["location"]) for i in injuries})
            )
            summary = (
                f"规则基线：{len(injuries)} 处伤情（{joints}），"
                f"冲击等级上限 {profile.impact_ceiling}"
            )
        else:
            summary = f"规则基线：未录入伤情，冲击等级上限 {profile.impact_ceiling}"

        # 只写规则能负责的那句：出现疼痛就停。不编剂量口径。
        watch_items = [
            f"训练中{_JOINT_ZH.get(joint, joint)}部出现疼痛立即停止该动作"
            for joint in sorted(profile.joint_caps)[:4]
        ]

        return {
            "source": "baseline",
            "overall": {
                "risk_level": risk_level,
                "clearance": clearance,
                "summary": summary[:200],
            },
            "injuries": injuries,
            "dose_guidance": {},
            "watch_items": watch_items,
            "rationale": "",
        }

    @classmethod
    def _merge_report(
        cls,
        base_report: Dict[str, Any],
        raw: Dict[str, Any],
        profile: RiskProfile,
    ) -> Tuple[Dict[str, Any], bool]:
        """把模型给的报告并入基线报告，返回 (报告, 是否改写了)。

        两处刻意不对称：
        - ``clearance`` / ``risk_level`` 只能**更保守**。模型可以比基线严，
          不能比基线松 —— 松的那一侧由约束兜着，报告若比约束乐观就自相矛盾。
        - ``injuries`` / ``dose_guidance`` / ``watch_items`` 允许整体替换，
          这部分正是规则算不出来的，模型说什么就是什么（逐条做类型收敛）。
        """
        overall_raw = raw.get("overall") if isinstance(raw.get("overall"), dict) else {}
        level = _pick_enum(overall_raw.get("risk_level"), RISK_LEVELS)
        clearance = _pick_enum(overall_raw.get("clearance"), CLEARANCES)
        summary = str(overall_raw.get("summary") or "").strip()[:200]

        injuries = cls._normalize_injuries(raw.get("injuries"), profile)
        dose = cls._normalize_dose(raw.get("dose_guidance"))
        watch = [
            str(w).strip()[:80]
            for w in (raw.get("watch_items") or [])
            if str(w).strip()
        ][:5]

        if not (level or clearance or summary or injuries or dose or watch):
            return base_report, False

        base_overall = dict(base_report.get("overall") or {})
        return (
            {
                "source": "agent",
                "overall": {
                    # 取更保守的一侧
                    "risk_level": _stricter(base_overall.get("risk_level"), level, RISK_LEVELS),
                    "clearance": _stricter(
                        base_overall.get("clearance"), clearance, CLEARANCES
                    ),
                    "summary": summary or base_overall.get("summary", ""),
                },
                "injuries": injuries or list(base_report.get("injuries") or []),
                "dose_guidance": dose or dict(base_report.get("dose_guidance") or {}),
                "watch_items": watch or list(base_report.get("watch_items") or []),
                "rationale": str(raw.get("rationale") or "")[:400],
            },
            True,
        )

    @staticmethod
    def _normalize_injuries(
        raw_injuries: Any, profile: RiskProfile
    ) -> List[Dict[str, Any]]:
        """逐条收敛：只保留约定字段，上限取「模型建议」与「机器约束」中更严的。"""
        if not isinstance(raw_injuries, list):
            return []
        out: List[Dict[str, Any]] = []
        for item in raw_injuries[:6]:
            if not isinstance(item, dict):
                continue
            location = str(item.get("location") or "").strip().lower()
            cap = _as_optional_int(item.get("impact_cap"))
            profile_cap = profile.joint_caps.get(location)
            if cap is not None and profile_cap is not None:
                cap = min(cap, profile_cap)
            elif cap is None:
                cap = profile_cap
            ceiling = _as_optional_int(item.get("load_pct_ceiling"))
            if ceiling is None:
                ceiling = profile.load_pct_cap
            elif profile.load_pct_cap is not None:
                ceiling = min(ceiling, profile.load_pct_cap)

            out.append(
                {
                    "location": location or "unspecified",
                    "condition": str(item.get("condition") or "")[:80],
                    "severity": str(item.get("severity") or "").lower()[:20],
                    "functional_impact": str(item.get("functional_impact") or "")[:160],
                    "contraindications": [
                        str(c).strip()[:80]
                        for c in (item.get("contraindications") or [])
                        if str(c).strip()
                    ][:6],
                    "safe_substitutes": [
                        str(c).strip()[:80]
                        for c in (item.get("safe_substitutes") or [])
                        if str(c).strip()
                    ][:6],
                    "impact_cap": cap,
                    "load_pct_ceiling": ceiling,
                    "source": "agent",
                }
            )
        return out

    @staticmethod
    def _normalize_dose(raw_dose: Any) -> Dict[str, str]:
        if not isinstance(raw_dose, dict):
            return {}
        out: Dict[str, str] = {}
        for key in ("volume", "intensity", "rest", "progression"):
            value = str(raw_dose.get(key) or "").strip()[:120]
            if value:
                out[key] = value
        return out

    # ── 规则后端（唯一的下限来源）─────────────────────────────────────────
    def _analyze_rules(
        self,
        user_profile: Dict[str, Any],
        feedback: Optional[Dict[str, Any]] = None,
    ) -> RiskProfile:
        user_id = str(user_profile.get("user_id", "unknown"))
        joint_severity = self._injury_map(user_profile)

        # ① 器械不可达 —— 硬约束，与伤情禁忌同级
        #    「没有杠铃」和「膝伤不能深蹲」在执行层面是同一件事：动作做不了。
        #    放在规则层而不是交给模型，因为这是可判定事实，不需要推理。
        equipment = self._build_equipment_set(user_profile.get("available_equipment"))
        gear_blocked: Dict[int, str] = {}
        if equipment is not None:
            for ex in self.exercise_db:
                need = [str(e).lower() for e in (ex.get("required_equipment") or []) if e]
                missing = [e for e in need if e not in equipment]
                if missing:
                    gear_blocked[int(ex["id"])] = f"EQUIPMENT_MISSING:{missing[0]}"

        forbidden: Dict[int, str] = dict(gear_blocked)
        for ex in self.exercise_db:
            eid = int(ex["id"])
            risk_level = int(ex.get("risk_level", 1))
            for joint, severity in joint_severity.items():
                if joint not in [str(j).lower() for j in ex.get("involved_joints", [])]:
                    continue
                threshold = SEVERITY_THRESHOLD.get(severity, 5)
                if risk_level >= threshold:
                    # 伤情原因覆盖器械原因：前者更需要被用户看到
                    forbidden[eid] = f"SEVERITY_{severity.upper()}:{joint}"
                    break

        joint_caps = {
            joint: joint_cap_for_severity(severity)
            for joint, severity in joint_severity.items()
        }
        allowed_ids = tuple(
            int(ex["id"]) for ex in self.exercise_db if int(ex["id"]) not in forbidden
        )

        impact_ceiling, load_pct_cap, dynamic_rules = self._dynamic_limits(feedback)

        rules: List[RuleSpec] = []
        for joint, severity in sorted(joint_severity.items()):
            rules.append(
                RuleSpec(
                    rule_id=f"joint_cap:{joint}",
                    kind="joint_cap",
                    subject=joint,
                    threshold=joint_caps[joint],
                    source=f"severity={severity}",
                )
            )
        for eid in sorted(forbidden):
            rules.append(
                RuleSpec(
                    rule_id=f"forbidden:{eid}",
                    kind="forbidden_id",
                    subject=str(eid),
                    threshold=0,
                    source=forbidden[eid],
                )
            )
        rules.append(
            RuleSpec("impact_ceiling", "impact_ceiling", "*", impact_ceiling, "static")
        )
        if gear_blocked:
            rules.append(
                RuleSpec("equipment_filter", "equipment", "*", len(gear_blocked), "static:gear")
            )
        rules.extend(dynamic_rules)

        return RiskProfile(
            user_id=user_id,
            allowed_ids=allowed_ids,
            forbidden_reasons=forbidden,
            joint_caps=joint_caps,
            impact_ceiling=impact_ceiling,
            load_pct_cap=load_pct_cap,
            rules=tuple(rules),
            fitness_level=str(user_profile.get("fitness_level") or ""),
        )

    # ── LLM 增强 ──────────────────────────────────────────────────────────
    def _enhance(
        self,
        base: RiskProfile,
        user_profile: Dict[str, Any],
        feedback: Optional[Dict[str, Any]],
    ) -> RiskProfile:
        # 只有在「没有任何可读文本」时才跳过调用。
        # 注意这里不再用 joint_caps 作条件：病历可能只写在 notes 里、结构化字段
        # 没填（location/severity 缺失），那种情况规则算不出 joint_caps，
        # 但恰恰是模型唯一能救的场景。
        has_notes = any(
            str(item.get("notes") or "").strip()
            for item in (user_profile.get("medical_history") or [])
        )
        # 本次需求原话与偏好备注同样可能带症状或时间限制
        # （「今天只有半小时」「最近腰有点紧」），都算可读文本。
        ctx = base.user_context or {}
        has_request_text = bool(str(ctx.get("query") or "").strip())
        has_pref_text = bool(str((ctx.get("preferences") or {}).get("notes") or "").strip())
        if not base.joint_caps and not feedback and not has_notes \
                and not has_request_text and not has_pref_text:
            return replace(base, llm_status="empty")

        payload = self._build_enhance_payload(base, user_profile, feedback)
        try:
            raw = self._llm_enhance_fn(payload)  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001 - 任何失败都必须退回规则结果
            return replace(
                base,
                llm_status="error",
                llm_rationale=f"LLM 调用失败，已退回规则结果：{exc}"[:240],
                llm_prompt_version=STATE_RISK_PROMPT_VERSION,
            )
        if not isinstance(raw, dict):
            return replace(
                base,
                llm_status="error",
                llm_rationale="LLM 返回非对象结构，已退回规则结果",
                llm_prompt_version=STATE_RISK_PROMPT_VERSION,
            )
        return self._merge_enhancement(base, raw)

    def _build_enhance_payload(
        self,
        base: RiskProfile,
        user_profile: Dict[str, Any],
        feedback: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        injured = set(base.joint_caps)
        allowed_set = set(base.allowed_ids)

        def _row(ex: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "exercise_id": int(ex["id"]),
                "name": ex.get("name", ""),
                "name_zh": ex.get("name_zh") or "",
                "type": ex.get("type", ""),
                "motion_pattern": ex.get("motion_pattern", ""),
                "involved_joints": [str(j).lower() for j in ex.get("involved_joints", [])],
                "risk_level": int(ex.get("risk_level", 1)),
            }

        # 有明确伤情时只发「涉及受伤关节」的动作 —— 压低 token，也避免模型
        # 在无关动作上乱开枪。只有当结构化字段缺失（只写了 notes）时才发全量，
        # 因为此时规则没有任何线索，需要模型自己从文本里判断。
        if injured:
            scoped = [
                _row(ex)
                for ex in self.exercise_db
                if int(ex["id"]) in allowed_set
                and injured & {str(j).lower() for j in ex.get("involved_joints", [])}
            ]
        else:
            scoped = [_row(ex) for ex in self.exercise_db if int(ex["id"]) in allowed_set]

        # 动作模式词表：模型只能从这里挑 avoid_patterns，否则下游无法消费
        patterns = sorted(
            {
                str(ex.get("motion_pattern") or "").lower()
                for ex in self.exercise_db
                if ex.get("motion_pattern")
            }
        )

        ctx = base.user_context or {}
        return {
            # 完整原始档案 —— 不再只挑四个字段。
            # 目标（fitness_goal）、器械、偏好、本次需求都会影响风险判断：
            # 「想练力量」会把负荷顶到上限，「没有杠铃」和「膝伤」一样是硬约束。
            "user_profile": {
                "user_id": user_profile.get("user_id"),
                "basic_info": dict(ctx.get("basic_info") or {}),
                "fitness_level": user_profile.get("fitness_level"),
                "fitness_goal": ctx.get("fitness_goal"),
                "training_frequency": ctx.get("training_frequency"),
                "available_equipment": ctx.get("available_equipment") or [],
                "preferences": ctx.get("preferences") or {},
                # 病历全文：location / condition / severity / pain_trigger / notes
                "medical_history": user_profile.get("medical_history") or [],
            },
            "current_request": {
                "workout_type": ctx.get("workout_type") or "full_body",
                "query": ctx.get("query") or "",
            },
            "recent_feedback": feedback or {},
            "rule_engine_output": {
                "joint_caps": dict(base.joint_caps),
                "impact_ceiling": base.impact_ceiling,
                "load_pct_cap": base.load_pct_cap,
                "forbidden": [
                    {"exercise_id": eid, "reason": reason}
                    for eid, reason in sorted(base.forbidden_reasons.items())
                ],
                "equipment_filtered": sum(
                    1 for r in base.forbidden_reasons.values() if r.startswith("EQUIPMENT_MISSING")
                ),
            },
            "allowed_exercises": scoped,
            "available_motion_patterns": patterns,
        }

    def _merge_enhancement(
        self, base: RiskProfile, raw: Dict[str, Any]
    ) -> RiskProfile:
        """把模型输出拆成两半：报告并入报告，约束只取更严的一方。

        模型可以只交约束、也可以只交报告 —— 两种都接受，所以先看有没有
        ``constraints`` 这一层包装，没有就按扁平字段读（兼容旧输出）。
        """
        index = {int(ex["id"]): ex for ex in self.exercise_db}
        allowed_set = set(base.allowed_ids)
        constraints = (
            raw["constraints"]
            if isinstance(raw.get("constraints"), dict)
            else raw
        )

        added: Dict[int, str] = {}
        for item in constraints.get("additional_forbidden") or []:
            if not isinstance(item, dict):
                continue
            try:
                eid = int(item.get("exercise_id"))
            except (TypeError, ValueError):
                continue
            # 只接受「当前允许且存在于知识库」的 ID。
            # 已在禁忌集里的不能再被"追加"，更不可能被移除。
            if eid not in allowed_set or eid not in index:
                continue
            reason = str(item.get("reason") or "LLM 追加禁忌")
            added[eid] = f"LLM_APPENDED:{reason}"[:160]

        joint_caps = dict(base.joint_caps)
        for joint, cap in (constraints.get("additional_joint_caps") or {}).items():
            key = str(joint).lower()
            try:
                value = int(cap)
            except (TypeError, ValueError):
                continue
            # 只允许收窄已知关节的上限；不新建关节、不放宽
            if key in joint_caps and value < joint_caps[key]:
                joint_caps[key] = value

        ceiling = base.impact_ceiling
        override = constraints.get("impact_ceiling_override")
        if isinstance(override, (int, float)) and not isinstance(override, bool):
            candidate = int(override)
            if 1 <= candidate < ceiling:
                ceiling = candidate

        load_cap = base.load_pct_cap
        load_override = constraints.get("load_pct_cap_override")
        if isinstance(load_override, (int, float)) and not isinstance(load_override, bool):
            candidate = int(load_override)
            if 0 <= candidate <= 100 and (load_cap is None or candidate < load_cap):
                load_cap = candidate

        rationale = str(raw.get("rationale") or "")[:400]

        # 模式禁忌：模型只能从动作库真实存在的模式里选，否则下游过滤不掉
        vocab = {
            str(ex.get("motion_pattern") or "").lower()
            for ex in self.exercise_db
            if ex.get("motion_pattern")
        }
        avoid: List[str] = []
        for p in constraints.get("avoid_patterns") or []:
            key = str(p).strip().lower()
            if key in vocab and key not in avoid:
                avoid.append(key)

        session_cap: Optional[int] = None
        raw_cap = constraints.get("session_cap_minutes")
        if isinstance(raw_cap, (int, float)) and not isinstance(raw_cap, bool):
            session_cap = min(max(int(raw_cap), 15), 120)

        # 这两句属于报告（判断），不属于约束；模型若放进 constraints 也认
        progression = str(
            raw.get("progression_note") or constraints.get("progression_note") or ""
        ).strip()[:200]
        capacity = str(
            raw.get("capacity_note") or constraints.get("capacity_note") or ""
        ).strip()[:200]

        constraints_touched = bool(
            added
            or joint_caps != base.joint_caps
            or ceiling != base.impact_ceiling
            or load_cap != base.load_pct_cap
            or avoid
            or session_cap is not None
            or progression
            or capacity
        )

        forbidden_reasons = dict(base.forbidden_reasons)
        forbidden_reasons.update(added)
        allowed_ids = tuple(i for i in base.allowed_ids if i not in added)

        rules: List[RuleSpec] = list(base.rules)
        for eid in sorted(added):
            rules.append(RuleSpec(f"llm_forbidden:{eid}", "forbidden_id", str(eid), 0, "llm:medical_text"))
        for joint in sorted(joint_caps):
            if joint in base.joint_caps and joint_caps[joint] != base.joint_caps[joint]:
                rules.append(
                    RuleSpec(f"llm_joint_cap:{joint}", "joint_cap", joint, joint_caps[joint], "llm:medical_text")
                )
        if ceiling != base.impact_ceiling:
            rules.append(RuleSpec("llm_impact_ceiling", "impact_ceiling", "*", ceiling, "llm:feedback"))
        if load_cap != base.load_pct_cap:
            rules.append(RuleSpec("llm_load_pct", "load_pct", "*", load_cap or 0, "llm:feedback"))
        for p in avoid:
            rules.append(
                RuleSpec(f"llm_avoid_pattern:{p}", "avoid_pattern", p, 0, "llm:medical_text")
            )
        if session_cap is not None:
            rules.append(
                RuleSpec("llm_session_cap", "session_cap", "*", session_cap, "llm:feedback")
            )

        # profile_hash 必须重算：约束集变了，旧 hash 会让下游的
        # STALE_PROFILE 检查失去意义。
        merged = RiskProfile(
            user_id=base.user_id,
            allowed_ids=allowed_ids,
            forbidden_reasons=forbidden_reasons,
            joint_caps=joint_caps,
            impact_ceiling=ceiling,
            load_pct_cap=load_cap,
            rules=tuple(rules),
            fitness_level=base.fitness_level,
            llm_forbidden=tuple(added),
            llm_joint_caps={j: v for j, v in joint_caps.items() if base.joint_caps.get(j) != v},
            llm_rationale=rationale,
            llm_status="applied",
            llm_prompt_version=STATE_RISK_PROMPT_VERSION,
            avoid_patterns=tuple(avoid),
            session_cap_minutes=session_cap,
            progression_note=progression,
            capacity_note=capacity,
            user_context=dict(base.user_context or {}),
            risk_report=dict(base.risk_report or {}),
        )

        # 报告在约束合并**之后**归一 —— injuries 里的上限要取最终值，
        # 否则报告会说「冲击上限 3」而约束已经是 2。
        report, report_touched = self._merge_report(merged.risk_report, raw, merged)
        if not constraints_touched and not report_touched:
            return replace(
                merged,
                llm_status="empty",
                llm_rationale=rationale,
                llm_prompt_version=STATE_RISK_PROMPT_VERSION,
            )
        return replace(merged, risk_report=report)

    # ── 内部 ──────────────────────────────────────────────────────────────
    @staticmethod
    def _build_equipment_set(available: Optional[Sequence[Any]]) -> Optional[set]:
        """把用户器械归一成查表集合。

        ``None`` 表示「没填 → 不限制」（与 risk_engine 语义一致）；
        自重永远可用，否则没列 bodyweight 的用户会被判成连俯卧撑都做不了。
        """
        if not available:
            return None
        gear = {str(e).strip().lower() for e in available if str(e).strip()}
        if not gear:
            return None
        gear.add("bodyweight")
        return gear

    @staticmethod
    def _build_user_context(
        user_profile: Dict[str, Any],
        workout_type: str,
        query: Optional[str],
    ) -> Dict[str, Any]:
        """组装透传给下游的完整用户上下文（不含任何约束判断）。

        这里刻意把**原始输入全部保留**：目标、频率、器械、偏好、本次需求原话。
        之前只挑了四个字段下发，导致「没有杠铃」和「想练力量」这两件
        直接决定处方的信息在 Agent 之间整段丢失。
        """
        prefs = user_profile.get("preferences") or {}
        if hasattr(prefs, "model_dump"):
            prefs = prefs.model_dump()
        if not isinstance(prefs, dict):
            prefs = {}

        def _clean_list(value: Any) -> List[str]:
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, (list, tuple)):
                return []
            return [str(v).strip() for v in value if str(v).strip()]

        context: Dict[str, Any] = {
            "basic_info": dict(user_profile.get("basic_info") or {}),
            "fitness_level": str(user_profile.get("fitness_level") or ""),
            "fitness_goal": user_profile.get("fitness_goal") or None,
            "training_frequency": user_profile.get("training_frequency") or None,
            "available_equipment": _clean_list(user_profile.get("available_equipment")),
            "workout_type": workout_type,
            "query": str(query or "").strip(),
            # 病历原文一并透传：生成端要判断「这条基线禁忌是否适用于本次训练」，
            # 审查端要独立复核，两边都不能只看到被编译过的结论。
            "medical_history": [
                {k: item.get(k) for k in ("location", "condition", "severity", "pain_trigger", "notes") if item.get(k)}
                for item in (user_profile.get("medical_history") or [])
                if isinstance(item, dict)
            ],
        }

        cleaned_prefs: Dict[str, Any] = {}
        for key in ("liked_patterns", "disliked_patterns", "disliked_exercises"):
            values = _clean_list(prefs.get(key))
            if values:
                cleaned_prefs[key] = values
        note = str(prefs.get("notes") or "").strip()
        if note:
            cleaned_prefs["notes"] = note
        if cleaned_prefs:
            context["preferences"] = cleaned_prefs
        return context

    @staticmethod
    def _injury_map(user_profile: Dict[str, Any]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for item in user_profile.get("medical_history") or []:
            joint = str(item.get("location", "")).strip().lower()
            severity = str(item.get("severity", "")).strip().lower()
            if not joint or not severity:
                continue
            # 同一关节多次受伤时取更严重的一档
            prev = out.get(joint)
            if prev is None or _rank(severity) > _rank(prev):
                out[joint] = severity
        return out

    @staticmethod
    def _dynamic_limits(
        feedback: Optional[Dict[str, Any]]
    ) -> Tuple[int, Optional[int], List[RuleSpec]]:
        """把训练反馈翻译成强度约束。无反馈时给最宽松值。"""
        if not feedback:
            return 5, None, []

        rules: List[RuleSpec] = []
        ceiling = 5
        load_cap: Optional[int] = None

        pain = feedback.get("pain_feedback") or {}
        if pain.get("has_pain"):
            ceiling = 3
            load_cap = 60
            rules.append(RuleSpec("pain_ceiling", "impact_ceiling", "*", ceiling, "feedback:pain"))
            rules.append(RuleSpec("pain_load", "load_pct", "*", load_cap, "feedback:pain"))

        rpe = feedback.get("rpe")
        if isinstance(rpe, (int, float)) and rpe >= 8:
            if load_cap is None or load_cap > 70:
                load_cap = 70
            rules.append(RuleSpec("rpe_load", "load_pct", "*", 70, f"feedback:rpe={rpe}"))

        completion = feedback.get("completion_rate")
        if isinstance(completion, (int, float)) and completion < 0.6:
            if load_cap is None or load_cap > 70:
                load_cap = 70
            rules.append(
                RuleSpec("low_completion_load", "load_pct", "*", 70, f"feedback:completion={completion}")
            )

        return ceiling, load_cap, rules


def _rank(severity: str) -> int:
    return {"low": 1, "medium": 2, "high": 3}.get(severity, 0)


def _pick_enum(value: Any, allowed: Sequence[str]) -> str:
    """模型爱写 "Moderate"、"very-high"、"高" —— 只认白名单内的归一值。"""
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in allowed else ""


def _stricter(base_value: Any, new_value: str, order: Sequence[str]) -> str:
    """两档取更保守的一侧：报告的结论不允许比机器约束更乐观。"""
    base_text = str(base_value or "").strip().lower()
    if not new_value:
        return base_text
    if base_text not in order:
        return new_value
    return order[max(order.index(base_text), order.index(new_value))]


def _as_optional_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

