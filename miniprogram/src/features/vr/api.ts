/** Preparation-only bridge. Reuse the current login, never obtain device secrets. */
import Taro from "@tarojs/taro";
import { API_BASE, STORAGE_KEYS } from "../../utils/config";
import { parseConnection, parseOverview, parsePairing } from "./validation";

export class VrRequestError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export interface VrIdentity {
  userId: string;
  token: string;
}
export interface ReferencePlan {
  title: string;
  source_week: number;
  estimated_duration_minutes?: number | null;
  phases?: Record<
    string,
    { name: string; sets: number; reps: string }[]
  > | null;
  key_exercises: { name: string; sets: number; reps: string }[];
}
export interface Connection {
  id: string;
  device_name: string;
  connected_at: number;
  reference: ReferencePlan | null;
}
export interface TrainingResult {
  id: string;
  ended_at: string;
  started_at: string;
  received_at: number;
  outcome: "completed" | "stopped";
  actions: {
    action_id: string;
    action_name: string;
    completed_sets: number | null;
    completed_reps: number | null;
    duration_seconds: number | null;
    quality_score_01: number | null;
    tracking_good_ratio_01: number | null;
  }[];
}
export interface Overview {
  pairing: {
    id: string;
    expires_at: number;
    reference: ReferencePlan | null;
  } | null;
  connection: Connection | null;
  today_reference: ReferencePlan | null;
  results: TrainingResult[];
}
export function currentVrIdentity(): VrIdentity {
  return {
    userId: Taro.getStorageSync(STORAGE_KEYS.userId) || "",
    token: Taro.getStorageSync(STORAGE_KEYS.token) || "",
  };
}
export function createVrClient(identity: VrIdentity) {
  const tasks = new Set<{ abort(): void }>();
  const cancellations = new Set<() => void>();
  let cancelled = false;
  const matches = () => {
    const now = currentVrIdentity();
    return (
      !cancelled &&
      now.userId === identity.userId &&
      now.token === identity.token
    );
  };
  async function send<T>(
    path: string,
    method: "GET" | "POST" | "PUT" | "DELETE" = "GET",
    data?: unknown,
  ): Promise<T> {
    if (!identity.userId || !identity.token)
      throw new VrRequestError("请先到「我的」登录，再连接头显。", 401);
    if (!matches()) throw new Error("用户已变化，请重新进入 VR 跟练。");
    return new Promise<T>((resolve, reject) => {
      let task: { abort(): void } | undefined;
      let settled = false;
      const finish = (error: Error | null, value?: T) => {
        if (settled) return;
        settled = true;
        cancellations.delete(cancel);
        if (task) tasks.delete(task);
        if (error) reject(error);
        else resolve(value as T);
      };
      const cancel = () => finish(new Error("请求已取消。"));
      cancellations.add(cancel);
      try {
        task = Taro.request({
          url: `${API_BASE}/vr${path}`,
          method,
          data,
          timeout: 15000,
          header: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${identity.token}`,
          },
          success: (response) => {
            if (!matches())
              return finish(new Error("用户已变化，请重新进入 VR 跟练。"));
            if (response.statusCode >= 200 && response.statusCode < 300)
              return finish(null, response.data as T);
            const detail = (response.data as { detail?: unknown })?.detail;
            finish(
              new VrRequestError(
                response.statusCode === 401
                  ? "登录已失效，请到「我的」重新登录。"
                  : typeof detail === "string"
                    ? detail
                    : `请求未完成（${response.statusCode}），请重试。`,
                response.statusCode,
              ),
            );
          },
          fail: (error) =>
            finish(
              new Error(
                /timeout/i.test(error?.errMsg || "")
                  ? "连接超时，请稍后重试。"
                  : "暂时无法访问服务，请检查连接后重试。",
              ),
            ),
          complete: () => {
            if (task) tasks.delete(task);
          },
        });
        if (!settled) tasks.add(task);
      } catch {
        finish(new Error("暂时无法访问服务，请检查连接后重试。"));
      }
    });
  }
  return {
    overview: async () => parseOverview(await send<unknown>("/overview")),
    pairing: async (includeToday: boolean) =>
      parsePairing(
        await send<unknown>("/pairings", "POST", {
          include_today_plan: includeToday,
        }),
      ),
    cancelPairing: () => send<void>("/pairings", "DELETE"),
    reference: async (enabled: boolean) =>
      parseConnection(
        await send<unknown>("/connection/reference", "PUT", { enabled }),
      ),
    disconnect: () => send<void>("/connection", "DELETE"),
    cancel: () => {
      cancelled = true;
      const active = [...tasks];
      [...cancellations].forEach((cancel) => cancel());
      active.forEach((task) => {
        try {
          task.abort();
        } catch {
          /* Already disposed by the platform. */
        }
      });
      tasks.clear();
    },
  };
}
