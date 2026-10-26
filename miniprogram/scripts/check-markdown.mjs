/**
 * 校验 MarkdownLite 的解析结果 —— 不依赖浏览器，避免「改了样式但没验证」。
 *
 * 用法：
 *   node scripts/check-markdown.mjs <文本文件>
 *   node scripts/check-markdown.mjs --json <接口响应.json>
 *
 * 打印每种 block 的数量，并逐条展开列表项与剂量拆分结果。
 */
import fs from "node:fs";
import esbuild from "esbuild";

const src = fs.readFileSync("src/components/markdown-lite-parse.ts", "utf8");
const built = await esbuild.transform(src, { loader: "ts", format: "cjs" });
const mod = { exports: {} };
new Function("module", "exports", built.code)(mod, mod.exports);
const { parseMarkdownLite, splitDose } = mod.exports;

const args = process.argv.slice(2);
if (!args.length) {
  console.error("用法: node scripts/check-markdown.mjs <文件> [--json]");
  process.exit(1);
}

const jsonMode = args.includes("--json");
const file = args.find((a) => !a.startsWith("--"));
const raw = fs.readFileSync(file, "utf8");
const text = jsonMode
  ? JSON.parse(raw)?.assistant_message?.content ?? ""
  : raw;

const blocks = parseMarkdownLite(text);
const count = (k) => blocks.filter((b) => b.kind === k).length;
console.log(
  `blocks=${blocks.length}  heading=${count("heading")}  item=${count("item")}  ` +
    `para=${count("para")}  divider=${count("divider")}`
);
console.log("");

for (const b of blocks) {
  if (b.kind === "heading") {
    console.log(`[H]   ${b.text}`);
  } else if (b.kind === "item") {
    const mark = b.ordered ? `${b.index}.` : b.indent >= 2 ? "  ·" : "·";
    const parsed = b.ordered ? splitDose(b.text) : { name: b.text, dose: undefined };
    // 与组件一致：长句有序项不配序号徽章，按段落渲染
    const asPara = b.ordered && !parsed.dose && b.text.length > 20;
    const dose = parsed.dose ? `  ⟨${parsed.dose}⟩` : "";
    const tag = asPara ? "P#" : b.ordered ? "O" : "U";
    console.log(
      `[${tag}] ${" ".repeat(b.indent)}${mark} ${parsed.name}${dose}`
    );
  } else if (b.kind === "para") {
    const t = b.text.length > 40 ? `${b.text.slice(0, 40)}…` : b.text;
    console.log(`[P]   ${t}`);
  } else {
    console.log("[---]");
  }
}
