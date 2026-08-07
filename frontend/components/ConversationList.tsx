"use client";

import { MessageCircle, Plus, Archive } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Conversation } from "@/lib/api";

interface Props {
  conversations: Conversation[];
  activeId: string | null;
  onSelect: (cid: string) => void;
  onNew: () => void;
}

export function ConversationList({ conversations, activeId, onSelect, onNew }: Props) {
  return (
    <div
      className="flex flex-col h-full min-h-0 w-64 border-r shrink-0"
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: "var(--border)" }}>
        <span className="text-sm font-semibold" style={{ color: "var(--text)" }}>
          对话历史
        </span>
        <button
          onClick={onNew}
          className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg transition-colors hover:opacity-80"
          style={{ background: "var(--accent)", color: "#fff" }}
        >
          <Plus size={12} />
          新对话
        </button>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-1">
        {conversations.length === 0 && (
          <p className="text-xs text-center mt-8" style={{ color: "var(--text-muted)" }}>
            暂无对话记录
          </p>
        )}
        {conversations.map((c) => (
          <button
            key={c.conversation_id}
            onClick={() => onSelect(c.conversation_id)}
            className={cn(
              "flex items-start gap-2 px-3 py-2.5 rounded-lg text-left text-xs w-full transition-colors",
              c.conversation_id !== activeId && "hover:bg-[var(--surface2)]"
            )}
            style={{
              background: c.conversation_id === activeId ? "var(--accent)" : "transparent",
              color: c.conversation_id === activeId ? "#fff" : "var(--text-muted)",
            }}
          >
            {c.status === "archived" ? (
              <Archive size={13} className="mt-0.5 shrink-0 opacity-50" />
            ) : (
              <MessageCircle size={13} className="mt-0.5 shrink-0" />
            )}
            <span className="truncate leading-snug">{c.title}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
