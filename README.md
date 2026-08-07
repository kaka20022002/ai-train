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

## 协作开发

其他人加入项目请先读：**[协作开发指南](docs/协作开发指南.md)**（克隆、环境、分支、PR、真机联调、模块边界）。

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
  - `USE_REAL_LLM=false` 或未设置 → 使用本地 Mock 生成器。
- LLM 厂商选择：
  - `LLM_PROVIDER=openai`（默认）
  - `LLM_PROVIDER=minimax`（示例 MiniMax 2.5 集成）

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
