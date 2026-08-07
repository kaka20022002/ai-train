export function cn(...classes: (string | undefined | false | null)[]): string {
  return classes.filter(Boolean).join(" ");
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

export function rpeColor(rpe: number): string {
  if (rpe <= 4) return "text-emerald-500";
  if (rpe <= 6) return "text-yellow-500";
  if (rpe <= 8) return "text-orange-500";
  return "text-red-500";
}

export function rpeBg(rpe: number): string {
  if (rpe <= 4) return "bg-emerald-500";
  if (rpe <= 6) return "bg-yellow-500";
  if (rpe <= 8) return "bg-orange-500";
  return "bg-red-500";
}
