/** Independent VR API. No polling, subscriptions, or shared login-state changes. */
import { API_BASE } from "@/lib/api";
import { parseConnection, parseOverview, parsePairing } from "./validation";

export interface ReferencePlan {
  title: string;
  source_program_id: string;
  source_week: number;
  estimated_duration_minutes?: number | null;
  phases?: Record<
    string,
    { name: string; sets: number; reps: string }[]
  > | null;
  key_exercises: { name: string; sets: number; reps: string }[];
  advisory_only: true;
  vr_schedule_authoritative: true;
}

export interface Connection {
  id: string;
  device_name: string;
  connected_at: number;
  reference: ReferencePlan | null;
  reference_updated_at: number | null;
}

export interface ActionResult {
  action_id: string;
  action_name: string;
  completed_sets: number | null;
  completed_reps: number | null;
  duration_seconds: number | null;
  quality_score_01: number | null;
  tracking_good_ratio_01: number | null;
}

export interface TrainingResult {
  id: string;
  client_session_id: string;
  started_at: string;
  ended_at: string;
  outcome: "completed" | "stopped";
  actions: ActionResult[];
  received_at: number;
}

export interface Overview {
  connection: Connection | null;
  pairing: {
    id: string;
    expires_at: number;
    reference: ReferencePlan | null;
  } | null;
  today_reference: ReferencePlan | null;
  results: TrainingResult[];
}

async function request<T>(
  path: string,
  init: RequestInit,
  signal: AbortSignal,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal.aborted) controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, 15000);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      cache: "no-store",
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(
        typeof body?.detail === "string"
          ? body.detail
          : `请求未完成（${response.status}），请重试。`,
      );
    }
    if (response.status === 204) return undefined as T;
    return await response.json();
  } catch (error) {
    if (controller.signal.aborted && !signal.aborted)
      throw new Error("连接超时，请确认后端服务可访问后重试。");
    if (error instanceof TypeError)
      throw new Error("暂时无法访问服务，请检查连接后重试。");
    if (error instanceof SyntaxError)
      throw new Error("服务返回的数据无法读取，请刷新后重试。");
    throw error;
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}

async function authorized<T>(
  userId: string,
  path: string,
  signal: AbortSignal,
  init: RequestInit = {},
): Promise<T> {
  // The local prototype login initializes a minimal user record when needed.
  // VR pairing requires an account, not a completed training profile or plan.
  // Tokens live only for this request chain; switching user aborts the chain.
  const login = await request<{ access_token: string; user_id: string }>(
    "/auth/dev-login",
    {
      method: "POST",
      body: JSON.stringify({ user_id: userId }),
    },
    signal,
  );
  if (login.user_id !== userId) throw new Error("用户状态已变化，请刷新页面。");
  return request<T>(
    path,
    {
      ...init,
      headers: { Authorization: `Bearer ${login.access_token}` },
    },
    signal,
  );
}

export const vrApi = {
  overview: async (uid: string, signal: AbortSignal) =>
    parseOverview(await authorized<unknown>(uid, "/vr/overview", signal)),
  pairing: async (uid: string, includeToday: boolean, signal: AbortSignal) =>
    parsePairing(
      await authorized<unknown>(uid, "/vr/pairings", signal, {
        method: "POST",
        body: JSON.stringify({ include_today_plan: includeToday }),
      }),
    ),
  cancelPairing: (uid: string, signal: AbortSignal) =>
    authorized<void>(uid, "/vr/pairings", signal, { method: "DELETE" }),
  reference: async (uid: string, enabled: boolean, signal: AbortSignal) =>
    parseConnection(
      await authorized<unknown>(uid, "/vr/connection/reference", signal, {
        method: "PUT",
        body: JSON.stringify({ enabled }),
      }),
    ),
  disconnect: (uid: string, signal: AbortSignal) =>
    authorized<void>(uid, "/vr/connection", signal, { method: "DELETE" }),
};
