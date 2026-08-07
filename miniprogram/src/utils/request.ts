import Taro from "@tarojs/taro";
import { API_BASE, STORAGE_KEYS } from "./config";

export class ApiError extends Error {
  status: number;
  body: string;

  constructor(status: number, body: string) {
    super(`${status}: ${body}`);
    this.status = status;
    this.body = body;
  }
}

function networkHint(errMsg: string): string {
  const base = API_BASE.replace(/^https?:\/\//, "");
  return (
    `连不上后端 ${base}。` +
    `真机请用手机热点连电脑后改 API 地址；` +
    `并勾选「不校验合法域名」。(${errMsg.slice(0, 40)})`
  );
}

/** 探测后端是否可达（用于真机调试排错） */
export async function pingBackend(): Promise<{ ok: boolean; message: string }> {
  try {
    const res = await Taro.request({
      url: `${API_BASE}/docs`,
      method: "GET",
      timeout: 5000,
    });
    if (res.statusCode >= 200 && res.statusCode < 500) {
      return { ok: true, message: `已连接 ${API_BASE}` };
    }
    return { ok: false, message: `后端响应异常 HTTP ${res.statusCode}` };
  } catch (e: any) {
    return {
      ok: false,
      message: networkHint(e?.errMsg || e?.message || String(e)),
    };
  }
}

export async function request<T>(
  path: string,
  options: {
    method?: "GET" | "POST" | "PUT" | "PATCH";
    data?: unknown;
    auth?: boolean;
  } = {}
): Promise<T> {
  const { method = "GET", data, auth = true } = options;
  const header: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (auth) {
    const token = Taro.getStorageSync(STORAGE_KEYS.token);
    if (token) header.Authorization = `Bearer ${token}`;
  }

  let res: Taro.request.SuccessCallbackResult;
  try {
    res = await Taro.request({
      url: `${API_BASE}${path}`,
      method,
      data,
      header,
      timeout: 20000,
    });
  } catch (e: any) {
    throw new Error(networkHint(e?.errMsg || e?.message || "request:fail"));
  }

  if (res.statusCode < 200 || res.statusCode >= 300) {
    const body =
      typeof res.data === "string" ? res.data : JSON.stringify(res.data ?? {});
    throw new ApiError(res.statusCode, body);
  }

  return res.data as T;
}
