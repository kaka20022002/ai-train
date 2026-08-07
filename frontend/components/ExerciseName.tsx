import { formatExerciseName } from "@/lib/exercise-labels";

interface Props {
  name: string;
  /** 是否显示英文副标题（动作库列表可关闭以节省空间） */
  showEnglish?: boolean;
  className?: string;
}

/** 中文动作名为主；默认不显示英文副标题 */
export function ExerciseName({ name, showEnglish = false, className = "" }: Props) {
  const { cn, en, isTranslated } = formatExerciseName(name);
  return (
    <span className={className}>
      <span style={{ color: "var(--text)" }}>{cn}</span>
      {showEnglish && isTranslated && (
        <span className="block text-[10px] mt-0.5 opacity-50 font-normal" style={{ color: "var(--text-muted)" }}>
          {en}
        </span>
      )}
    </span>
  );
}
