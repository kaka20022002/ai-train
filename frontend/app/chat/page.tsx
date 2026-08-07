"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Send, Loader2, Bot, AlertCircle } from "lucide-react";
import { chatApi, usersApi, programsApi } from "@/lib/api";
import type { Message, Conversation, ActionRequest } from "@/lib/api";
import { ChatMessage } from "@/components/ChatMessage";
import { ConversationList } from "@/components/ConversationList";
import { UserIdBar } from "@/components/UserIdBar";
import { useUser } from "@/contexts/UserContext";

export default function ChatPage() {
  const { userId, setUserId } = useUser();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Load conversations when userId changes
  const loadConversations = useCallback(async () => {
    try {
      const list = await usersApi.conversations(userId);
      setConversations(list);
    } catch {
      setConversations([]);
    }
  }, [userId]);

  useEffect(() => { loadConversations(); }, [loadConversations]);

  // Load messages when activeConvId changes
  useEffect(() => {
    if (!activeConvId) { setMessages([]); return; }
    chatApi.getConversation(activeConvId)
      .then(({ messages }) => setMessages(messages))
      .catch(() => setMessages([]));
  }, [activeConvId]);

  // Auto-scroll messages only — keep input bar fixed at bottom
  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, streamingContent]);

  const handleSend = async (textOverride?: string) => {
    const text = (textOverride ?? input).trim();
    if (!text || sending) return;

    if (!textOverride) setInput("");
    setSending(true);
    setError(null);

    // Optimistic user message
    const userMsg: Message = {
      id: Date.now(),
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      setStreamingContent("");
      let fullContent = "";
      let convId = activeConvId;
      let finalMsg: Message | null = null;

      const res = await fetch(chatApi.streamUrl(activeConvId), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          message: text,
          conversation_id: activeConvId ?? undefined,
        }),
      });

      if (!res.ok || !res.body) {
        // Fallback: synchronous chat when streaming unavailable
        const sync = await chatApi.send({
          user_id: userId,
          message: text,
          conversation_id: activeConvId ?? undefined,
        });
        if (!activeConvId) {
          setActiveConvId(sync.conversation_id);
          loadConversations();
        }
        setMessages((prev) => [...prev, sync.assistant_message]);
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          if (!line.startsWith("data:")) continue;
          const raw = line.slice(5).trim();
          if (!raw) continue;
          try {
            const evt = JSON.parse(raw) as {
              type: string;
              conversation_id?: string;
              text?: string;
              content?: string;
              action_request?: ActionRequest | null;
              assistant_message_id?: number;
              message?: string;
            };

            if (evt.type === "start" && evt.conversation_id) {
              convId = evt.conversation_id;
              if (!activeConvId) {
                setActiveConvId(convId);
                loadConversations();
              }
            } else if (evt.type === "delta") {
              fullContent += evt.text ?? "";
              setStreamingContent(fullContent);
            } else if (evt.type === "final") {
              finalMsg = {
                id: evt.assistant_message_id ?? Date.now(),
                role: "assistant",
                content: evt.content ?? fullContent,
                action_request: evt.action_request ?? null,
                created_at: new Date().toISOString(),
              };
            } else if (evt.type === "error") {
              throw new Error(evt.message ?? "流式响应失败");
            }
          } catch (e) {
            if (e instanceof SyntaxError) continue;
            throw e;
          }
        }
      }

      setStreamingContent("");
      if (finalMsg) {
        setMessages((prev) => [...prev, finalMsg!]);
      } else if (fullContent) {
        setMessages((prev) => [
          ...prev,
          { id: Date.now(), role: "assistant", content: fullContent },
        ]);
      }

      loadConversations();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "发送失败，请重试");
      setStreamingContent("");
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  const handleNewConversation = () => {
    setActiveConvId(null);
    setMessages([]);
    setStreamingContent("");
    setError(null);
  };

  const handleConfirmAction = async (action: ActionRequest) => {
    try {
      if (action.tool === "advance_week") {
        const programs = await usersApi.programs(userId);
        const active = programs.find((p) => p.status === "active");
        if (active) await programsApi.advance(active.program_id);
      }
      // Other tools: send a follow-up message describing what happened
      setInput(`已执行操作：${action.confirm_label}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "操作失败");
    }
  };

  // Build the streaming placeholder message
  const streamingMsg: Message | null = streamingContent
    ? { id: -1, role: "assistant", content: streamingContent }
    : null;

  const isEmpty = messages.length === 0 && !streamingContent;

  return (
    <div className="flex h-full min-h-0 overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Conversation sidebar */}
      <ConversationList
        conversations={conversations}
        activeId={activeConvId}
        onSelect={setActiveConvId}
        onNew={handleNewConversation}
      />

      {/* Main chat area */}
      <div className="flex flex-col flex-1 min-w-0 min-h-0">
        {/* Top bar */}
        <UserIdBar userId={userId} onChange={(id) => { setUserId(id); setActiveConvId(null); setMessages([]); }} />

        {/* Messages — sole scroll region */}
        <div
          ref={messagesRef}
          className="flex-1 min-h-0 overflow-y-auto px-6 py-6 flex flex-col gap-6"
        >
          {isEmpty && <WelcomeHint onSelect={(hint) => void handleSend(hint)} />}

          {messages.map((msg) => (
            <ChatMessage
              key={msg.id}
              message={msg}
              onConfirmAction={handleConfirmAction}
            />
          ))}

          {streamingMsg && (
            <ChatMessage message={streamingMsg} streaming />
          )}

          {error && (
            <div
              className="flex items-center gap-2 text-sm px-4 py-3 rounded-xl"
              style={{ background: "rgba(239,68,68,0.1)", color: "var(--danger)", border: "1px solid rgba(239,68,68,0.2)" }}
            >
              <AlertCircle size={15} />
              {error}
            </div>
          )}

        </div>

        {/* Input — pinned to bottom */}
        <div
          className="shrink-0 px-6 pb-6 pt-3 border-t"
          style={{ background: "var(--surface)", borderColor: "var(--border)" }}
        >
          <div
            className="flex items-end gap-3 rounded-2xl px-4 py-3 border"
            style={{ background: "var(--surface)", borderColor: "var(--border)" }}
          >
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                e.target.style.height = "auto";
                e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px";
              }}
              onKeyDown={handleKeyDown}
              placeholder="问 Coach 任何健身问题… (Enter 发送，Shift+Enter 换行)"
              disabled={sending}
              className="flex-1 bg-transparent resize-none outline-none text-sm leading-relaxed max-h-36 disabled:opacity-50"
              style={{ color: "var(--text)" }}
            />
            <button
              type="button"
              onClick={() => void handleSend()}
              disabled={sending || !input.trim()}
              className="shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-opacity disabled:opacity-40"
              style={{ background: "var(--accent)" }}
            >
              {sending ? (
                <Loader2 size={16} className="text-white animate-spin" />
              ) : (
                <Send size={16} className="text-white" />
              )}
            </button>
          </div>
          <p className="text-xs mt-2 text-center" style={{ color: "var(--text-muted)" }}>
            AI 教练基于你的训练数据给出建议，仅供参考，不替代专业医疗意见
          </p>
        </div>
      </div>
    </div>
  );
}

function WelcomeHint({ onSelect }: { onSelect: (text: string) => void }) {
  const hints = [
    "我今天训练感觉很累，该怎么办？",
    "帮我分析一下最近的训练状态",
    "帮我生成下周的训练计划",
    "我膝盖有点不舒服，哪些动作要避免？",
  ];

  return (
    <div className="flex flex-col items-center justify-center flex-1 text-center py-20">
      <div
        className="w-16 h-16 rounded-2xl flex items-center justify-center mb-4"
        style={{ background: "var(--accent)" }}
      >
        <Bot size={28} className="text-white" />
      </div>
      <h2 className="text-lg font-bold mb-2" style={{ color: "var(--text)" }}>
        你好，我是 Coach 🏋️
      </h2>
      <p className="text-sm max-w-sm" style={{ color: "var(--text-muted)" }}>
        我会根据你的训练历史、伤病记录和当前计划，给出个性化的建议。<br />
        直接告诉我你想聊什么吧！
      </p>
      <div className="grid grid-cols-2 gap-2 mt-8 max-w-sm">
        {hints.map((hint) => (
          <button
            key={hint}
            type="button"
            onClick={() => onSelect(hint)}
            className="text-left text-xs px-3 py-2.5 rounded-xl border transition-colors hover:opacity-80 cursor-pointer"
            style={{
              borderColor: "var(--border)",
              background: "var(--surface)",
              color: "var(--text-muted)",
            }}
          >
            {hint}
          </button>
        ))}
      </div>
    </div>
  );
}
