/**
 * API client — wraps all FastAPI backend endpoints.
 * Base URL is read from NEXT_PUBLIC_API_URL (defaults to localhost:8000).
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ─── helpers ────────────────────────────────────────────────────────────────

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });
const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });

// ─── types ──────────────────────────────────────────────────────────────────

export interface BasicInfo {
  age: number;
  gender: string;
  height_cm?: number;
  weight_kg?: number;
  bmi?: number;
}

export interface MedicalHistoryItem {
  location: string;
  condition: string;
  severity: "low" | "medium" | "high";
  pain_trigger?: string;
  notes?: string;
}

export interface SafetyRevalidation {
  programs_scanned: number;
  programs_updated: number;
  plans_scanned: number;
  plans_updated: number;
  exercises_replaced: number;
  replacements: Array<{ context: string; from: string; to: string }>;
}

export interface UserProfile {
  user_id: string;
  basic_info: BasicInfo;
  fitness_level: "beginner" | "intermediate" | "advanced";
  fitness_goal?: string;
  training_frequency?: number;
  available_equipment?: string[];
  medical_history: MedicalHistoryItem[];
  created_at?: string;
  updated_at?: string;
  safety_revalidation?: SafetyRevalidation | null;
}

export interface TrainingSession {
  session_id: string;
  user_id: string;
  date: string;
  workout_type?: string;
  duration_minutes?: number;
  rpe: number;
  completion_rate?: number;
  pain_feedback: { has_pain: boolean; pain_location?: string; pain_severity?: number };
  fatigue_feedback?: { overall_fatigue?: number; sleep_quality_last_night?: number };
  notes?: string;
  program_id?: string;
  program_week?: number;
  created_at?: string;
}

export interface ProgramExercise {
  name: string;
  sets: number;
  reps: string;
  rest_seconds: number;
  intensity_note?: string;
  target_muscle?: string;
}

export interface ProgramSession {
  session_number: number;
  workout_type: string;
  label: string;
  estimated_duration_minutes: number;
  key_exercises: ProgramExercise[];
  notes?: string;
  phases?: WorkoutPhases;
  source_plan_id?: string;
}

export interface ProgramWeek {
  week_number: number;
  week_type?: string;
  actual_week_type?: string;
  label?: string;
  intensity_note?: string;
  volume_modifier?: number;
  status?: string;
  completed_sessions?: number;
  actual_avg_rpe?: number;
  adaptation_notes?: string[];
  sessions?: ProgramSession[];
}

export interface TrainingProgram {
  program_id: string;
  user_id: string;
  name: string;
  description?: string;
  status: string;
  goal: string;
  split_type: string;
  total_weeks: number;
  current_week: number;
  sessions_per_week: number;
  forbidden_exercise_count?: number;
  safe_exercise_count?: number;
  program_data?: Record<string, unknown>;
  weeks?: ProgramWeek[];
  created_at?: string;
  updated_at?: string;
}

export interface ActionRequest {
  tool: string;
  args: Record<string, unknown>;
  rationale: string;
  confirm_label: string;
}

export interface Message {
  id: number;
  role: "user" | "assistant" | "system";
  content: string;
  action_request?: ActionRequest | null;
  created_at?: string;
}

export interface Conversation {
  conversation_id: string;
  user_id: string;
  title: string;
  status: string;
  program_id?: string;
  created_at?: string;
  updated_at?: string;
  message_count?: number;
}

// Paginated list wrappers (FastAPI response models)
interface SessionListResponse {
  sessions: TrainingSession[];
}

interface ProgramListResponse {
  programs: TrainingProgram[];
}

interface ConversationListResponse {
  conversations: Conversation[];
}

export interface ChatSyncResponse {
  conversation_id: string;
  user_message: Message;
  assistant_message: Message;
  action_request?: ActionRequest | null;
}

export interface ConversationDetail extends Conversation {
  messages: Message[];
}

export interface AdvanceWeekResponse {
  program_id: string;
  adaptation_report: Record<string, unknown>;
  next_week?: ProgramWeek | null;
}

export interface NextSessionResponse {
  program_id: string;
  current_week: number;
  sessions_completed_this_week: number;
  sessions_planned_this_week: number;
  next_session: ProgramSession | null;
  message: string;
}

export interface RecommendationComponentScores {
  profile: number;
  behaviour: number;
  population: number;
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
  component_scores: RecommendationComponentScores;
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

export interface ExercisePerformance {
  name: string;
  weight_kg?: number;
  sets_completed?: number;
  reps_per_set?: number[];
  notes?: string;
}

export interface LogSessionRequest {
  session_id?: string;
  plan_id?: string;
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
    pain_type?: string;
    trigger_exercise?: string;
  };
  fatigue_feedback?: {
    overall_fatigue?: number;
    sleep_quality_last_night?: number;
    stress_level?: number;
  };
  exercise_performance?: ExercisePerformance[];
  notes?: string;
}

export interface UpdateUserRequest {
  basic_info?: BasicInfo;
  fitness_level?: string;
  fitness_goal?: string;
  training_frequency?: number;
  available_equipment?: string[];
  medical_history?: MedicalHistoryItem[];
}

// ─── users ──────────────────────────────────────────────────────────────────

export const usersApi = {
  get: (userId: string) => get<UserProfile>(`/users/${userId}`),

  create: (profile: Omit<UserProfile, "created_at" | "updated_at">) =>
    post<UserProfile>("/users", profile),

  update: (userId: string, body: UpdateUserRequest) =>
    put<UserProfile>(`/users/${userId}`, body),

  logSession: (userId: string, body: LogSessionRequest) =>
    post<TrainingSession>(`/users/${userId}/sessions`, body),

  sessions: async (userId: string): Promise<TrainingSession[]> => {
    const data = await get<SessionListResponse>(`/users/${userId}/sessions`);
    return data.sessions ?? [];
  },

  latestSession: (userId: string) =>
    get<TrainingSession>(`/users/${userId}/sessions/latest`),

  programs: async (userId: string): Promise<TrainingProgram[]> => {
    const data = await get<ProgramListResponse>(`/users/${userId}/programs`);
    return data.programs ?? [];
  },

  conversations: async (userId: string): Promise<Conversation[]> => {
    const data = await get<ConversationListResponse>(`/users/${userId}/conversations`);
    return data.conversations ?? [];
  },
};

// ─── chat ───────────────────────────────────────────────────────────────────

export interface StartChatRequest {
  user_id: string;
  message: string;
  conversation_id?: string;
  title?: string;
}

export const chatApi = {
  send: (body: StartChatRequest) => post<ChatSyncResponse>("/chat", body),

  getConversation: async (cid: string): Promise<{ conversation: Conversation; messages: Message[] }> => {
    const detail = await get<ConversationDetail>(`/conversations/${cid}`);
    const { messages, ...conversation } = detail;
    return { conversation, messages: messages ?? [] };
  },

  rename: (cid: string, title: string) =>
    patch<Conversation>(`/conversations/${cid}/title`, { title }),

  archive: (cid: string) =>
    patch<Conversation>(`/conversations/${cid}/archive`, {}),

  /** SSE stream URL for a new or continuing conversation */
  streamUrl: (conversationId?: string | null) =>
    conversationId
      ? `${BASE}/conversations/${conversationId}/messages/stream`
      : `${BASE}/chat/stream`,
};

// ─── programs ───────────────────────────────────────────────────────────────

export const programsApi = {
  get: (pid: string) => get<TrainingProgram>(`/programs/${pid}`),

  nextSession: (pid: string) => get<NextSessionResponse>(`/programs/${pid}/next-session`),

  generate: (body: {
    user_profile: Omit<UserProfile, "created_at" | "updated_at">;
    goal: string;
    total_weeks: number;
    sessions_per_week: number;
    split_type?: string;
    use_history?: boolean;
  }) => post<TrainingProgram>("/programs/generate", body),

  advance: (pid: string) =>
    post<AdvanceWeekResponse>(`/programs/${pid}/advance`, {}),
};

// ─── training-plan recommendations ──────────────────────────────────────────

export const recommendationsApi = {
  plans: (userId: string, limit = 6) =>
    get<PlanRecommendationResponse>(
      `/users/${encodeURIComponent(userId)}/plan-recommendations?limit=${limit}`
    ),
};

// ─── insights: readiness + progression (Sprint 4) ────────────────────────────

export interface ReadinessFactor {
  label: string;
  value: string;
  score: number;
  status: "good" | "ok" | "bad";
}

export interface ReadinessResponse {
  user_id: string;
  score: number | null;
  band: "prime" | "ready" | "caution" | "rest" | "unknown";
  label: string;
  recommendation: string;
  suggested_intensity_modifier: number;
  based_on_sessions: number;
  factors: ReadinessFactor[];
}

export interface NextSetSuggestion {
  suggested_weight_kg?: number | null;
  suggested_reps: string;
  action: "increase_load" | "increase_reps" | "hold" | "deload" | "start";
  rationale: string;
  last_weight_kg?: number | null;
  last_reps?: number[] | null;
  est_1rm?: number | null;
  trend: "increasing" | "stable" | "decreasing" | "unknown";
}

export interface ExerciseProgressionReport {
  exercise_name: string;
  sessions_tracked: number;
  current_weight_kg?: number | null;
  best_est_1rm?: number | null;
  est_1rm_change_kg?: number | null;
  trend: string;
  last_date?: string | null;
  history: Array<{ date?: string; weight_kg?: number | null; reps_per_set: number[]; est_1rm?: number | null }>;
  suggestion: NextSetSuggestion;
}

export interface ProgressionResponse {
  user_id: string;
  goal: string;
  tracked_exercises: number;
  reports: ExerciseProgressionReport[];
}

export const insightsApi = {
  readiness: (userId: string) =>
    get<ReadinessResponse>(`/users/${userId}/readiness`),

  progression: (userId: string) =>
    get<ProgressionResponse>(`/users/${userId}/progression`),
};

export { BASE as API_BASE };

// ─── Plan generation (Streamlit Tab 1) ─────────────────────────────────────

export interface PlanExercise {
  name: string;
  /** 后端给出的中文名；缺省时前端回退到 EXERCISE_CN 映射表 */
  name_zh?: string | null;
  sets: number;
  reps: string;
  rest_seconds: number;
  notes?: string;
  target_muscle?: string;
}

export interface WorkoutPhases {
  warm_up: PlanExercise[];
  activation: PlanExercise[];
  main_lifts: PlanExercise[];
  accessories: PlanExercise[];
  cool_down: PlanExercise[];
}

export interface GeneratePlanResponse {
  plan_id: string;
  user_id: string;
  date: string;
  workout_type: string;
  estimated_duration_minutes: number;
  phases: WorkoutPhases;
  safety_notes: string[];
  risk_analysis: {
    forbidden_exercises: Array<{
      name: string;
      reason: string;
      substitution: string;
    }>;
    safe_exercise_count: number;
    constraints: string[];
  };
  generated_at: string;
  generator_version: string;
  program_id?: string;
}

export interface GeneratePlanRequest {
  user_profile: UserProfile;
  feedback?: {
    user_id: string;
    rpe: number;
    pain_feedback: { has_pain: boolean; pain_location?: string; pain_severity?: number; pain_type?: string; trigger_exercise?: string };
    fatigue_feedback?: { overall_fatigue?: number; sleep_quality_last_night?: number };
  } | null;
  workout_type: string;
}

export const plansApi = {
  generate: (body: GeneratePlanRequest, opts?: { save_to_db?: boolean; use_history?: boolean }) => {
    const params = new URLSearchParams();
    if (opts?.save_to_db) params.set("save_to_db", "true");
    if (opts?.use_history) params.set("use_history", "true");
    const qs = params.toString();
    return post<GeneratePlanResponse>(`/generate_plan${qs ? `?${qs}` : ""}`, body);
  },
};

// ─── Risk analysis (Streamlit Tab 2) ────────────────────────────────────────

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

export const riskApi = {
  analyze: (profile: UserProfile) => post<RiskAnalysisResult>("/analyze_risk", profile),
};

// ─── Exercise database (Streamlit Tab 3) ────────────────────────────────────

export interface ExerciseRecord {
  id: number;
  name: string;
  /** 后端权威中文名；缺省时前端回退到 EXERCISE_CN 映射表 */
  name_zh?: string;
  type: string;
  /** 适配的阶段：warm_up / activation / main_lifts / accessories / cool_down */
  phase?: string[];
  target_muscle: string;
  involved_joints: string[];
  risk_level: number;
  substitution?: string;
  has_guide?: boolean;
  image_url?: string | null;
  animation_frames?: string[];
}

export interface ExerciseListResponse {
  count: number;
  exercises: ExerciseRecord[];
}

export interface ExerciseGuideMeta {
  name: string;
  image_url: string | null;
  animation_frames: string[];
  technique_cn: string[];
  has_guide: boolean;
}

export interface ExerciseGuideMetaResponse {
  count: number;
  guides: Record<string, ExerciseGuideMeta>;
}

export const exercisesApi = {
  list: (opts?: { muscle_group?: string; exercise_type?: string; max_risk_level?: number }) => {
    const params = new URLSearchParams();
    if (opts?.muscle_group) params.set("muscle_group", opts.muscle_group);
    if (opts?.exercise_type) params.set("exercise_type", opts.exercise_type);
    if (opts?.max_risk_level) params.set("max_risk_level", String(opts.max_risk_level));
    const qs = params.toString();
    return get<ExerciseListResponse>(`/exercises${qs ? `?${qs}` : ""}`);
  },
  guideMeta: (name?: string) =>
    get<ExerciseGuideMetaResponse | ExerciseGuideMeta>(
      name ? `/exercises/guide-meta?name=${encodeURIComponent(name)}` : "/exercises/guide-meta"
    ) as Promise<ExerciseGuideMetaResponse>,
};

// ─── Video exercise analysis (multipart upload) ─────────────────────────────

export interface VideoEvidenceFrame {
  frame_id: number;
  timestamp_seconds: number;
}

export interface VideoUnderstandingResult {
  model: string;
  summary: string;
  reason: string;
  evidence_frames: VideoEvidenceFrame[];
  duration_seconds: number;
  processing_seconds: number;
  mock: boolean;
}

export interface VideoAnalysisResponse {
  analysis_id: string;
  conversation_id: string;
  video_analysis: VideoUnderstandingResult;
  answer_model: { provider: string; model: string };
  user_message: Message;
  assistant_message: Message;
  action_request?: ActionRequest | null;
  disclaimer: string;
}

export interface VideoAnalysisRequest {
  file: File;
  question: string;
  userId: string;
  conversationId?: string;
}

function fastApiError(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg: unknown }).msg);
        }
        return String(item);
      })
      .join("；");
  }
  return fallback;
}

export const videoAnalysisApi = {
  analyze: (
    body: VideoAnalysisRequest,
    options?: {
      onUploadProgress?: (percent: number) => void;
      signal?: AbortSignal;
    },
  ): Promise<VideoAnalysisResponse> =>
    new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("file", body.file);
      form.append("question", body.question);
      form.append("user_id", body.userId);
      if (body.conversationId) {
        form.append("conversation_id", body.conversationId);
      }

      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE}/video-analysis`);
      xhr.responseType = "json";

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          options?.onUploadProgress?.(
            Math.min(100, Math.round((event.loaded / event.total) * 100)),
          );
        }
      };
      xhr.upload.onload = () => options?.onUploadProgress?.(100);
      xhr.onload = () => {
        const payload = xhr.response as unknown;
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(payload as VideoAnalysisResponse);
          return;
        }
        reject(
          new Error(
            fastApiError(payload, `视频分析失败（HTTP ${xhr.status}）`),
          ),
        );
      };
      xhr.onerror = () => reject(new Error("无法连接视频分析服务，请确认后端已启动。"));
      xhr.onabort = () => reject(new DOMException("视频分析已取消", "AbortError"));

      const abort = () => xhr.abort();
      if (options?.signal) {
        if (options.signal.aborted) {
          abort();
          return;
        }
        options.signal.addEventListener("abort", abort, { once: true });
      }
      xhr.onloadend = () => options?.signal?.removeEventListener("abort", abort);
      xhr.send(form);
    }),
};
