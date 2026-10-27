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
const DEFAULT_API_BASE = "http://127.0.0.1:8000";

/**
 * 运行时决定后端地址，按优先级：
 *  1. 地址栏参数 ?api=http://192.168.1.5:8000（真机调试最省事，不用重新编译）
 *  2. 页面本身由后端同源托管（端口 8000）→ 用相对路径 ""，彻底没有跨域/混合内容问题
 *  3. 其它浏览器场景（如 5178 独立静态预览）→ 回落到 127.0.0.1:8000
 *  4. 小程序 / 开发者工具（没有 location）→ 127.0.0.1:8000
 */
function resolveApiBase(): string {
  try {
    const loc = (globalThis as any)?.location;
    if (loc && typeof loc.origin === "string" && /^https?:/.test(loc.origin)) {
      const fromQuery = new URLSearchParams(loc.search || "").get("api");
      if (fromQuery) return fromQuery.replace(/\/+$/, "");
      if (loc.port === "8000") return loc.origin;
      return DEFAULT_API_BASE;
    }
  } catch {
    /* 忽略：降级到默认地址 */
  }
  return DEFAULT_API_BASE;
}

export const API_BASE = resolveApiBase();

/** 提示文案里用的可读地址（API_BASE 为空表示同源） */
export function apiBaseLabel(): string {
  if (API_BASE) return API_BASE;
  try {
    return (globalThis as any)?.location?.origin || DEFAULT_API_BASE;
  } catch {
    return DEFAULT_API_BASE;
  }
}

export const STORAGE_KEYS = {
  token: "ai_train_token",
  userId: "ai_train_user_id",
};
