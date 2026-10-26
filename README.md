# Adaptive Athletic Risk Assessment System

基于 FastAPI 的自适应运动风险评估与训练计划生成系统。

本项目包含三个核心部分：

1. **RiskAssessmentEngine (`risk_engine.py`)**  
   基于用户伤病史和训练反馈进行静态/动态风险评估，输出禁止动作和训练约束。
2. **PlanGenerator (`plan_generator_mock.py`)**  
   - 默认使用本地 **Mock 生成器** 生成安全的训练计划；
   - 可选接入真实 LLM（例如 OpenAI GPT 系列）生成计划。
3. **FastAPI 接口 (`main.py`)**  
   提供 `/generate_plan`、`/analyze_risk`、`/exercises` 等 REST 接口。
4. **微信小程序（Taro）** — 目录 `miniprogram/`  
   今日训练 / AI 教练 / 计划 / 我的；详见 [`miniprogram/README.md`](miniprogram/README.md)。
5. **训练计划推荐** — 基于用户档案、训练历史、器材和伤病条件生成个性化计划排序。
   详见 [`docs/plan-recommendation/README.md`](docs/plan-recommendation/README.md)。

## 协作开发

其他人加入项目请先读：**[协作开发指南](docs/协作开发指南.md)**（克隆、环境、分支、PR、真机联调、模块边界）。

组会演示请看：**[组会演示清单](docs/组会演示清单.md)**。

训练计划推荐模块说明：**[计划推荐 README](docs/plan-recommendation/README.md)**。

正式微信小程序 AppID（真机/发布）：**[微信 AppID 申请与接入](docs/微信AppID申请与接入.md)**。

环境变量模板：复制 [`.env.example`](.env.example) 为 `.env` 后填写，**不要提交密钥**。

## 环境准备

```bash
cd "/Users/wyh/Downloads/06_代码项目/ai-train"
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 运行 API 服务

开发模式启动：

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

或直接运行：

```bash
python main.py
```

然后在浏览器打开：`http://localhost:8000/docs` 查看交互式文档。

## 接入真实 LLM

项目已支持可选接入真实 LLM，并通过 `LLM_PROVIDER` 环境变量选择不同厂商。

### 通用说明

- 是否启用 LLM：
  - `USE_REAL_LLM=true`  → 通过 `LLMClient` 调用真实 LLM；
  - `USE_REAL_LLM=false` 或未设置 → 使用本地规则/Mock 后端。
- LLM 厂商选择：
  - `LLM_PROVIDER=openai`（默认，DeepSeek 等 OpenAI 兼容网关也走这条）
  - `LLM_PROVIDER=minimax`（示例 MiniMax 2.5 集成）

### 一把 key 驱动三个 Agent

`POST /generate_plan` 默认走三 Agent 管线（`engine=agents`）。三个 Agent 共用
**同一组环境变量、同一个 `LLMClient` 实例**，但各自使用独立的 system prompt
（见 `agents/prompts.py`）：

| Agent | prompt 版本 | 职责 | 接不上 LLM 时 |
| --- | --- | --- | --- |
| `state_risk` | `state_risk/2.1.0` | 从病历自由文本抽取规则算不出的约束（模式禁忌、时长上限、容量判断） | 退回纯规则阈值表 |
| `plan_gen` | `plan_gen/2.1.0` | **决定**选哪些动作、顺序、组数、次数、负荷、休息 | 退回确定性采样 + 处方推荐值 |
| `safety_eval` | `safety_eval/2.0.0` | 独立审查，输出枚举违规码（含剂量合理性） | 退回纯谓词校验 |

### 模型看到的输入是完整档案，不是摘要

`/generate_plan` 的请求体里，`user_profile` 的**每个字段**都会进入 Agent 1
的 payload。这一点很关键 —— 只下发「关节 + 严重度」的摘要，模型就只能做
阈值表的复读机。

| 字段 | 用途 | 谁执行 |
| --- | --- | --- |
| `medical_history[].notes / pain_trigger` | 唯一的自由文本，「蹲到底膝内侧刺痛」这类描述只能从这儿读 | 模型 |
| `medical_history[].location / severity` | 阈值表映射；模型二次阅读用于发现映射错误 | 规则（模型可追加） |
| `available_equipment` | 没有的器械做不了 —— **硬约束**，动作直接进 forbidden | 规则 |
| `fitness_goal` | 剂量取向（力量→上沿低次，减脂→辅助补量，康复→全面下沿） | 模型 |
| `training_frequency` | 每周次数少则单次覆盖更多，多则单组组数取低 | 模型 |
| `preferences` | 兴趣：`liked_patterns` / `disliked_patterns` / `disliked_exercises` / `notes` | 模型（**软约束**） |
| `query`（请求顶层） | 本次需求原话，可含时间限制与当天状态，可转成 `session_cap_minutes` | 模型 |

两条容易搞混的边界：

- **偏好不是禁忌。** `preferences` 只会在候选行上打 `liked: true` / `disliked: true`
  标记，同等多重选择时让位；它**不会**写进 `forbidden`。不喜欢不等于不能做，
  把偏好偷换成禁忌会白送掉本该训练的空间。
- **器械是禁忌。** 没列出来的器械对应的动作与伤情禁忌同处一个禁止集，
  理由码为 `EQUIPMENT_MISSING:<器械>`，在 `audit` 里可见。

`query` 示例：

```json
{
  "user_profile": { "...": "..." },
  "workout_type": "lower_body",
  "query": "今天只有三十分钟，想练下肢，膝盖蹲到底有点不舒服"
}
```

### 训练类型是硬过滤，不是提示词

`workout_type`（`full_body` / `upper_body` / `lower_body` / `push` / `pull`）
在编译文法时就被翻译成候选集的物理范围（`agents/focus.py`）——
练腿日模型根本看不到上肢动作，所以在它那一侧不可能排出上肢计划。

| 训练类型 | 生效方式 |
| --- | --- |
| `lower_body` | 只保留下肢肌肉（股四 / 臀 / 腘绳 / 小腿）+ 中性（核心、稳定、活动度） |
| `upper_body` | 只保上胸背肩臂 + 中性 |
| `push` / `pull` | 按动作模式（`push_h/v`、`pull_h/v`、屈伸肘）划分 |
| `full_body` / 未知值 | 不限制 |

两个实现细节：

- **以目标肌肉为准，动作模式只兜底。** 侧平举和蚌式开合的 `motion_pattern`
  都是 `abduction`，只按模式判会把侧平举放进练腿日。
- **热身与放松阶段豁免。** 全身升温与放松本来就不分部位，按部位裁剪只会让
  候选枯竭；跨阶段补位也只接受类型相容的动作（不会把拉伸塞进主项段）。

`exercise_db.json` 现有 **77 条**动作。2026-10 补了 7 条哑铃/自重主项
（高脚杯深蹲、哑铃罗马尼亚硬拉、哑铃相扑硬拉、单腿臀桥、单臂划船、
俯身划船、反向划船），原因是原来的下肢主项全依赖杠铃与器械架 ——
「膝伤 + 只有哑铃」的用户在练腿日会一个主项都选不出来。

### 权力结构：模型决策，规则兜底

模块的分工不是「规则裁剪完让模型从剩下的里挑」，而是「模型自由决定，越界部分
由规则夹紧」。区别在模型的实际自由度：

| 维度 | 规则 | 模型 |
| --- | --- | --- |
| 哪些动作被禁止 | **独占**（阈值表 + 语义追加） | 只能追加，不能放宽 |
| 组数 / 次数 / 负荷 | 给**区间**（`prescription_bounds`） | 在区间内**自行取值** |
| 动作顺序 / 组合 | 只保证阶段归属 | **独占** |
| 单动作要点 / 组间休息 | 只做默认值 | **独占** |
| 验收判定 | 谓词校验（不可绕过） | 合取，只能加严 |

三条不会被模型突破的线：

1. **合取验收**：`passed = rule_passed AND llm_passed`。LLM 通道超时或返回坏
   JSON 时，判定退回规则结论而不是放行。
2. **参数夹紧**：模型给的组次负荷必须落在 `prescription_bounds()`
   推导出的区间内（按动作类型 × 阶段），越界由 `PrescriptionBounds.clamp`
   夹到边界并计入 `adjusted_slots`；ID 或阶段越界则直接进 `rejected_ids`。
3. **约束单向**：`state_risk` 的追加类字段只能让约束更紧。但
   `avoid_patterns` / `session_cap_minutes` 是规则没有的维度 —— 这正是
   「让模型做规则做不到的事」，而不是让它把阈值表重算一遍。

响应里 `safety.llm_verdict` / `safety.state_llm_status` / `generator_version`
会显示三个 Agent 的实际后端，`safety.avoid_patterns` / `session_cap_minutes` /
`adjusted_slots` 展示语义约束与越界程度，`audit` 数组逐条记录各自用的 prompt
版本，可直接用于对照实验（Mock vs LLM）。

### 使用 OpenAI 模型（示例 GPT-4.1）

1. 安装依赖（`requirements.txt` 已包含）：
   ```bash
   pip install -r requirements.txt
   ```

2. 设置环境变量：
   ```bash
   export LLM_PROVIDER=openai
   export OPENAI_API_KEY="你的_openai_api_key"
   # 可选：自定义模型和网关
   export OPENAI_MODEL="gpt-4.1"        # 默认即为 gpt-4.1
   export OPENAI_BASE_URL="https://api.openai.com/v1"  # 如使用代理/网关可修改

   # 打开真实 LLM 模式
   export USE_REAL_LLM=true
   ```

3. 启动服务（同上）：
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

### 使用 MiniMax 2.5（示例集成）

`llm_client.py` 中已提供 MiniMax 的 HTTP API 示例，你需要根据 MiniMax 官方文档填写正确的接口 URL 和模型名。

1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```

2. 设置环境变量（示例）：

   **方案 A：MiniMax HTTP 接口（OpenAI 兼容格式）**
   ```bash
   export LLM_PROVIDER=minimax
   export MINIMAX_API_KEY="你的_minimax_api_key"
   export MINIMAX_MODEL="你的_minimax_模型名"   # 例如 abab6.5-chat 等
   export MINIMAX_API_URL="https://你的-minimax-聊天接口URL"

   export USE_REAL_LLM=true
   ```

   **方案 B：MiniMax Anthropic SDK 接口（推荐，支持 MiniMax-M2.7 等新模型）**
   ```bash
   export LLM_PROVIDER=minimax_anthropic
   export ANTHROPIC_API_KEY="你的_minimax_api_key"
   export ANTHROPIC_BASE_URL="https://api.minimaxi.com/anthropic"
   export MINIMAX_MODEL="MiniMax-M2.7"   # 可选，默认即 MiniMax-M2.7

   export USE_REAL_LLM=true
   ```

3. 启动服务：
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

> **MiniMax Anthropic 接口说明**：`LLM_PROVIDER=minimax_anthropic` 使用
> `anthropic` SDK 发起请求（`pip install anthropic` 已包含在
> `requirements.txt` 中）。响应中的 `thinking` 块会被自动跳过，仅提取
> `text` 块作为计划内容。若模型未返回有效 JSON，系统会自动重试最多 2 次，
> 重试仍失败则降级到本地 Mock 生成器。

在 `USE_REAL_LLM=true` 且对应厂商的 API Key 等环境变量正确配置的情况下：

- `main.py` 会以 LLM 模式初始化 `PlanGeneratorMock`；
- `plan_generator_mock.py` 内部通过 `LLMClient` 调用真实 LLM；
- 若环境变量缺失或初始化失败，可将 `USE_REAL_LLM` 置为 `false` 回退到本地 Mock 生成器。

## 命令行 Demo

也可以直接运行计划生成 Demo：

```bash
python plan_generator_mock.py
```

- 默认使用 Mock 模式；
- 若设置 `USE_REAL_LLM=true` 且提供 `OPENAI_API_KEY`，则会通过真实 LLM 生成计划。

## 典型调用流程

1. 客户端提交用户档案 `UserProfile` 与可选的训练反馈 `FeedbackInput` 到 `/generate_plan`。
2. `RiskAssessmentEngine` 基于 `exercise_db.json` + 伤病史做静态风险评估，并基于反馈做动态约束。
3. `PlanGeneratorMock`（Mock 或真实 LLM）在安全动作集合内生成完整的训练计划。
4. FastAPI 将计划按结构化 JSON 返回，包含分阶段动作和安全提示等信息。

## 视频动作安全分析

网页端 `/video-analysis` 支持上传一段运动视频并输入问题，例如：

- “我的动作在整个视频中有没有问题？”
- “这个深蹲动作是否存在可能增加受伤风险的模式？”

后端使用两阶段模型链路：

1. V-Socrate-1020 使用 CLIP + Qwen 多模态 vLLM 搜索并复核关键帧；
2. 当前 `LLM_PROVIDER`（`.env.example` 默认 DeepSeek）将视频证据与用户伤病档案、
   近期疼痛和训练历史结合，生成最终中文答复。

DeepSeek 不直接读取视频帧。原始
`Videoagent/V-Socrate-1020` 目录保持不变；应用使用
`vendor/v_socrate_1020/` 中的最小推理副本。

### 依赖与配置

先安装基础依赖和可选视频依赖：

```bash
pip install -r requirements.txt
pip install -r requirements-video.txt
```

确认多模态 vLLM 已启动，并在 `.env` 中配置：

```bash
V_SOCRATE_ENABLED=true
V_SOCRATE_MODEL=qwen3-vl-8b-instruct
V_SOCRATE_ENDPOINTS=http://127.0.0.1:8200/v1
V_SOCRATE_CLIP_MODEL=/absolute/path/to/clip-vit-base-patch32
V_SOCRATE_CACHE_DIR=./.cache/v_socrate

# 最终答案仍使用现有模型，例如 DeepSeek
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-chat
OPENAI_API_KEY=...
```

没有 GPU 服务时，可用 `V_SOCRATE_USE_MOCK=true` 验证上传、对话持久化和页面状态；
Mock 会明确提示没有真正读取视频，不能用于动作判断。

### API 示例

```bash
curl -X POST http://localhost:8000/video-analysis \
  -F 'user_id=usr_001' \
  -F 'question=请检查整个视频中的深蹲动作是否存在风险' \
  -F 'file=@./squat.mp4;type=video/mp4'
```

默认支持 MP4、MOV、M4V、WebM，大小上限 100 MiB。上传内容只保存在临时文件中，
请求结束后立即删除；VideoIndex 特征缓存按文件哈希存放，不保存原视频。
