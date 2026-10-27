import Taro from "@tarojs/taro";
import { API_BASE, STORAGE_KEYS, apiBaseLabel } from "./config";

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
  const base = apiBaseLabel().replace(/^https?:\/\//, "");
  return (
    `连不上后端 ${base}。` +
    `电脑上直接访问 http://${base}/health 应能看到 {"status":"ok"}；` +
    `若手机真机调试，请先用 ?api=http://<电脑IP>:8000 指定地址。` +
    `(${errMsg.slice(0, 60)})`
  );
}

/** 把底层异常翻译成人能看懂的一句话，避免所有失败都显示「连不上后端」 */
function describeError(e: any): string {
  const raw = String(e?.errMsg || e?.message || e || "");

  if (/timeout|超时|abort/i.test(raw)) {
    return (
      "等了很久后端还没回话（请求已超时）。" +
      "教练这条链路要先跑一次风险分析，首次通常 20-40 秒，请重试一次。"
    );
  }
  if (/fail|network|ECONN|ERR_|Failed to fetch/i.test(raw)) {
    return networkHint(raw);
  }
  return raw || "请求失败";
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
    /** 毫秒；默认 20s。含 LLM 的接口（/chat、/generate_plan）要显式放宽 */
    timeout?: number;
  } = {}
): Promise<T> {
  const { method = "GET", data, auth = true, timeout = 20000 } = options;
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
      timeout,
    });
  } catch (e: any) {
    throw new Error(describeError(e));
  }

  if (res.statusCode < 200 || res.statusCode >= 300) {
    const body =
      typeof res.data === "string" ? res.data : JSON.stringify(res.data ?? {});
    throw new ApiError(res.statusCode, body);
  }

  return res.data as T;
}
