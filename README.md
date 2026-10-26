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
| `state_risk` | `state_risk/3.0.0` | 读身体情况出**风险报告**（risk_level / clearance / injuries / dose_guidance / watch_items）+ 约束投影 | 退回阈值表生成的基线报告 |
| `plan_gen` | `plan_gen/3.1.0` | 照报告 + 需求**全权决定**全库选哪些动作、放哪个阶段、顺序、组次负荷、休息；被打回时自己改 | 退回确定性采样 + 处方推荐值 |
| `safety_eval` | `safety_eval/3.1.0` | **最终裁决**：判是否符合安全标准、是否适合这位用户（`REPORT_BREACH`），确认或否决基线提示 | 退回基线谓词 |

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

### 三阶段语义（v4）：评估 → 生成 → 复核

管线不是「三个过滤器」，而是三次**不同性质的判断**：

| 阶段 | Agent | 输入 | 产物 |
| --- | --- | --- | --- |
| ① 评估 | `state_risk` | 病历原文、训练反馈、本次需求 | **风险报告**：整体风险等级、能否开练、每条伤情的功能影响与具体禁忌、剂量口径、要盯的信号 |
| ② 生成 | `plan_gen` | 风险报告 + 用户需求 + 全量动作库 | 完整计划（动作、顺序、组次、负荷、休息） |
| ③ 复核 | `safety_eval` | 计划 + 风险报告 + 基线命中项 | 裁决：符合安全标准吗？适合这位用户吗？ |

**报告长这样**（`/generate_plan` 的 `risk_analysis.risk_report`）：

```json
{
  "source": "agent",
  "overall": {"risk_level": "high", "clearance": "conditional",
              "summary": "下肢只能做无痛幅度内的髋主导动作"},
  "injuries": [{
    "location": "knee", "condition": "meniscus_tear",
    "functional_impact": "屈膝超过 90° 出现内侧刺痛，闭链屈膝耐受差",
    "contraindications": ["深屈膝闭合链负荷", "跳跃落地缓冲"],
    "safe_substitutes": ["髋主导", "低冲击"],
    "impact_cap": 2, "load_pct_ceiling": 55
  }],
  "dose_guidance": {"volume": "单次不超过 12 个工作组", "intensity": "主项 ≤55% 1RM"},
  "watch_items": ["膝内侧出现刺痛立即停止该动作"]
}
```

报告与 `RiskProfile` 里那组约束是**同一判断的两种形态**：报告给人读、给下游
Agent 读；约束（`allowed_ids` / `joint_caps` / `avoid_patterns` / …）是它的
机器可执行投影，由程序逐条核对。两者由同一个 Agent 产出，不会互相打脸。

两处刻意的不对称：

- `clearance` / `risk_level` 只能**更保守**。模型可以比阈值表严，不能更松 ——
  松的那一侧由约束兜着，报告若比约束乐观就自相矛盾。
- `injuries` / `dose_guidance` / `watch_items` 允许整体替换 —— 这些正是规则
  结构性算不出来的，模型说什么就是什么（逐条做类型收敛）。

`risk_report.source` 标明报告出自谁：`agent` = 读过病历原文的判断；
`baseline` = 没配模型，阈值表生成的降级版本（形状完全相同，下游不必判空）。

### 权力结构：模型全权决策，Rule 只做会审依据

中间那层规则在 v3 被拆掉了。原先是「规则裁剪候选 → 模型在剩下的里挑 →
规则夹紧参数 → 规则判合规 ∧ 模型判合规」，模型实际上没有决定权。现在是：

| 维度 | 谁决定 |
| --- | --- |
| 能选哪些动作 | **模型**（全库 77 条，无候选裁剪、无 enum 掩码） |
| 放哪个阶段 | **模型**（`phases` 只是建议，放错了由审查判 `SEQUENCE`） |
| 组数 / 次数 / 负荷 / 休息 | **模型**（原样落库，不再夹紧） |
| 训练是否安全 | **审查 Agent**（它的 verdict 就是最终结论） |
| 是否符合这位用户 | **审查 Agent**（拿计划逐条对风险报告，判 `REPORT_BREACH`） |
| 计划被打回后怎么改 | **生成 Agent 自己改**（拿到违规清单重写，不是规则补位） |

规则只剩两处身位：

1. **报告与约束的基线**。`state_risk` 用阈值表算出禁忌清单、关节上限、
   冲击上限，作为报告的 `source=baseline` 版本和 `baseline` 字段下发 ——
   这是「另一个 Agent 的意见」，不是硬约束。模型可以判定某条对本次训练
   不适用，代价是要在接受会审时说清依据。
2. **降级后端**。没配 key 时没有任何 Agent 能做判断，此时才启用
   `RiskGrammar` 的候选采样 + 处方推荐值，并在响应里标注
   `review_mode="baseline"`（本次未经 Agent 审查）。

审查的三种结论（`safety.review_mode`）：

| review_mode | 含义 | `passed` 由谁给 |
| --- | --- | --- |
| `agent` | 审查 Agent 正常裁决 | 模型 verdict |
| `baseline_fallback` | 审查 Agent 超时 / 坏 JSON | 基线谓词（不放行） |
| `baseline` | 没配模型 | 基线谓词 |

会审回路：`safety_eval` 判 fail → 违规清单 + 上一版计划回灌给 `plan_gen`
→ 重写 → 再审，最多 2 轮（`max_review`）。审计链里对应 `review_round`
记录，`safety.review_rounds` 是实际轮次。

响应里 `risk_analysis.risk_report` / `safety.review_mode` / `llm_verdict` /
`review_rounds` / `baseline_flags` 显示判断内容与判定归属，`audit` 数组逐条
记录三个 Agent 的输入摘要与输出结构，可直接用于对照实验（降级 vs LLM、
不同 prompt 版本）。

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

接好 key 之后建议按这个顺序验证，别一上来就跑整条链路：

```bash
python scripts/check_llm.py              # ① 配置对不对（两次最小请求，几秒）
python scripts/trace_stages.py --agent   # ② 产物形状对不对（假模型，不花钱）
python scripts/trace_stages.py --llm     # ③ 真模型跑一遍三阶段 + 会审回路
```

`--llm` 的完整输出会写到 `docs/trace_llm.txt`，可以直接对比 `docs/trace_baseline.txt`
看模型到底改了什么。单元测试不受 `.env` 影响：`tests/conftest.py` 会钉住
`USE_REAL_LLM=false`，跑 `pytest` 不会调用真实 API。

最后打一次真实接口，确认 HTTP 层也通（约 1-2 分钟，含会审回路）：

```bash
uvicorn main:app --host 127.0.0.1 --port 8000
curl -X POST http://127.0.0.1:8000/generate_plan \
  -H "Content-Type: application/json" \
  --data-binary @docs/request_llm_demo.json
```

`docs/request_llm_demo.json` 是一份**符合接口 schema**的样例：半月板术后 + 肩峰撞击、
今日膝痛 3/10、RPE 8、需求「只有三十分钟想练下肢」。注意 `feedback` 里的
`rpe` 与 `pain_feedback.has_pain` 是必填项，缺了直接 422。

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
