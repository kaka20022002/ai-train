"use client";

import { useEffect, useState } from "react";
import { BookOpen, ChevronDown, ChevronUp, Loader2 } from "lucide-react";
import { getExerciseGuides, getCachedGuide } from "@/lib/exercise-guide-cache";
import type { ExerciseGuideMeta } from "@/lib/api";
import { formatExerciseName } from "@/lib/exercise-labels";

function useGuide(name: string) {
  const [guide, setGuide] = useState<ExerciseGuideMeta | null>(() => getCachedGuide(name));
  const [loading, setLoading] = useState(() => !getCachedGuide(name));

  useEffect(() => {
    let cancelled = false;
    setLoading(!getCachedGuide(name));
    getExerciseGuides()
      .then((guides) => {
        if (!cancelled) {
          setGuide(guides[name] ?? null);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [name]);

  return { guide, loading };
}

function GuideAnimation({
  frames,
  imageUrl,
  alt,
  size,
  featured = false,
}: {
  frames: string[] | null;
  imageUrl: string | null;
  alt: string;
  size: number;
  featured?: boolean;
}) {
  const style = { width: size, height: size, minWidth: size };
  const radius = featured ? "rounded-2xl" : "rounded-xl";

  if (frames && frames.length >= 2) {
    return (
      <div
        className={`exercise-guide-anim relative overflow-hidden border shrink-0 ${radius}`}
        style={{ ...style, background: "var(--surface2)", borderColor: "var(--border)" }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={frames[0]}
          alt={`${alt} 起始位`}
          className="exercise-guide-frame-a absolute inset-0 w-full h-full object-cover"
        />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={frames[1]}
          alt={`${alt} 结束位`}
          className="exercise-guide-frame-b absolute inset-0 w-full h-full object-cover"
        />
        <span
          className={`absolute bottom-2 left-2 rounded-md font-medium bg-black/50 text-white ${
            featured ? "text-[11px] px-2 py-1" : "text-[9px] px-1.5 py-0.5"
          }`}
        >
          动图
        </span>
      </div>
    );
  }

  if (imageUrl) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={imageUrl}
        alt={alt}
        className={`object-cover border shrink-0 ${radius}`}
        style={{ ...style, background: "var(--surface2)", borderColor: "var(--border)" }}
      />
    );
  }

  return (
    <div
      className={`flex items-center justify-center shrink-0 border ${radius} ${featured ? "text-3xl" : "text-xl"}`}
      style={{ ...style, background: "var(--surface2)", borderColor: "var(--border)" }}
    >
      🏋️
    </div>
  );
}

/** 始终可见的动图缩略图 */
export function ExerciseGuideThumb({ name, size = 96 }: { name: string; size?: number }) {
  const { guide, loading } = useGuide(name);
  const { cn } = formatExerciseName(name);

  if (loading) {
    return (
      <div
        className="rounded-xl flex items-center justify-center shrink-0 border"
        style={{ width: size, height: size, background: "var(--surface2)", borderColor: "var(--border)" }}
      >
        <Loader2 size={16} className="animate-spin" style={{ color: "var(--text-muted)" }} />
      </div>
    );
  }

  if (!guide?.has_guide) return null;

  const frames = guide.animation_frames?.length >= 2 ? guide.animation_frames : null;
  return <GuideAnimation frames={frames} imageUrl={guide.image_url} alt={cn} size={size} />;
}

interface Props {
  name: string;
  /** 仅展示文字要领，动图由 ExerciseGuideThumb 单独展示 */
  techniqueOnly?: boolean;
  defaultOpen?: boolean;
  className?: string;
  /** 动作库详情等大尺寸展示 */
  featured?: boolean;
}

export function ExerciseGuide({
  name,
  techniqueOnly = false,
  defaultOpen = true,
  className = "",
  featured = false,
}: Props) {
  const { guide, loading } = useGuide(name);
  const [open, setOpen] = useState(defaultOpen);

  const { cn } = formatExerciseName(name);

  if (loading) {
    return (
      <p className="text-[11px] mt-1 flex items-center gap-1" style={{ color: "var(--text-muted)" }}>
        <Loader2 size={11} className="animate-spin" /> 加载动作教程…
      </p>
    );
  }

  if (!guide?.has_guide) return null;

  const frames = guide.animation_frames?.length >= 2 ? guide.animation_frames : null;
  const imageUrl = guide.image_url;
  const mediaSize = featured ? 220 : 140;

  const media = !techniqueOnly && (
    <GuideAnimation frames={frames} imageUrl={imageUrl} alt={cn} size={mediaSize} featured={featured} />
  );

  const technique = guide.technique_cn.length > 0 && (
    <div className="flex-1 min-w-0">
      <p
        className={`font-semibold mb-3 flex items-center gap-2 ${featured ? "text-sm" : "text-xs mb-2 gap-1.5"}`}
        style={{ color: "var(--text)" }}
      >
        <BookOpen size={featured ? 15 : 12} style={{ color: "var(--accent-light)" }} />
        标准动作要领
      </p>
      <ol
        className={`space-y-2 ${featured ? "text-sm" : "text-xs space-y-1.5"}`}
        style={{ color: "var(--text-muted)" }}
      >
        {guide.technique_cn.map((step, i) => (
          <li key={i} className={`flex gap-2.5 ${featured ? "leading-relaxed" : "leading-relaxed"}`}>
            <span
              className={`shrink-0 rounded-full flex items-center justify-center font-bold ${
                featured ? "w-5 h-5 text-xs" : "w-4 h-4 text-[10px]"
              }`}
              style={{ background: "rgba(108,99,255,0.2)", color: "var(--accent-light)" }}
            >
              {i + 1}
            </span>
            <span style={featured ? { color: "var(--text)" } : undefined}>{step}</span>
          </li>
        ))}
      </ol>
    </div>
  );

  if (techniqueOnly) {
    if (!technique) return null;
    return (
      <div className={className}>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-1 text-[11px] mt-2 hover:opacity-80"
          style={{ color: "var(--accent-light)" }}
        >
          <BookOpen size={11} />
          {open ? "收起动作要领" : "展开动作要领"}
          {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
        </button>
        {open && (
          <div
            className="mt-2 p-3 rounded-lg border"
            style={{ background: "var(--surface)", borderColor: "var(--border)" }}
          >
            {technique}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className={`flex rounded-xl border ${featured ? "gap-6 p-5" : "gap-4 p-3"} ${className}`}
      style={{ background: "var(--surface2)", borderColor: "var(--border)" }}
    >
      {media}
      {technique}
    </div>
  );
}
