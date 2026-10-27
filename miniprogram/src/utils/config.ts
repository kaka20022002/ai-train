/**
 * 后端 API 地址（真机调试专用说明见下方）
 *
 * 【模拟器 / 浏览器预览】用 http://127.0.0.1:8000
 *
 * 这里刻意不写 localhost：Windows 上 localhost 可能先解析到 IPv6 的 ::1，
 * 而 uvicorn 绑的是 127.0.0.1（仅 IPv4），浏览器偶尔会直接报连接被拒。
 * 写死 IPv4 可以避开这个不确定性。
 *
 * 【真机连不上的常见原因】校园网 / 公司网「访客隔离」：
 * 手机和电脑即使同一 Wi‑Fi，也不能互相访问。
 *
 * 【推荐做法：开手机热点】
 * 1. iPhone：设置 → 个人热点 → 开启，让 Mac 连上这个热点
 * 2. Mac 终端执行：ipconfig getifaddr en0
 * 3. 把下面 API_BASE 改成 http://<上一步的IP>:8000
 * 4. 重新编译小程序，再真机调试
 *
 * 【备选：电脑开热点】
 * 系统设置 → 通用 → 共享 → 互联网共享，让手机连电脑热点，
 * 再用电脑热点网卡 IP（常为 192.168.2.1 一类）填到 API_BASE。
 *
 * 开发者工具务必勾选：不校验合法域名、web-view、TLS 版本以及 HTTPS 证书
 */
export const API_BASE = "http://127.0.0.1:8000";

export const STORAGE_KEYS = {
  token: "ai_train_token",
  userId: "ai_train_user_id",
};
