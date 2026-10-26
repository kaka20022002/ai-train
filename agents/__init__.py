"""多 Agent 运动计划生成管线。

设计约束（与论文口径一致）：

1. **结构化边界**：Agent 之间只传 dataclass / 纯 JSON 字段
   （``{exercise_id, sets, reps, load_pct, impact}``），不传自然语言。
   自然语言只允许出现在最外层（用户输入、最终展示），不进入 Agent 通道。
2. **约束解码**：风险档案在进入生成阶段前被编译成 ``RiskGrammar``，
   候选集被硬性裁剪；同时向支持结构化输出的模型下发以允许 ID 为
   enum 的 JSON Schema，使禁忌动作在解码层面无法被生成。

模块划分：
    contracts      数据契约（唯一跨 Agent 传输格式）
    grammar        风险条件约束解码（编译 + 校验 + 候选采样）
    prescription   处方推导（动作类型 × 阶段 → 组数/次数/强度）
    state_agent    状态与风险分析 Agent
    plan_agent     计划生成 Agent
    safety_agent   计划安全评估 Agent
    pipeline       编排与审计
    render         结构化产物 → 对外 JSON
"""

from agents.contracts import (
    PlanDraft,
    RiskProfile,
    SafetyReport,
    Slot,
    Violation,
)
from agents.grammar import RiskGrammar, build_exercise_index, compile_risk_grammar
from agents.pipeline import GenerationResult, PipelineAudit, run_pipeline
from agents.prescription import Prescription, prescribe
from agents.render import build_safety_notes, render_plan_draft
from agents.plan_agent import PlanAgent
from agents.safety_agent import SafetyEvalAgent
from agents.state_agent import StateRiskAgent

__all__ = [
    "PlanDraft",
    "RiskProfile",
    "SafetyReport",
    "Slot",
    "Violation",
    "RiskGrammar",
    "build_exercise_index",
    "compile_risk_grammar",
    "GenerationResult",
    "PipelineAudit",
    "run_pipeline",
    "Prescription",
    "prescribe",
    "render_plan_draft",
    "build_safety_notes",
    "PlanAgent",
    "SafetyEvalAgent",
    "StateRiskAgent",
]
