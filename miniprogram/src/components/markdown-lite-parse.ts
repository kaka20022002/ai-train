/**
 * 教练回复的轻量排版解析器 —— 纯函数，无 UI 依赖，便于单测与 node 校验。
 *
 * 契约（与后端 `sanitize_coach_plaintext()` 一一对应）：
 *   ### 标题
 *   · 要点            （行首缩进 ≥2 空格视为上一级的子要点）
 *   1. 动作名 · 3 组 × 12 次
 *   ---               （水平分隔线）
 *   其余非空行按段落合并
 */

export type Block =
  | { kind: "heading"; text: string }
  | {
      kind: "item";
      ordered: boolean;
      index?: string;
      text: string;
      indent: number;
    }
  | { kind: "para"; text: string }
  | { kind: "divider" };

/** 判断某段是不是「剂量」而不是普通短语 */
const DOSE_RE = /(组|次|分钟|秒|米|自重|每侧)/;

/**
 * 把 `动作名 · 3 组 × 12 次` 拆成名称 + 剂量。
 * 拆不出来（或右半边不像剂量）就原样返回，避免把「热身 · 5 分钟」以外的
 * 普通短语误当剂量涂成徽章。
 */
export function splitDose(text: string): { name: string; dose?: string } {
  const m = /^(.+?)\s*[·•]\s*([^·•]{1,24})$/.exec(text);
  if (!m) return { name: text };

  const name = m[1].trim();
  const dose = m[2].trim();
  if (!DOSE_RE.test(dose) || !/[\d一二三四五六七八九十]/.test(dose)) {
    return { name: text };
  }
  return { name, dose };
}

export function parseMarkdownLite(text: string): Block[] {
  const lines = (text || "").replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let buf: string[] = [];

  const flush = () => {
    if (!buf.length) return;
    blocks.push({ kind: "para", text: buf.join(" ") });
    buf = [];
  };

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (!line.trim()) {
      flush();
      continue;
    }

    const heading = /^\s*#{1,6}\s+(.*)$/.exec(line);
    if (heading) {
      flush();
      blocks.push({ kind: "heading", text: heading[1].trim() });
      continue;
    }

    const ordered = /^(\s*)(\d+)[.、)]\s*(.*)$/.exec(line);
    if (ordered) {
      flush();
      blocks.push({
        kind: "item",
        ordered: true,
        index: ordered[2],
        text: ordered[3].trim(),
        indent: ordered[1].length,
      });
      continue;
    }

    const bullet = /^(\s*)[·•*\-]\s*(.*)$/.exec(line);
    if (bullet) {
      flush();
      blocks.push({
        kind: "item",
        ordered: false,
        text: bullet[2].trim(),
        indent: bullet[1].length,
      });
      continue;
    }

    if (/^\s*-{3,}\s*$/.test(line)) {
      flush();
      blocks.push({ kind: "divider" });
      continue;
    }

    buf.push(line.trim());
  }
  flush();
  return blocks;
}
