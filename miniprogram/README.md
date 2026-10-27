# AI 健身教练 — 微信小程序（Taro）

对齐网页版核心功能的小程序客户端。

## 功能对照

| 网页版 | 小程序 |
|--------|--------|
| 今日训练 | Tab「今日训练」+ 训练执行页 |
| 仪表盘 | 「计划/我的」→ 仪表盘 |
| 生成计划 | 「计划/我的」→ 生成计划（单次/周期） |
| 计划推荐 | Tab「计划」→ 计划推荐 |
| 周期计划 | Tab「计划」+ 推进下周 |
| 风险分析 | 「计划/我的」→ 风险分析 + 同步档案 |
| 动作库 | Tab「动作库」 |
| AI 教练 | Tab「AI 教练」（支持按住说话） |
| 视频动作分析 | 「AI 教练/我的」→ 上传视频并输入问题 |
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
cd ..
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 小程序
cd miniprogram
npm install
npm run dev:weapp
```

微信开发者工具打开 `miniprogram/`，勾选「不校验合法域名」，点编译。

## 演示视频动作分析

1. 打开底部 Tab「AI 教练」，点击顶部「上传视频分析动作」；
2. 从相册选择视频或直接拍摄，输入希望重点检查的问题；
3. 点击「开始视频分析」，保持页面打开直到结果返回；
4. 页面会展示 V-Socrate 的动作观察、证据时间点、AI 教练答复和安全声明。

快速验证页面和 multipart 上传流程时，可在后端 `.env` 设置
`V_SOCRATE_USE_MOCK=true`。要验证真实视频理解，请配置
`V_SOCRATE_ENDPOINTS`、`V_SOCRATE_MODEL` 与 `V_SOCRATE_CLIP_MODEL`。

开发者工具默认使用 `http://localhost:8000`。真机调试时，把
`src/utils/config.ts` 中的 `API_BASE` 改成手机可访问的电脑局域网 IP，
并在开发者工具中勾选「不校验合法域名」；正式发布时需使用已备案的 HTTPS 域名。

默认 `project.config.json` 使用游客 `touristappid`。申请正式 AppID 并写入配置见仓库文档：

[`docs/微信AppID申请与接入.md`](../docs/微信AppID申请与接入.md)

```bash
# 拿到 AppID 后
../scripts/set-wechat-appid.sh wx你的AppID
npm run build:weapp
```
