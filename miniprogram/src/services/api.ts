import Taro from "@tarojs/taro";
import { ApiError, request } from "../utils/request";
import { API_BASE, STORAGE_KEYS } from "../utils/config";

export interface AuthLoginResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  is_new_user: boolean;
  mode: "wechat" | "dev";
}

export interface BasicInfo {
  age: number;
  gender: string;
  height_cm?: number;
  weight_kg?: number;
}

export interface MedicalHistoryItem {
  location: string;
  condition: string;
  severity: string;
  pain_trigger?: string;
  notes?: string;
}

export interface UserProfile {
  user_id: string;
  basic_info: BasicInfo;
  fitness_level: string;
  fitness_goal?: string;
  training_frequency?: number;
  available_equipment?: string[];
  medical_history: MedicalHistoryItem[];
  safety_revalidation?: {
    programs_updated?: number;
    plans_updated?: number;
    exercises_replaced?: number;
  } | null;
}

export interface ProgramExercise {
  name: string;
  sets: number;
  reps: string;
  rest_seconds: number;
  intensity_note?: string;
  target_muscle?: string;
}

export interface NextSessionResponse {
  program_id: string;
  program_status: string;
  current_week: number;
  total_weeks: number;
  next_session: {
    session_number: number;
    workout_type: string;
    label: string;
    estimated_duration_minutes: number;
    key_exercises: ProgramExercise[];
    notes?: string;
  } | null;
  message?: string;
  sessions_completed_this_week?: number;
  sessions_planned_this_week?: number;
}

export interface TrainingProgram {
  program_id: string;
  user_id: string;
  goal: string;
  name?: string;
  total_weeks: number;
  current_week: number;
  status: string;
  sessions_per_week?: number;
}

export interface RecommendedPlan {
  rank: number;
  template_id: string;
  name: string;
  description: string;
  goal: string;
  goal_label: string;
  split_type: string;
  split_label: string;
  total_weeks: number;
  sessions_per_week: number;
  difficulty: string;
  difficulty_label: string;
  estimated_duration_minutes: number;
  focus_areas: string[];
  required_equipment: string[];
  score: number;
  component_scores: {
    profile: number;
    behaviour: number;
    population: number;
  };
  match_reasons: string[];
  cautions: string[];
  safe_exercise_count: number;
  forbidden_exercise_count: number;
}

export interface PlanRecommendationResponse {
  user_id: string;
  generated_at: string;
  model: {
    name: string;
    version: string;
    weights: Record<string, number>;
  };
  user_snapshot: {
    goal: string;
    goal_label: string;
    fitness_level: string;
    training_frequency: number;
    available_equipment: string[];
    injury_count: number;
    session_count: number;
    average_completion_rate: number | null;
    average_rpe: number | null;
    actual_sessions_per_week: number | null;
    pain_locations: string[];
  };
  recommendations: RecommendedPlan[];
}

export interface TrainingSession {
  session_id: string;
  user_id: string;
  date: string;
  workout_type?: string;
  duration_minutes?: number;
  rpe: number;
  completion_rate?: number;
  pain_feedback?: { has_pain?: boolean; pain_location?: string };
  notes?: string;
}

export interface ChatPlanExercise {
  name: string;
  name_zh?: string;
  sets?: number;
  reps?: string | number;
  rest_seconds?: number;
  load_pct?: number;
  notes?: string;
  target_muscle?: string;
}

export interface ChatPlan {
  plan_id: string;
  user_id?: string;
  workout_type: string;
  estimated_duration_minutes: number;
  phases: Record<string, ChatPlanExercise[]>;
  safety_notes?: string[];
  generator_version?: string;
  date?: string;
}

export interface ChatSafety {
  passed: boolean;
  review_mode?: string;
  llm_verdict?: string;
  reviewer_note?: string;
  checked_slots?: number;
  violations?: Array<{ code: string; detail?: string; exercise_id?: number }>;
  risk_level?: string;
  clearance?: string;
  risk_summary?: string;
}

/** 这一轮跑了哪几个 Agent —— 让「到底过没过审查」在前端也看得见 */
export interface ChatAgentTrace {
  agents: string[];
  elapsed_ms?: number;
  stage_ms?: Record<string, number>;
  review_rounds?: number;
  revision_applied?: boolean;
}

export interface ChatSyncResponse {
  conversation_id: string;
  user_message: { id: number; role: string; content: string };
  assistant_message: { id: number; role: string; content: string };
  plan?: ChatPlan | null;
  safety?: ChatSafety | null;
  agent_trace?: ChatAgentTrace | null;
  intent?: string;
}

export interface VideoEvidenceFrame {
  frame_id: number;
  timestamp_seconds: number;
}

export interface VideoAnalysisResponse {
  analysis_id: string;
  conversation_id: string;
  video_analysis: {
    model: string;
    summary: string;
    reason: string;
    evidence_frames: VideoEvidenceFrame[];
    duration_seconds: number;
    processing_seconds: number;
    mock: boolean;
  };
  answer_model: {
    provider: string;
    model: string;
  };
  user_message: { id: number; role: string; content: string };
  assistant_message: { id: number; role: string; content: string };
  disclaimer: string;
}

export interface ExerciseRecord {
  id: number;
  name: string;
  type: string;
  target_muscle: string;
  involved_joints?: string[];
  risk_level: number;
  substitution?: string;
  has_guide?: boolean;
  image_url?: string | null;
  animation_frames?: string[];
}

export interface ExerciseGuideMeta {
  name: string;
  image_url: string | null;
  animation_frames: string[];
  technique_cn: string[];
  has_guide: boolean;
}

export interface PlanExercise {
  name: string;
  sets: number;
  reps: string;
  rest_seconds: number;
  notes?: string;
  target_muscle?: string;
}

export interface GeneratePlanResponse {
  plan_id: string;
  user_id: string;
  date: string;
  workout_type: string;
  estimated_duration_minutes: number;
  phases: {
    warm_up: PlanExercise[];
    activation: PlanExercise[];
    main_lifts: PlanExercise[];
    accessories: PlanExercise[];
    cool_down: PlanExercise[];
  };
  safety_notes: string[];
  risk_analysis?: {
    forbidden_exercises: Array<{ name: string; reason: string; substitution: string }>;
    safe_exercise_count: number;
  };
  program_id?: string;
}

export interface RiskAnalysisResult {
  user_id: string;
  summary: { total_exercises: number; forbidden_count: number; safe_count: number };
  forbidden_exercises: Array<{
    name: string;
    reason: string;
    risk_level: number;
    involved_joints: string[];
    substitution: string;
  }>;
  safe_exercises: string[];
}

export interface ExercisePerformance {
  name: string;
  weight_kg?: number;
  sets_completed?: number;
  reps_per_set?: number[];
  notes?: string;
}

export interface LogSessionRequest {
  program_id?: string;
  program_week?: number;
  date?: string;
  workout_type?: string;
  duration_minutes?: number;
  rpe: number;
  completion_rate?: number;
  pain_feedback: {
    has_pain: boolean;
    pain_location?: string;
    pain_severity?: number;
    trigger_exercise?: string;
  };
  fatigue_feedback?: { overall_fatigue?: number };
  exercise_performance?: ExercisePerformance[];
  notes?: string;
}

export interface ActiveWorkout {
  userId: string;
  programId?: string;
  programWeek?: number;
  workoutType: string;
  label: string;
  startedAt: number;
  exercises: ProgramExercise[];
}

export const WORKOUT_STORAGE_KEY = "ai_train_active_workout";

export function getStoredUserId(): string {
  return Taro.getStorageSync(STORAGE_KEYS.userId) || "";
}

export function saveAuth(token: string, userId: string) {
  Taro.setStorageSync(STORAGE_KEYS.token, token);
  Taro.setStorageSync(STORAGE_KEYS.userId, userId);
}

export function clearAuth() {
  Taro.removeStorageSync(STORAGE_KEYS.token);
  Taro.removeStorageSync(STORAGE_KEYS.userId);
}

export async function devLogin(userId = "usr_demo"): Promise<AuthLoginResponse> {
  const data = await request<AuthLoginResponse>("/auth/dev-login", {
    method: "POST",
    data: { user_id: userId },
    auth: false,
  });
  saveAuth(data.access_token, data.user_id);
  return data;
}

export async function wechatLogin(): Promise<AuthLoginResponse> {
  const loginRes = await Taro.login();
  if (!loginRes.code) throw new Error("wx.login 未返回 code");
  const data = await request<AuthLoginResponse>("/auth/wechat/login", {
    method: "POST",
    data: { code: loginRes.code },
    auth: false,
  });
  saveAuth(data.access_token, data.user_id);
  return data;
}

export async function ensureLoggedIn(): Promise<string> {
  const existing = getStoredUserId();
  if (existing) return existing;
  const data = await devLogin("usr_demo");
  return data.user_id;
}

export function saveActiveWorkout(workout: ActiveWorkout) {
  Taro.setStorageSync(WORKOUT_STORAGE_KEY, workout);
}

export function loadActiveWorkout(): ActiveWorkout | null {
  return (Taro.getStorageSync(WORKOUT_STORAGE_KEY) as ActiveWorkout) || null;
}

export function clearActiveWorkout() {
  Taro.removeStorageSync(WORKOUT_STORAGE_KEY);
}

export function parseDefaultReps(reps: string): number {
  const nums = String(reps || "")
    .match(/\d+/g)
    ?.map(Number)
    .filter((n) => !Number.isNaN(n));
  if (!nums || nums.length === 0) return 10;
  if (nums.length === 1) return nums[0];
  return Math.round((nums[0] + nums[1]) / 2);
}

async function uploadVideoAnalysis(
  filePath: string,
  body: {
    user_id: string;
    question: string;
    conversation_id?: string;
  }
): Promise<VideoAnalysisResponse> {
  const token = Taro.getStorageSync(STORAGE_KEYS.token) || "";
  const header: Record<string, string> = {};
  if (token) header.Authorization = `Bearer ${token}`;

  let upload: Taro.uploadFile.SuccessCallbackResult;
  try {
    upload = await Taro.uploadFile({
      url: `${API_BASE}/video-analysis`,
      filePath,
      name: "file",
      header,
      formData: {
        user_id: body.user_id,
        question: body.question,
        ...(body.conversation_id
          ? { conversation_id: body.conversation_id }
          : {}),
      },
      // V-Socrate 会覆盖完整视频并多轮复核，真实推理通常超过普通请求的 20 秒。
      timeout: 10 * 60 * 1000,
    });
  } catch (e: any) {
    const detail = e?.errMsg || e?.message || "uploadFile:fail";
    throw new Error(`视频上传或分析连接失败：${String(detail).slice(0, 80)}`);
  }

  let parsed: any;
  try {
    parsed =
      typeof upload.data === "string" ? JSON.parse(upload.data) : upload.data;
  } catch {
    throw new Error("视频分析服务返回了无法解析的数据。");
  }

  if (upload.statusCode < 200 || upload.statusCode >= 300) {
    const detail =
      typeof parsed?.detail === "string"
        ? parsed.detail
        : JSON.stringify(parsed?.detail ?? parsed ?? {});
    throw new ApiError(upload.statusCode, detail);
  }
  if (!parsed?.video_analysis || !parsed?.assistant_message?.content) {
    throw new Error("视频分析结果缺少必要字段。");
  }
  return parsed as VideoAnalysisResponse;
}

export const api = {
  getUser: (userId: string) => request<UserProfile>(`/users/${userId}`),

  createUser: (profile: Partial<UserProfile> & { user_id: string; basic_info: BasicInfo }) =>
    request<UserProfile>("/users", { method: "POST", data: profile }),

  updateUser: (userId: string, body: Partial<UserProfile>) =>
    request<UserProfile>(`/users/${userId}`, { method: "PUT", data: body }),

  listPrograms: async (userId: string) => {
    const data = await request<{ programs: TrainingProgram[] }>(
      `/users/${userId}/programs`
    );
    return data.programs ?? [];
  },

  planRecommendations: (userId: string, limit = 6) =>
    request<PlanRecommendationResponse>(
      `/users/${encodeURIComponent(userId)}/plan-recommendations?limit=${limit}`
    ),

  listSessions: async (userId: string) => {
    const data = await request<{ sessions: TrainingSession[] }>(
      `/users/${userId}/sessions`
    );
    return data.sessions ?? [];
  },

  nextSession: (programId: string) =>
    request<NextSessionResponse>(`/programs/${programId}/next-session`),

  generateProgram: (body: {
    user_profile: Record<string, unknown>;
    goal: string;
    total_weeks: number;
    sessions_per_week: number;
    split_type?: string;
    use_history?: boolean;
  }) => request<TrainingProgram>("/programs/generate", { method: "POST", data: body }),

  advanceProgram: (programId: string) =>
    request(`/programs/${programId}/advance`, { method: "POST", data: {} }),

  generatePlan: (
    body: {
      user_profile: Record<string, unknown>;
      workout_type: string;
      feedback?: Record<string, unknown> | null;
    },
    opts?: { save_to_db?: boolean; use_history?: boolean }
  ) => {
    const params: string[] = [];
    if (opts?.save_to_db) params.push("save_to_db=true");
    if (opts?.use_history) params.push("use_history=true");
    const qs = params.length ? `?${params.join("&")}` : "";
    return request<GeneratePlanResponse>(`/generate_plan${qs}`, {
      method: "POST",
      data: body,
      // 三 Agent 链路（风险报告 → 生成 → 审查，可能还有一轮重写）
      // 实测 60-90 秒，默认 20 秒必然超时。
      timeout: 180000,
    });
  },

  analyzeRisk: (profile: Record<string, unknown>) =>
    request<RiskAnalysisResult>("/analyze_risk", { method: "POST", data: profile }),

  chat: (body: {
    user_id: string;
    message: string;
    conversation_id?: string;
  }) =>
    request<ChatSyncResponse>("/chat", {
      method: "POST",
      data: body,
      // 问答：命中伤病时先跑一次 state_risk，实测 11-40 秒。
      // 生成/修改计划：对话里要计划会直接跑三个 Agent，实测 60-100 秒。
      timeout: 240000,
    }),

  analyzeVideo: uploadVideoAnalysis,

  readiness: (userId: string) =>
    request<{
      score: number | null;
      band: string;
      label: string;
      recommendation: string;
    }>(`/users/${userId}/readiness`),

  progression: (userId: string) =>
    request<{
      tracked_exercises: number;
      reports: Array<{
        exercise_name: string;
        trend: string;
        suggestion: { action: string; rationale: string; suggested_reps: string };
      }>;
    }>(`/users/${userId}/progression`),

  logSession: (userId: string, body: LogSessionRequest) =>
    request(`/users/${userId}/sessions`, { method: "POST", data: body }),

  listExercises: async (opts?: {
    muscle_group?: string;
    exercise_type?: string;
    max_risk_level?: number;
  }) => {
    const params = new URLSearchParams();
    if (opts?.muscle_group) params.set("muscle_group", opts.muscle_group);
    if (opts?.exercise_type) params.set("exercise_type", opts.exercise_type);
    if (opts?.max_risk_level) params.set("max_risk_level", String(opts.max_risk_level));
    const qs = params.toString();
    const data = await request<{ exercises: ExerciseRecord[] }>(
      `/exercises${qs ? `?${qs}` : ""}`
    );
    return data.exercises ?? [];
  },

  guideMeta: (name: string) =>
    request<ExerciseGuideMeta>(
      `/exercises/guide-meta?name=${encodeURIComponent(name)}`
    ),
};
