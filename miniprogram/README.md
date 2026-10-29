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

## AI 教练 · 回复排版

教练回复不再是一坨纯文本。后端 `sanitize_coach_plaintext()` 只保留一套轻量语法，
前端 `components/MarkdownLite.tsx` 负责渲染：

| 语法 | 渲染成 |
|---|---|
| `### 结论` | 左侧色条的章节标题 |
| `· 要点` | 圆点列表（缩进 2 格为子要点） |
| `1. 臀桥 · 3 组 × 12 次` | 方形序号 + 动作名 + 右侧「3 组 × 12 次」剂量徽章 |
| `1. 现在膝盖疼吗？……` | 超过 20 字且无剂量的有序项按段落排，不套序号徽章 |
| 空行 | 分段 |

加粗、表格、代码块仍会被剥掉（旧客户端不会渲染），所以提示词里也禁止模型使用。

修改排版后可以用脚本核对解析结果，不必等浏览器：

```bash
node scripts/check-markdown.mjs ../docs/coach_reply_sample.md
# blocks=33  heading=4  item=26  para=3  divider=0
# [H]   结论
# [O] 2. 臀桥  ⟨3 组 × 12 次⟩
```

## 底部 Tab（5）

今日训练 · 计划 · 动作库 · AI 教练 · 我的

## VR 跟练

入口位于「今日训练」内容底部，不增加底部 Tab。独立页面包含「连接与准备」和「跟练记录」：
为当前登录用户生成六位短码，在头显输入匹配；匹配后显示用户并倒计时 3 秒开练，可取消。
可主动附带今日计划参考，实际课表由 VR 端选择。短码有效期 5 分钟，重新生成使旧码失效。
训练期间不轮询、不远程控制，结束回传后手动刷新记录。解除关联前二次确认，历史记录保留。

页面复用当前登录 token，与网页版访问同一后端 `/vr` 接口。两端需选择相同用户才能查看同一份关联与记录。
新逻辑与样式集中在 `src/features/vr/`，路由为 `src/pages/vr/`；离开页面会取消请求，重新进入按当前用户读取。
协议说明见 [`docs/vr-bridge/README.md`](../docs/vr-bridge/README.md)。

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

## 没有开发者工具？先跑 H5 版看界面

若要同时保留微信编译产物，可使用独立预览命令：

```bash
npm run build:h5:preview  # 输出 dist-h5/，不覆盖微信的 dist/
npx serve dist-h5 -l 5178
```

这只是新增的可选命令；原 `build:h5` / `build:weapp` 仍输出到 `dist/`。

同一套 Taro 代码可以编译成网页，界面与小程序一致（少了微信登录、录音、真机手势）：

```bash
cd miniprogram
npm install
npm run build:h5          # 产物在 dist/
npx serve dist -l 5178    # 或任意静态服务器
```

浏览器开 `http://127.0.0.1:5178`，数据来自本地后端 `http://localhost:8000`
（`src/utils/config.ts` 里的 `API_BASE`）。后端 CORS 已放开 `*`，不用额外配置。

> `build:h5` 依赖 `@tarojs/plugin-platform-h5`，已写进 devDependencies。
> 首次 `npm install` 若在 Windows 报 `esbuild EBUSY`，忽略即可 —— 包本身已装好，
> 直接继续 `build:h5`。

默认 `project.config.json` 使用游客 `touristappid`。申请正式 AppID 并写入配置见仓库文档：

[`docs/微信AppID申请与接入.md`](../docs/微信AppID申请与接入.md)

```bash
# 拿到 AppID 后
../scripts/set-wechat-appid.sh wx你的AppID
npm run build:weapp
```
