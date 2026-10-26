"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Dumbbell,
  LayoutDashboard,
  CalendarDays,
  User,
  Zap,
  ClipboardList,
  ShieldAlert,
  BookOpen,
  PlayCircle,
  MessageCircle,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/workout", icon: PlayCircle, label: "今日训练" },
  { href: "/", icon: LayoutDashboard, label: "仪表盘" },
  { href: "/generate", icon: ClipboardList, label: "生成计划" },
  { href: "/recommendations", icon: Sparkles, label: "计划推荐" },
  { href: "/programs", icon: CalendarDays, label: "周期计划" },
  { href: "/risk", icon: ShieldAlert, label: "风险分析" },
  { href: "/exercises", icon: BookOpen, label: "动作库" },
  { href: "/chat", icon: MessageCircle, label: "AI 教练" },
  { href: "/profile", icon: User, label: "我的档案" },
] as const;

function isActive(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      className={cn(
        "flex flex-col h-screen shrink-0 border-r z-20",
        "w-[4.25rem] md:w-60",
        "shadow-[4px_0_32px_-16px_rgba(15,23,42,0.08)]"
      )}
      style={{ background: "var(--surface)", borderColor: "var(--border)" }}
    >
      {/* Brand */}
      <div
        className="flex items-center justify-center md:justify-start gap-3 px-3 md:px-5 h-[4.25rem] border-b shrink-0"
        style={{ borderColor: "var(--border)" }}
      >
        <div className="flex items-center justify-center w-10 h-10 rounded-xl shrink-0 bg-gradient-to-br from-[#6c63ff] to-[#5449d4] shadow-md shadow-[#6c63ff]/20">
          <Zap size={20} className="text-white" strokeWidth={2.25} />
        </div>
        <div className="hidden md:block min-w-0">
          <p className="font-bold text-sm tracking-tight truncate" style={{ color: "var(--text)" }}>
            AI 健身教练
          </p>
          <p className="text-[11px] truncate" style={{ color: "var(--text-muted)" }}>
            智能自适应训练
          </p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex flex-col gap-0.5 p-2 md:p-3 flex-1 overflow-y-auto">
        <p
          className="hidden md:block px-3 pt-1 pb-2 text-[10px] font-semibold uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          导航
        </p>
        {NAV.map(({ href, icon: Icon, label }) => {
          const active = isActive(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              title={label}
              className={cn(
                "group relative flex items-center gap-3 rounded-xl text-sm transition-all duration-200",
                "px-3 py-2.5 md:justify-start justify-center",
                active ? "font-semibold" : "font-medium",
                !active && "hover:bg-[var(--surface2)]"
              )}
              style={{
                background: active
                  ? "linear-gradient(135deg, rgba(108,99,255,0.14) 0%, rgba(108,99,255,0.06) 100%)"
                  : "transparent",
                color: active ? "var(--accent)" : "var(--text-muted)",
                boxShadow: active ? "inset 0 0 0 1px rgba(108,99,255,0.14)" : undefined,
              }}
            >
              {active && (
                <span
                  className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-6 rounded-r-full hidden md:block"
                  style={{ background: "var(--accent)" }}
                />
              )}
              <span
                className={cn(
                  "flex items-center justify-center w-8 h-8 rounded-lg shrink-0 transition-colors",
                  active ? "bg-white/80 shadow-sm" : "group-hover:bg-white/60"
                )}
              >
                <Icon
                  size={17}
                  strokeWidth={active ? 2.25 : 2}
                  style={{ color: active ? "var(--accent)" : "var(--text-muted)" }}
                />
              </span>
              <span className="hidden md:block truncate">{label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="p-2 md:p-3 border-t shrink-0" style={{ borderColor: "var(--border)" }}>
        <div
          className="hidden md:flex items-center gap-3 p-3 rounded-xl border"
          style={{ background: "var(--bg)", borderColor: "var(--border)" }}
        >
          <div className="relative shrink-0">
            <div className="w-9 h-9 rounded-full flex items-center justify-center bg-gradient-to-br from-[#6c63ff]/15 to-[#6c63ff]/5">
              <Dumbbell size={15} style={{ color: "var(--accent)" }} />
            </div>
            <span
              className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2"
              style={{ background: "var(--success)", borderColor: "var(--surface)" }}
            />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold truncate" style={{ color: "var(--text)" }}>
              统一界面 v2.0
            </p>
            <p className="text-[11px] truncate" style={{ color: "var(--text-muted)" }}>
              系统运行正常
            </p>
          </div>
        </div>
        <div className="md:hidden flex justify-center py-1">
          <div className="relative">
            <div
              className="w-9 h-9 rounded-full flex items-center justify-center"
              style={{ background: "var(--surface2)" }}
            >
              <Dumbbell size={15} style={{ color: "var(--accent)" }} />
            </div>
            <span
              className="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full border-2"
              style={{ background: "var(--success)", borderColor: "var(--surface)" }}
            />
          </div>
        </div>
      </div>
    </aside>
  );
}
