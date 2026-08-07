"use client";

/**
 * Main content shell — soft gradient backdrop + scrollable content area.
 * Inspired by 21st.dev Magic MCP app-shell layout.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex-1 min-w-0 min-h-0 overflow-y-auto relative">
      <div className="app-shell-bg pointer-events-none absolute inset-0" aria-hidden />
      <div className="relative z-10 min-h-full h-full">{children}</div>
    </main>
  );
}
