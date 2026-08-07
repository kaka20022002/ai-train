import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/AppShell";
import { Sidebar } from "@/components/Sidebar";
import { Providers } from "@/components/Providers";

export const metadata: Metadata = {
  title: "AI 健身教练",
  description: "由大模型驱动的自适应 AI 健身教练系统",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="flex h-screen overflow-hidden">
        <Providers>
          <Sidebar />
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
