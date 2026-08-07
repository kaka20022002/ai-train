"use client";

import { useState } from "react";
import { User, Check } from "lucide-react";

interface Props {
  userId: string;
  onChange: (id: string) => void;
}

export function UserIdBar({ userId, onChange }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(userId);

  const commit = () => {
    const trimmed = draft.trim();
    if (trimmed) onChange(trimmed);
    setEditing(false);
  };

  return (
    <div
      className="flex items-center gap-2 px-4 py-2 border-b text-sm"
      style={{ borderColor: "var(--border)", background: "var(--surface2)" }}
    >
      <User size={14} style={{ color: "var(--text-muted)" }} />
      <span style={{ color: "var(--text-muted)" }} className="shrink-0">用户 ID：</span>

      {editing ? (
        <>
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && commit()}
            className="flex-1 bg-transparent outline-none text-sm"
            style={{ color: "var(--text)" }}
            placeholder="输入 user_id"
          />
          <button onClick={commit} className="shrink-0">
            <Check size={14} style={{ color: "var(--success)" }} />
          </button>
        </>
      ) : (
        <button
          onClick={() => { setDraft(userId); setEditing(true); }}
          className="font-mono hover:underline"
          style={{ color: "var(--accent-light)" }}
        >
          {userId || "点击设置"}
        </button>
      )}
    </div>
  );
}
