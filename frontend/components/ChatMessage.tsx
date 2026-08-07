"use client";

import { Bot, User } from "lucide-react";
import { cn } from "@/lib/utils";
import { ActionCard } from "./ActionCard";
import type { Message, ActionRequest } from "@/lib/api";

interface Props {
  message: Message;
  streaming?: boolean;
  onConfirmAction?: (action: ActionRequest) => Promise<void>;
}

export function ChatMessage({ message, streaming = false, onConfirmAction }: Props) {
  const isAssistant = message.role === "assistant";

  return (
    <div className={cn("flex gap-3 group", isAssistant ? "items-start" : "items-start flex-row-reverse")}>
      {/* Avatar */}
      <div
        className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center"
        style={{
          background: isAssistant ? "var(--accent)" : "var(--surface2)",
          border: `1px solid var(--border)`,
        }}
      >
        {isAssistant ? (
          <Bot size={15} className="text-white" />
        ) : (
          <User size={15} style={{ color: "var(--text-muted)" }} />
        )}
      </div>

      {/* Bubble */}
      <div className={cn("max-w-[80%]", isAssistant ? "" : "items-end flex flex-col")}>
        <div
          className={cn(
            "rounded-2xl px-4 py-3 text-sm leading-relaxed",
            isAssistant ? "rounded-tl-sm" : "rounded-tr-sm"
          )}
          style={{
            background: isAssistant ? "var(--surface2)" : "var(--accent)",
            color: isAssistant ? "var(--text)" : "#fff",
          }}
        >
          <div
            className={cn("prose-chat whitespace-pre-wrap break-words", streaming && "typing-cursor")}
            dangerouslySetInnerHTML={{ __html: simpleMarkdown(message.content) }}
          />
        </div>

        {/* Action card */}
        {message.action_request && onConfirmAction && (
          <ActionCard action={message.action_request} onConfirm={onConfirmAction} />
        )}
      </div>
    </div>
  );
}

/** Very lightweight markdown → HTML for chat bubbles. */
function simpleMarkdown(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/^[-•] (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`)
    .replace(/\n/g, "<br/>");
}
