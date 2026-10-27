"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
} from "react";
import {
  AlertTriangle,
  BrainCircuit,
  Check,
  Clock3,
  FileVideo,
  Loader2,
  RotateCcw,
  ShieldCheck,
  UploadCloud,
  Video,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useUser } from "@/contexts/UserContext";
import {
  videoAnalysisApi,
  type VideoAnalysisResponse,
} from "@/lib/api";

const MAX_FILE_BYTES = 100 * 1024 * 1024;
const ACCEPTED_EXTENSIONS = [".mp4", ".mov", ".m4v", ".webm"];
const DEFAULT_QUESTION =
  "请检查我在整个视频中的运动动作是否有问题，以及是否存在可能增加受伤风险的动作模式。";

type AnalysisPhase = "idle" | "uploading" | "processing" | "success" | "error";

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(seconds: number): string {
  const safe = Math.max(0, seconds);
  const minutes = Math.floor(safe / 60);
  const rest = Math.floor(safe % 60);
  return minutes > 0
    ? `${minutes}:${String(rest).padStart(2, "0")}`
    : `${safe.toFixed(1)}s`;
}

function phaseLabel(phase: AnalysisPhase): string {
  if (phase === "uploading") return "正在上传视频";
  if (phase === "processing") return "正在理解视频并生成答复";
  return "";
}

export default function VideoAnalysisPage() {
  const { userId, profile } = useUser();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [phase, setPhase] = useState<AnalysisPhase>("idle");
  const [dragActive, setDragActive] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [result, setResult] = useState<VideoAnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const busy = phase === "uploading" || phase === "processing";

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    const timer = window.setInterval(
      () => setElapsedSeconds(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [busy]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
    },
    [],
  );

  const validateAndSelect = useCallback((candidate: File) => {
    const lower = candidate.name.toLowerCase();
    const hasAllowedExtension = ACCEPTED_EXTENSIONS.some((ext) =>
      lower.endsWith(ext),
    );
    if (!hasAllowedExtension) {
      setError("请选择 MP4、MOV、M4V 或 WebM 视频。");
      setPhase("error");
      return;
    }
    if (candidate.size <= 0) {
      setError("视频文件为空。");
      setPhase("error");
      return;
    }
    if (candidate.size > MAX_FILE_BYTES) {
      setError("视频超过 100 MB，请压缩或裁剪后再上传。");
      setPhase("error");
      return;
    }
    setFile(candidate);
    setResult(null);
    setError(null);
    setPhase("idle");
    setUploadProgress(0);
    setElapsedSeconds(0);
  }, []);

  const onFileInput = (event: ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0];
    if (selected) validateAndSelect(selected);
    event.target.value = "";
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
    if (busy) return;
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) validateAndSelect(dropped);
  };

  const reset = () => {
    if (busy) return;
    setFile(null);
    setResult(null);
    setError(null);
    setPhase("idle");
    setUploadProgress(0);
    setElapsedSeconds(0);
  };

  const submit = async () => {
    if (!file) {
      setError("请先选择一段运动视频。");
      setPhase("error");
      return;
    }
    if (!question.trim()) {
      setError("请输入希望教练结合视频回答的问题。");
      setPhase("error");
      return;
    }
    if (!userId.trim()) {
      setError("请先在顶部用户栏设置用户 ID。");
      setPhase("error");
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;
    setResult(null);
    setError(null);
    setUploadProgress(0);
    setElapsedSeconds(0);
    setPhase("uploading");

    try {
      const response = await videoAnalysisApi.analyze(
        {
          file,
          question: question.trim(),
          userId,
        },
        {
          signal: controller.signal,
          onUploadProgress: (percent) => {
            setUploadProgress(percent);
            if (percent >= 100) setPhase("processing");
          },
        },
      );
      setUploadProgress(100);
      setResult(response);
      setPhase("success");
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") {
        setError("已取消本次视频分析。");
      } else {
        setError(caught instanceof Error ? caught.message : "视频分析失败");
      }
      setPhase("error");
    } finally {
      abortRef.current = null;
    }
  };

  return (
    <div className="p-6 md:p-8 max-w-7xl mx-auto">
      <header className="mb-6 flex flex-col md:flex-row md:items-end md:justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span
              className="w-9 h-9 rounded-xl flex items-center justify-center"
              style={{ background: "rgba(108,99,255,0.12)", color: "var(--accent)" }}
            >
              <Video size={19} />
            </span>
            <h1 className="text-2xl font-bold" style={{ color: "var(--text)" }}>
              视频动作安全分析
            </h1>
          </div>
          <p className="text-sm" style={{ color: "var(--text-muted)" }}>
            V-Socrate 检索整段视频的动作证据，再由当前 AI 教练结合伤病档案回答
          </p>
        </div>
        <div
          className="text-xs px-3 py-2 rounded-lg border"
          style={{ color: "var(--text-muted)", borderColor: "var(--border)", background: "var(--surface)" }}
        >
          当前用户：<span className="font-mono" style={{ color: "var(--text)" }}>{userId}</span>
          {profile?.medical_history?.length
            ? ` · 已读取 ${profile.medical_history.length} 条伤病记录`
            : " · 暂无伤病记录"}
        </div>
      </header>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)] gap-6 items-start">
        <section className="dashboard-card p-5 md:p-6 space-y-5">
          <div>
            <h2 className="text-sm font-semibold mb-1" style={{ color: "var(--text)" }}>
              1. 上传运动视频
            </h2>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              支持 MP4、MOV、M4V、WebM，最大 100 MB。建议保留完整动作周期并确保关节可见。
            </p>
          </div>

          {!file ? (
            <div
              role="button"
              tabIndex={0}
              onClick={() => !busy && fileInputRef.current?.click()}
              onKeyDown={(event) => {
                if ((event.key === "Enter" || event.key === " ") && !busy) {
                  fileInputRef.current?.click();
                }
              }}
              onDragEnter={(event) => {
                event.preventDefault();
                setDragActive(true);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={(event) => {
                if (event.currentTarget === event.target) setDragActive(false);
              }}
              onDrop={onDrop}
              className="rounded-2xl border-2 border-dashed min-h-60 flex flex-col items-center justify-center text-center px-6 cursor-pointer transition-colors"
              style={{
                borderColor: dragActive ? "var(--accent)" : "var(--border)",
                background: dragActive ? "rgba(108,99,255,0.08)" : "var(--surface2)",
              }}
            >
              <div
                className="w-14 h-14 rounded-2xl flex items-center justify-center mb-4"
                style={{ background: "rgba(108,99,255,0.12)", color: "var(--accent)" }}
              >
                <UploadCloud size={27} />
              </div>
              <p className="text-sm font-semibold mb-1" style={{ color: "var(--text)" }}>
                拖入视频，或点击选择文件
              </p>
              <p className="text-xs max-w-sm" style={{ color: "var(--text-muted)" }}>
                尽量固定机位、光线充足，并从侧面或斜前方拍摄全身
              </p>
            </div>
          ) : (
            <div className="rounded-2xl overflow-hidden border" style={{ borderColor: "var(--border)" }}>
              {previewUrl && (
                <video
                  src={previewUrl}
                  controls
                  preload="metadata"
                  aria-label="待分析运动视频预览"
                  className="w-full max-h-[360px] bg-black object-contain"
                />
              )}
              <div
                className="flex items-center gap-3 px-4 py-3"
                style={{ background: "var(--surface2)" }}
              >
                <FileVideo size={18} style={{ color: "var(--accent)" }} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium truncate" style={{ color: "var(--text)" }}>
                    {file.name}
                  </p>
                  <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                    {formatBytes(file.size)}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={reset}
                  disabled={busy}
                  aria-label="移除视频"
                  className="p-2 rounded-lg disabled:opacity-40"
                  style={{ color: "var(--text-muted)" }}
                >
                  <X size={17} />
                </button>
              </div>
            </div>
          )}

          <input
            ref={fileInputRef}
            type="file"
            accept=".mp4,.mov,.m4v,.webm,video/mp4,video/quicktime,video/webm"
            onChange={onFileInput}
            className="hidden"
          />

          <div>
            <label htmlFor="video-question" className="block text-sm font-semibold mb-1.5" style={{ color: "var(--text)" }}>
              2. 你希望重点检查什么？
            </label>
            <textarea
              id="video-question"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              disabled={busy}
              rows={5}
              maxLength={4000}
              className="w-full rounded-xl px-3.5 py-3 text-sm border outline-none resize-y disabled:opacity-60"
              style={{
                color: "var(--text)",
                background: "var(--surface2)",
                borderColor: "var(--border)",
              }}
              placeholder="例如：请检查整个深蹲过程中有没有膝盖内扣、弯腰或重心不稳"
            />
            <div className="mt-2 flex flex-wrap gap-2">
              {[
                "整个视频中的动作有没有明显问题？",
                "这个动作可能增加哪些受伤风险？",
                "请重点检查膝盖、髋和躯干稳定性。",
              ].map((preset) => (
                <button
                  type="button"
                  key={preset}
                  disabled={busy}
                  onClick={() => setQuestion(preset)}
                  className="text-[11px] px-2.5 py-1.5 rounded-lg border disabled:opacity-50"
                  style={{
                    color: "var(--text-muted)",
                    borderColor: "var(--border)",
                    background: "var(--surface)",
                  }}
                >
                  {preset}
                </button>
              ))}
            </div>
          </div>

          <Button
            size="lg"
            fullWidth
            loading={busy}
            disabled={!file || !question.trim()}
            leftIcon={<BrainCircuit size={18} />}
            onClick={submit}
          >
            {busy ? phaseLabel(phase) : "开始分析"}
          </Button>

          {busy && (
            <button
              type="button"
              onClick={() => abortRef.current?.abort()}
              className="w-full text-xs text-center"
              style={{ color: "var(--text-muted)" }}
            >
              取消本次分析
            </button>
          )}

          <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-muted)" }}>
            原视频仅在本次请求期间临时保存，分析结束后删除。系统会保留特征缓存和问答记录，
            不会把结果当作医学诊断。
          </p>
        </section>

        <section className="min-h-[520px]">
          {phase === "idle" && !result && (
            <IdleState />
          )}

          {busy && (
            <ProcessingState
              phase={phase}
              progress={uploadProgress}
              elapsedSeconds={elapsedSeconds}
            />
          )}

          {phase === "error" && error && (
            <div className="dashboard-card p-6">
              <div
                className="w-11 h-11 rounded-xl flex items-center justify-center mb-4"
                style={{ background: "rgba(239,68,68,0.1)", color: "var(--danger)" }}
              >
                <AlertTriangle size={22} />
              </div>
              <h2 className="font-semibold mb-2" style={{ color: "var(--text)" }}>
                分析没有完成
              </h2>
              <p className="text-sm leading-relaxed mb-5" style={{ color: "var(--danger)" }}>
                {error}
              </p>
              <div className="flex gap-3">
                <Button
                  variant="secondary"
                  leftIcon={<RotateCcw size={15} />}
                  onClick={() => {
                    setError(null);
                    setPhase("idle");
                  }}
                >
                  返回修改
                </Button>
                {file && (
                  <Button leftIcon={<BrainCircuit size={15} />} onClick={submit}>
                    重新分析
                  </Button>
                )}
              </div>
            </div>
          )}

          {phase === "success" && result && (
            <AnalysisResult result={result} onReset={reset} />
          )}
        </section>
      </div>
    </div>
  );
}

function IdleState() {
  return (
    <div className="dashboard-card p-6 md:p-8">
      <div
        className="w-12 h-12 rounded-2xl flex items-center justify-center mb-5"
        style={{ background: "rgba(16,185,129,0.1)", color: "var(--success)" }}
      >
        <ShieldCheck size={24} />
      </div>
      <h2 className="text-lg font-semibold mb-2" style={{ color: "var(--text)" }}>
        分析将分两步完成
      </h2>
      <p className="text-sm mb-6 leading-relaxed" style={{ color: "var(--text-muted)" }}>
        视觉模型只负责找出画面证据；最终教练答复会进一步参考你的伤病史和训练记录，
        避免仅凭单帧画面直接下结论。
      </p>
      <div className="space-y-4">
        {[
          {
            n: "1",
            title: "V-Socrate 理解视频",
            text: "覆盖整段视频，检索完整动作周期并复核关键帧。",
          },
          {
            n: "2",
            title: "AI 教练评估风险",
            text: "当前配置的大模型结合用户档案回答问题；默认可使用 DeepSeek。",
          },
          {
            n: "3",
            title: "输出证据与限制",
            text: "给出可见问题、证据时间点，以及当前机位无法判断的部分。",
          },
        ].map((item) => (
          <div key={item.n} className="flex gap-3">
            <span
              className="w-7 h-7 shrink-0 rounded-lg flex items-center justify-center text-xs font-bold"
              style={{ background: "var(--surface2)", color: "var(--accent)" }}
            >
              {item.n}
            </span>
            <div>
              <p className="text-sm font-medium" style={{ color: "var(--text)" }}>{item.title}</p>
              <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{item.text}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ProcessingState({
  phase,
  progress,
  elapsedSeconds,
}: {
  phase: AnalysisPhase;
  progress: number;
  elapsedSeconds: number;
}) {
  const uploaded = phase === "processing";
  return (
    <div className="dashboard-card p-6 md:p-8">
      <div className="flex items-center gap-3 mb-6">
        <Loader2 size={25} className="animate-spin" style={{ color: "var(--accent)" }} />
        <div>
          <h2 className="font-semibold" style={{ color: "var(--text)" }}>{phaseLabel(phase)}</h2>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
            已等待 {elapsedSeconds}s，真实视频推理可能需要数分钟
          </p>
        </div>
      </div>

      <div className="mb-7">
        <div className="flex justify-between text-xs mb-1.5" style={{ color: "var(--text-muted)" }}>
          <span>{uploaded ? "视频上传完成" : "上传进度"}</span>
          <span>{uploaded ? "100%" : `${progress}%`}</span>
        </div>
        <div className="h-2 rounded-full overflow-hidden" style={{ background: "var(--surface2)" }}>
          <div
            className="h-full rounded-full transition-[width] duration-300"
            style={{ width: `${uploaded ? 100 : progress}%`, background: "var(--accent)" }}
          />
        </div>
      </div>

      <div className="space-y-4">
        <StageRow done={uploaded} active={!uploaded} label="安全上传临时视频" detail="完成后原视频会被删除" />
        <StageRow done={false} active={uploaded} label="V-Socrate 检索与复核动作帧" detail="分析完整动作周期和不同重复次数" />
        <StageRow done={false} active={false} label="AI 教练结合伤病档案作答" detail="使用当前 LLM Provider 生成最终建议" />
      </div>
    </div>
  );
}

function StageRow({
  done,
  active,
  label,
  detail,
}: {
  done: boolean;
  active: boolean;
  label: string;
  detail: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <span
        className="mt-0.5 w-7 h-7 shrink-0 rounded-full flex items-center justify-center"
        style={{
          background: done
            ? "rgba(16,185,129,0.12)"
            : active
              ? "rgba(108,99,255,0.12)"
              : "var(--surface2)",
          color: done ? "var(--success)" : active ? "var(--accent)" : "var(--text-muted)",
        }}
      >
        {done ? <Check size={15} /> : active ? <Loader2 size={14} className="animate-spin" /> : <Clock3 size={14} />}
      </span>
      <div>
        <p className="text-sm font-medium" style={{ color: "var(--text)" }}>{label}</p>
        <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{detail}</p>
      </div>
    </div>
  );
}

function AnalysisResult({
  result,
  onReset,
}: {
  result: VideoAnalysisResponse;
  onReset: () => void;
}) {
  const visual = result.video_analysis;
  return (
    <div className="space-y-4">
      {visual.mock && (
        <div
          className="rounded-xl border p-4 flex gap-3"
          style={{
            background: "rgba(245,158,11,0.09)",
            borderColor: "rgba(245,158,11,0.35)",
            color: "var(--warning)",
          }}
        >
          <AlertTriangle size={19} className="shrink-0 mt-0.5" />
          <p className="text-sm">
            当前是 Mock 模式，系统没有真正读取视频。请配置视觉模型后再用于动作判断。
          </p>
        </div>
      )}

      <div className="dashboard-card p-5 md:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
          <div>
            <p className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>视频理解结果</p>
            <h2 className="text-lg font-semibold" style={{ color: "var(--text)" }}>
              V-Socrate 可见证据
            </h2>
          </div>
          <div className="flex flex-wrap gap-2 text-[11px]">
            <span className="px-2.5 py-1 rounded-full" style={{ background: "var(--surface2)", color: "var(--text-muted)" }}>
              {visual.model}
            </span>
            <span className="px-2.5 py-1 rounded-full" style={{ background: "var(--surface2)", color: "var(--text-muted)" }}>
              视频 {formatTime(visual.duration_seconds)}
            </span>
            <span className="px-2.5 py-1 rounded-full" style={{ background: "var(--surface2)", color: "var(--text-muted)" }}>
              分析 {formatTime(visual.processing_seconds)}
            </span>
          </div>
        </div>

        <div className="space-y-4">
          <ResultBlock title="可见动作观察" text={visual.summary} />
          <ResultBlock title="证据与限制" text={visual.reason} />
          <div>
            <p className="text-xs font-semibold mb-2" style={{ color: "var(--text-muted)" }}>
              证据时间点
            </p>
            {visual.evidence_frames.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {visual.evidence_frames.map((frame) => (
                  <span
                    key={`${frame.frame_id}-${frame.timestamp_seconds}`}
                    className="text-xs px-2.5 py-1.5 rounded-lg border"
                    style={{
                      borderColor: "rgba(108,99,255,0.25)",
                      background: "rgba(108,99,255,0.07)",
                      color: "var(--accent-light)",
                    }}
                  >
                    {formatTime(frame.timestamp_seconds)} · 帧 {frame.frame_id}
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>无真实证据帧</p>
            )}
          </div>
        </div>
      </div>

      <div className="dashboard-card p-5 md:p-6">
        <div className="flex items-start gap-3 mb-4">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: "rgba(16,185,129,0.1)", color: "var(--success)" }}
          >
            <ShieldCheck size={20} />
          </div>
          <div>
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>
              {result.answer_model.provider} · {result.answer_model.model}
            </p>
            <h2 className="font-semibold" style={{ color: "var(--text)" }}>AI 教练答复</h2>
          </div>
        </div>
        <div
          className="text-sm leading-7 whitespace-pre-wrap"
          style={{ color: "var(--text)" }}
        >
          {result.assistant_message.content}
        </div>
      </div>

      <div
        className="rounded-xl border p-4 text-xs leading-relaxed"
        style={{
          background: "rgba(245,158,11,0.07)",
          borderColor: "rgba(245,158,11,0.25)",
          color: "var(--text-muted)",
        }}
      >
        {result.disclaimer}
      </div>

      <Button variant="secondary" leftIcon={<RotateCcw size={15} />} onClick={onReset}>
        分析另一段视频
      </Button>
    </div>
  );
}

function ResultBlock({ title, text }: { title: string; text: string }) {
  return (
    <div>
      <p className="text-xs font-semibold mb-1.5" style={{ color: "var(--text-muted)" }}>{title}</p>
      <p className="text-sm leading-6 whitespace-pre-wrap" style={{ color: "var(--text)" }}>{text}</p>
    </div>
  );
}
