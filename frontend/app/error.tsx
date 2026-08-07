"use client";

import { useEffect } from "react";
import { AlertCircle } from "lucide-react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] p-8 text-center">
      <AlertCircle size={40} className="mb-4" style={{ color: "var(--danger)" }} />
      <h2 className="text-lg font-bold mb-2" style={{ color: "var(--text)" }}>
        页面加载出错
      </h2>
      <p className="text-sm mb-6 max-w-md" style={{ color: "var(--text-muted)" }}>
        {error.message || "未知错误"}
      </p>
      <button
        onClick={reset}
        className="px-4 py-2 rounded-lg text-sm font-medium"
        style={{ background: "var(--accent)", color: "#fff" }}
      >
        重试
      </button>
    </div>
  );
}
