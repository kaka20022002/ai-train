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
| `state_risk` | `state_risk/1.0.0` | 读病历文本，**只能追加**约束 | 退回纯规则阈值表 |
| `plan_gen` | `plan_gen/1.0.0` | 在已裁剪的候选集内选动作 | 退回确定性采样 |
| `safety_eval` | `safety_eval/1.0.0` | 独立审查，只输出枚举违规码 | 退回纯谓词校验 |

两点设计约束值得注意：

1. **合取验收**：`passed = rule_passed AND llm_passed`。接上 LLM 只会让判定更严，
   永远不能放宽；LLM 通道超时或返回坏 JSON 时，判定退回规则结论而不是放行。
2. **单向增强**：`state_risk` 的 LLM 建议只能让约束更紧（追加禁忌、下调关节上限）。
   它提议移除禁忌或调高上限都会被丢弃 —— 上游一旦可被放宽，下游的合规性就不再可证。

响应里 `safety.llm_verdict` / `safety.state_llm_status` / `generator_version`
会显示三个 Agent 的实际后端，`audit` 数组逐条记录各自用的 prompt 版本，
可直接用于对照实验（Mock vs LLM）。

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
