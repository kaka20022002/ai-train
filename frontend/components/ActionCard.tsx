"use client";

import { Zap, Loader2 } from "lucide-react";
import { useState } from "react";
import type { ActionRequest } from "@/lib/api";

interface Props {
  action: ActionRequest;
  onConfirm: (action: ActionRequest) => Promise<void>;
}

export function ActionCard({ action, onConfirm }: Props) {
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  const handle = async () => {
    setLoading(true);
    try {
      await onConfirm(action);
      setDone(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="mt-3 rounded-xl p-4 border text-sm"
      style={{
        background: "rgba(108,99,255,0.08)",
        borderColor: "rgba(108,99,255,0.3)",
      }}
    >
      <div className="flex items-start gap-2 mb-3">
        <Zap size={14} className="mt-0.5 shrink-0" style={{ color: "var(--accent-light)" }} />
        <div>
          <p className="font-semibold mb-0.5" style={{ color: "var(--accent-light)" }}>
            教练建议操作
          </p>
          <p style={{ color: "var(--text-muted)" }}>{action.rationale}</p>
        </div>
      </div>

      <button
        onClick={handle}
        disabled={loading || done}
        className="flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium transition-opacity disabled:opacity-60"
        style={{ background: "var(--accent)", color: "#fff" }}
      >
        {loading && <Loader2 size={13} className="animate-spin" />}
        {done ? "✓ 已执行" : action.confirm_label}
      </button>
    </div>
  );
}
