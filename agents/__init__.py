"""多 Agent 运动计划生成管线。

设计约束（与论文口径一致）：

1. **结构化边界**：Agent 之间只传 dataclass / 纯 JSON 字段
   （``{exercise_id, sets, reps, load_pct, impact}``），不传自然语言。
   自然语言只允许出现在最外层（用户输入、最终展示），不进入 Agent 通道。
2. **会审而非前筛**：v3 起不再把风险档案编译成候选裁剪 —— 生成端拿到全量
   动作库，安全性由第 3 个 Agent 事后审查保证，判 fail 则把违规项回灌重写。
   ``RiskGrammar`` 仍然保留，但只服务于「没配模型」的降级后端。

模块划分：
    contracts      数据契约（唯一跨 Agent 传输格式）
    catalog        全量动作库视图（生成端与审查端共享）
    grammar        候选采样（**仅降级后端**使用）
    prescription   处方推导与参考区间（动作类型 × 阶段）
    prompts        三份独立的 Agent system prompt
    llm_bridge     同一个 LLM 客户端 → 三个职责不同的调用入口
    state_agent    状态与风险分析 Agent（产出基线证据）
    plan_agent     计划生成 Agent（全库自由生成 + 按审查意见重写）
    safety_agent   计划安全审查 Agent（最终裁决）
    pipeline       编排与审计
    render         结构化产物 → 对外 JSON
"""

from agents.catalog import ExerciseCatalog, build_catalog
from agents.contracts import (
    PlanDraft,
    RiskProfile,
    SafetyReport,
    Slot,
    Violation,
)
from agents.grammar import RiskGrammar, build_exercise_index, compile_risk_grammar
from agents.llm_bridge import AgentBridges, build_bridges
from agents.pipeline import GenerationResult, PipelineAudit, run_pipeline
from agents.prescription import Prescription, prescribe
from agents.prompts import (
    PLAN_GEN_PROMPT_VERSION,
    SAFETY_EVAL_PROMPT_VERSION,
    STATE_RISK_PROMPT_VERSION,
)
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
    "ExerciseCatalog",
    "build_catalog",
    "RiskGrammar",
    "build_exercise_index",
    "compile_risk_grammar",
    "AgentBridges",
    "build_bridges",
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
    "STATE_RISK_PROMPT_VERSION",
    "PLAN_GEN_PROMPT_VERSION",
    "SAFETY_EVAL_PROMPT_VERSION",
]
