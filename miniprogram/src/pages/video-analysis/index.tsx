import { useEffect, useState } from "react";
import { Text, Textarea, Video, View } from "@tarojs/components";
import Taro from "@tarojs/taro";
import {
  api,
  ensureLoggedIn,
  type VideoAnalysisResponse,
} from "../../services/api";
import "./index.scss";

const MAX_FILE_BYTES = 100 * 1024 * 1024;
const DEFAULT_QUESTION =
  "请检查我在整个视频中的运动动作是否有问题，以及是否存在可能增加受伤风险的动作模式。";

const QUICK_QUESTIONS = [
  "整个视频中的动作有没有明显问题？",
  "这个动作可能增加哪些受伤风险？",
  "请重点检查膝盖、髋和躯干稳定性。",
];

type Phase = "idle" | "working" | "success" | "error";

interface SelectedVideo {
  path: string;
  size: number;
  duration: number;
  name: string;
}

function formatBytes(bytes: number): string {
  if (!bytes) return "大小未知";
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(seconds: number): string {
  const safe = Math.max(0, Number(seconds) || 0);
  if (safe < 60) return `${safe.toFixed(1)} 秒`;
  const minutes = Math.floor(safe / 60);
  return `${minutes}:${String(Math.floor(safe % 60)).padStart(2, "0")}`;
}

export default function VideoAnalysisPage() {
  const [video, setVideo] = useState<SelectedVideo | null>(null);
  const [question, setQuestion] = useState(DEFAULT_QUESTION);
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [result, setResult] = useState<VideoAnalysisResponse | null>(null);
  const [error, setError] = useState("");

  const busy = phase === "working";

  useEffect(() => {
    if (!busy) return;
    const startedAt = Date.now();
    setElapsedSeconds(0);
    const timer = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(timer);
  }, [busy]);

  const chooseVideo = async () => {
    if (busy) return;
    try {
      const selected = await Taro.chooseMedia({
        count: 1,
        mediaType: ["video"],
        sourceType: ["album", "camera"],
        maxDuration: 60,
        camera: "back",
      });
      const item = selected.tempFiles?.[0];
      if (!item?.tempFilePath) return;

      const size = Number(item.size || 0);
      if (size > MAX_FILE_BYTES) {
        Taro.showToast({
          title: "视频超过 100 MB，请先压缩或裁剪",
          icon: "none",
          duration: 2600,
        });
        return;
      }
      const name =
        item.tempFilePath.split("/").pop()?.split("?")[0] || "exercise.mp4";
      setVideo({
        path: item.tempFilePath,
        size,
        duration: Number(item.duration || 0),
        name,
      });
      setResult(null);
      setError("");
      setPhase("idle");
    } catch (e: any) {
      const message = String(e?.errMsg || e?.message || e || "");
      if (!message.toLowerCase().includes("cancel")) {
        Taro.showToast({ title: "选择视频失败", icon: "none" });
      }
    }
  };

  const submit = async () => {
    if (!video) {
      Taro.showToast({ title: "请先拍摄或选择视频", icon: "none" });
      return;
    }
    const cleanQuestion = question.trim();
    if (!cleanQuestion) {
      Taro.showToast({ title: "请输入需要分析的问题", icon: "none" });
      return;
    }

    setError("");
    setResult(null);
    setPhase("working");
    Taro.showNavigationBarLoading();
    Taro.setKeepScreenOn({ keepScreenOn: true }).catch(() => undefined);
    try {
      const userId = await ensureLoggedIn();
      const response = await api.analyzeVideo(video.path, {
        user_id: userId,
        question: cleanQuestion,
      });
      setResult(response);
      setPhase("success");
    } catch (e: any) {
      const message = String(e?.message || e || "视频分析失败");
      setError(message);
      setPhase("error");
      Taro.showToast({ title: "分析失败，请查看提示", icon: "none" });
    } finally {
      Taro.hideNavigationBarLoading();
      Taro.setKeepScreenOn({ keepScreenOn: false }).catch(() => undefined);
    }
  };

  const reset = () => {
    if (busy) return;
    setVideo(null);
    setResult(null);
    setError("");
    setPhase("idle");
    setElapsedSeconds(0);
  };

  return (
    <View className="page video-analysis-page">
      <View className="card hero-card">
        <Text className="hero-kicker">VIDEO COACH</Text>
        <Text className="title">视频动作安全分析</Text>
        <Text className="subtitle">
          V-Socrate 理解整段动作，AI 教练结合你的伤病档案给出建议
        </Text>
      </View>

      <View className="card">
        <Text className="step-label">01 · 选择运动视频</Text>
        {!video ? (
          <View className="video-picker" onClick={chooseVideo}>
            <Text className="picker-icon">▶</Text>
            <Text className="picker-title">拍摄或从相册选择</Text>
            <Text className="picker-hint">
              建议固定机位、光线充足，并拍到完整身体和动作周期
            </Text>
          </View>
        ) : (
          <View className="video-selected">
            <Video
              className="video-preview"
              src={video.path}
              controls
              objectFit="contain"
              showCenterPlayBtn
            />
            <View className="file-row">
              <View className="file-info">
                <Text className="file-name">{video.name}</Text>
                <Text className="file-meta">
                  {formatBytes(video.size)}
                  {video.duration > 0 ? ` · ${formatTime(video.duration)}` : ""}
                </Text>
              </View>
              <Text className="replace-link" onClick={chooseVideo}>
                更换
              </Text>
            </View>
          </View>
        )}
        <Text className="support-hint">
          支持 MP4、MOV、M4V、WebM，最大 100 MB；拍摄视频最长 60 秒
        </Text>
      </View>

      <View className="card">
        <Text className="step-label">02 · 输入希望检查的问题</Text>
        <Textarea
          className="question-input"
          value={question}
          maxlength={4000}
          disabled={busy}
          autoHeight
          placeholder="例如：深蹲时有没有膝盖内扣或躯干不稳？"
          onInput={(e) => setQuestion(e.detail.value)}
        />
        <View className="question-list">
          {QUICK_QUESTIONS.map((item) => (
            <View
              className="question-chip"
              key={item}
              onClick={() => !busy && setQuestion(item)}
            >
              <Text>{item}</Text>
            </View>
          ))}
        </View>
      </View>

      {busy && (
        <View className="card processing-card">
          <View className="loading-ring" />
          <Text className="processing-title">正在上传并理解视频</Text>
          <Text className="processing-time">已等待 {elapsedSeconds} 秒</Text>
          <Text className="processing-hint">
            系统正在覆盖完整时间线、复核动作帧，并结合档案生成答复。真实推理可能需要数分钟，请保持页面打开。
          </Text>
        </View>
      )}

      {phase === "error" && error && (
        <View className="card error-card">
          <Text className="error-title">分析没有完成</Text>
          <Text className="error-message">{error}</Text>
          <View className="btn-ghost stack-gap" onClick={() => setPhase("idle")}>
            <Text>返回修改</Text>
          </View>
        </View>
      )}

      {phase === "success" && result && (
        <AnalysisResult result={result} onReset={reset} />
      )}

      {!busy && phase !== "success" && (
        <View
          className={`btn-primary analyze-button ${
            !video || !question.trim() ? "disabled" : ""
          }`}
          onClick={submit}
        >
          <Text>开始视频分析</Text>
        </View>
      )}

      <Text className="privacy-note">
        原视频在请求结束后删除；结果用于运动建议，不构成医学诊断。
      </Text>
    </View>
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
    <View className="result-list">
      {visual.mock && (
        <View className="mock-warning">
          <Text>
            当前为 Mock 模式，系统没有真实读取视频，请配置视觉模型后再判断动作。
          </Text>
        </View>
      )}

      <View className="card">
        <View className="result-heading">
          <View>
            <Text className="result-kicker">V-SOCRATE</Text>
            <Text className="section-title">可见视频证据</Text>
          </View>
          <Text className="model-tag">{visual.model}</Text>
        </View>

        <Text className="result-label">动作观察</Text>
        <Text className="result-text">{visual.summary}</Text>

        <View className="divider" />
        <Text className="result-label">证据与限制</Text>
        <Text className="result-text">{visual.reason}</Text>

        <View className="divider" />
        <Text className="result-label">证据时间点</Text>
        {visual.evidence_frames?.length ? (
          <View className="evidence-list">
            {visual.evidence_frames.map((frame) => (
              <Text
                className="evidence-chip"
                key={`${frame.frame_id}-${frame.timestamp_seconds}`}
              >
                {formatTime(frame.timestamp_seconds)} · 帧 {frame.frame_id}
              </Text>
            ))}
          </View>
        ) : (
          <Text className="muted">当前结果没有真实证据帧</Text>
        )}
        <Text className="runtime-text">
          视频 {formatTime(visual.duration_seconds)} · 分析{" "}
          {formatTime(visual.processing_seconds)}
        </Text>
      </View>

      <View className="card coach-result">
        <Text className="result-kicker">
          {result.answer_model.provider} · {result.answer_model.model}
        </Text>
        <Text className="section-title">AI 教练答复</Text>
        <Text className="coach-answer">{result.assistant_message.content}</Text>
      </View>

      <View className="disclaimer">
        <Text>{result.disclaimer}</Text>
      </View>

      <View className="btn-ghost" onClick={onReset}>
        <Text>分析另一段视频</Text>
      </View>
    </View>
  );
}
