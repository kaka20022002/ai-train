# AI 健身教练 — 微信小程序（Taro）

对齐网页版核心功能的小程序客户端。

## 功能对照

| 网页版 | 小程序 |
|--------|--------|
| 今日训练 | Tab「今日训练」+ 训练执行页 |
| 仪表盘 | 「计划/我的」→ 仪表盘 |
| 生成计划 | 「计划/我的」→ 生成计划（单次/周期） |
| 周期计划 | Tab「计划」+ 推进下周 |
| 风险分析 | 「计划/我的」→ 风险分析 + 同步档案 |
| 动作库 | Tab「动作库」 |
| AI 教练 | Tab「AI 教练」（支持按住说话） |
| 我的档案 | Tab「我的」 |

## AI 教练 · 语音输入

按住底部麦克风 → 松手结束 → 自动识别并发送。

当前默认：**录音 + 后端 `/stt`**（测试号可用，不依赖微信插件）。

```bash
# .env — DeepSeek 对话密钥不能转写，需单独配置 Whisper
WHISPER_API_KEY=sk-...
WHISPER_BASE_URL=https://api.openai.com/v1
WHISPER_MODEL=whisper-1
```

正式 AppID 若要用「同声传译」插件：公众平台添加插件后，在 `app.config.ts` 恢复 `plugins.WechatSI` 声明即可。

## 底部 Tab（5）

今日训练 · 计划 · 动作库 · AI 教练 · 我的

## 启动

```bash
# 后端
cd "/Users/wyh/Downloads/06_代码项目/ai-train"
.venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 小程序
cd miniprogram
npm run dev:weapp
```

微信开发者工具打开 `miniprogram/`，勾选「不校验合法域名」，点编译。
