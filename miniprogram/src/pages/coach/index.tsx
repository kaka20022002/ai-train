import { useEffect, useRef, useState } from "react";
import { View, Text, Textarea, ScrollView } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { api, ensureLoggedIn } from "../../services/api";
import { createVoiceInput, type VoiceStatus } from "../../utils/voice-input";
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
      Taro.showToast({ title: e?.message?.slice(0, 40) || "发送失败", icon: "none" });
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "暂时连不上教练服务，请确认后端已在 8000 端口运行。",
        },
      ]);
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
              <Text className="bubble-text">{m.content}</Text>
            </View>
          ))}
          {sending && (
            <View className="bubble bot">
              <Text className="bubble-text typing">教练正在回复…</Text>
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
