# 正式微信小程序 AppID：申请与接入

游客模式（`touristappid`）足够本地组会演示，但 **语音授权、真机稳定调试、体验版/正式版发布** 需要正式 AppID。

本仓库**无法代替你完成注册**（需个人/主体微信账号与实名信息）。下面是申请步骤与拿到 AppID 后如何接入本项目。

---

## 1. 申请 AppID（约 10–30 分钟）

1. 打开 [微信公众平台](https://mp.weixin.qq.com/) → 注册 → 选择 **小程序**
2. 用未绑定过小程序的邮箱注册，完成邮箱激活
3. 选择主体类型：
   - **个人**：最快，适合课程/组会；部分能力（支付、部分插件）受限
   - **企业/个体工商户/组织**：需营业执照等，能力更全
4. 完成管理员微信扫码、主体信息与身份证验证
5. 登录后：**设置 → 基本设置 → 账号信息**，复制 **AppID（小程序 ID）**  
   形如：`wx` + 16 位字符

官方说明：[小程序注册](https://developers.weixin.qq.com/miniprogram/dev/framework/quickstart/getstart.html)

---

## 2. 接入本仓库（拿到 AppID 后）

### 2.1 一键写入配置（推荐）

在仓库根目录执行（把下面换成你的真实 AppID）：

```bash
cd "/path/to/ai-train"
./scripts/set-wechat-appid.sh wx你的AppID
cd miniprogram && npm run build:weapp
```

脚本会更新：

- `miniprogram/project.config.json` 的 `appid`
- `miniprogram/project.private.config.json` 的 `appid`（若存在该字段）

### 2.2 手动改

编辑 `miniprogram/project.config.json`：

```json
"appid": "wx你的AppID"
```

### 2.3 微信开发者工具

1. 打开项目目录：`miniprogram/`（不要只开 `dist/`）
2. 详情 → 基本信息：确认 AppID 已是正式号（不是 tourist）
3. 本地开发仍可勾选「不校验合法域名」
4. 清缓存 → 编译

---

## 3. 建议在公众平台一并开通

| 项 | 路径 / 说明 |
|----|-------------|
| 开发者 | 成员管理 → 添加本机微信号为开发者 |
| 服务器域名 | **上线前**必填：request / uploadFile / downloadFile 合法域名（须 HTTPS） |
| 录音 | 用户隐私保护指引里声明「麦克风」；代码侧用 `authorize({ scope: 'scope.record' })` |
| 同声传译插件（可选） | 设置 → 第三方设置 → 插件管理 → 添加「同声传译」；再在 `app.config.ts` 恢复 `plugins.WechatSI` |

本地联调阶段：继续用电脑上的 FastAPI（`localhost` 或局域网 IP）。正式环境需把 `API_BASE` 改成已备案的 HTTPS 域名，并在公众平台配置合法域名。

---

## 4. 与当前工程的关系

| 能力 | 游客 AppID | 正式 AppID |
|------|------------|------------|
| 模拟器演示、调后端 | ✅ | ✅ |
| 录音 `scope.record` | 受限 / 告警 | ✅（需用户授权） |
| 真机预览 / 体验版 | 差 | ✅ |
| 上传发布 | ❌ | ✅ |
| WechatSI 插件 | ❌ | 需额外开通 |

语音识别当前默认走后端 **`/stt`（Whisper）**，不依赖微信插件；正式 AppID 主要解决授权与发布，不是 STT 的硬依赖。

---

## 5. 安全注意

- **AppSecret** 只放在服务端 `.env`（若做 `code2session`），**不要**写进小程序前端、不要提交 Git
- `.env` 已在 `.gitignore`；密钥私聊分发
- 个人主体小程序名称、简介需符合平台规范，避免未上线就宣传「医疗诊断」等表述

---

## 6. 完成后自检

- [ ] `project.config.json` 中 `appid` 已是 `wx…`
- [ ] 开发者工具显示正式 AppID，编译无「游客模式」限制提示（或明显减少）
- [ ] 模拟器可登录/拉计划；真机预览能连到你的 API（热点 + `sync-api-base.sh` 或 HTTPS）
- [ ] （可选）隐私指引已声明麦克风；按住说话能弹出授权
