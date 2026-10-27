import { useEffect, useRef, useState } from "react";
import { View, Text, Textarea, ScrollView } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { api, ensureLoggedIn } from "../../services/api";
import { createVoiceInput, type VoiceStatus } from "../../utils/voice-input";
import MarkdownLite from "../../components/MarkdownLite";
import "./index.scss";

interface Bubble {
  role: "user" | "assistant";
  content: string;
}

const QUICK = [
  "今天状态一般，训练要减量吗？",
  "膝盖有点紧，深蹲怎么调整？",
  "帮我解释今天这组动作的要点",
  "练完如何放松拉伸？",
];

export default function CoachPage() {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [messages, setMessages] = useState<Bubble[]>([
    {
      role: "assistant",
      content:
        "你好，我是你的 AI 健身教练。可以直接打字，或按住下方麦克风说话。",
    },
  ]);
  const [offlineHint, setOfflineHint] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus>("idle");
  const voiceRef = useRef(createVoiceInput());
  const sendingRef = useRef(false);

  useEffect(() => {
    sendingRef.current = sending;
  }, [sending]);

  const send = async (textOverride?: string) => {
    const text = (textOverride ?? input).trim();
    if (!text || sendingRef.current) return;

    setInput("");
    setSending(true);
    setMessages((prev) => [...prev, { role: "user", content: text }]);

    try {
      const userId = await ensureLoggedIn();
      const res = await api.chat({
        user_id: userId,
        message: text,
        conversation_id: conversationId,
      });
      setConversationId(res.conversation_id);
      const content = res.assistant_message.content || "";
      if (content.includes("本地教练模式") || content.includes("LLM 不可用")) {
        setOfflineHint(true);
      }
      setMessages((prev) => [...prev, { role: "assistant", content }]);
    } catch (e: any) {
      // 不再用固定的「连不上后端」兜底 —— 那句会把超时、跨域、500 全糊成
      // 一个原因，之前就是它把「等 20 秒超时」误报成「后端没启动」。
      const detail = e?.message || "发送失败，请重试";
      Taro.showToast({ title: detail.slice(0, 40), icon: "none", duration: 3000 });
      setMessages((prev) => [...prev, { role: "assistant", content: detail }]);
    } finally {
      setSending(false);
    }
  };

  const onVoiceStart = async () => {
    if (sending) return;
    setVoiceStatus("recording");
    await voiceRef.current.start({
      onStart: () => setVoiceStatus("recording"),
      onResult: (text) => {
        setVoiceStatus("idle");
        setInput(text);
        // 识别成功后自动发送，健身房场景更顺手
        setTimeout(() => send(text), 50);
      },
      onError: (message) => {
        setVoiceStatus("idle");
        Taro.showToast({ title: message.slice(0, 40), icon: "none", duration: 2500 });
      },
      onStop: () => {
        setVoiceStatus((s) => (s === "recording" ? "recognizing" : s));
      },
    });
  };

  const onVoiceEnd = () => {
    if (voiceStatus === "recording") {
      setVoiceStatus("recognizing");
    }
    voiceRef.current.stop();
  };

  const voiceLabel =
    voiceStatus === "recording"
      ? "松开结束"
      : voiceStatus === "recognizing"
        ? "识别中…"
        : "按住说话";

  return (
    <View className="coach-page">
      <View className="coach-header">
        <View className="coach-brand">
          <Text className="coach-mark">AI</Text>
          <View>
            <Text className="hero-kicker">COACH</Text>
            <Text className="coach-title">AI 教练</Text>
          </View>
        </View>
        <Text className="coach-sub">打字或按住麦克风，像训练搭档一样提问</Text>
        {offlineHint && (
          <Text className="offline-banner">
            当前为本地教练模式：请检查 DeepSeek API 余额与密钥配置。
          </Text>
        )}
        <View
          className="video-analysis-entry"
          onClick={() => Taro.navigateTo({ url: "/pages/video-analysis/index" })}
        >
          <Text className="video-entry-icon">▶</Text>
          <View className="video-entry-copy">
            <Text className="video-entry-title">上传视频分析动作</Text>
            <Text className="video-entry-hint">检查动作问题与潜在受伤风险</Text>
          </View>
          <Text className="video-entry-arrow">›</Text>
        </View>
      </View>

      <ScrollView scrollY className="msg-scroll" scrollWithAnimation>
        <View className="quick-row">
          {QUICK.map((q) => (
            <View key={q} className="quick-chip" onClick={() => send(q)}>
              <Text>{q}</Text>
            </View>
          ))}
        </View>

        <View className="msg-list">
          {messages.map((m, i) => (
            <View
              key={`${m.role}-${i}`}
              className={`bubble ${m.role === "user" ? "me" : "bot"}`}
            >
              {m.role === "assistant" && (
                <Text className="bubble-role">Coach</Text>
              )}
              {m.role === "assistant" ? (
                <MarkdownLite text={m.content} />
              ) : (
                <Text className="bubble-text">{m.content}</Text>
              )}
            </View>
          ))}
          {sending && (
            <View className="bubble bot">
              <Text className="bubble-text typing">
                教练正在思考（含风险分析，约 20-40 秒）…
              </Text>
            </View>
          )}
        </View>
      </ScrollView>

      <View className="composer">
        <View
          className={`mic ${voiceStatus !== "idle" ? "hot" : ""}`}
          onTouchStart={(e) => {
            e.stopPropagation();
            onVoiceStart();
          }}
          onTouchEnd={(e) => {
            e.stopPropagation();
            onVoiceEnd();
          }}
          onTouchCancel={onVoiceEnd}
        >
          <Text className="mic-icon">🎙</Text>
          <Text className="mic-text">{voiceLabel}</Text>
        </View>
        <Textarea
          className="input"
          value={input}
          maxlength={500}
          placeholder={sending ? "教练思考中…" : "也可以打字提问…"}
          disabled={sending || voiceStatus === "recording"}
          autoHeight
          onInput={(e) => setInput(e.detail.value)}
        />
        <View
          className={`send ${sending || !input.trim() ? "disabled" : ""}`}
          onClick={() => send()}
        >
          <Text>{sending ? "…" : "发送"}</Text>
        </View>
      </View>
    </View>
  );
}
