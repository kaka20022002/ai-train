import { View, Text } from "@tarojs/components";
import { parseMarkdownLite, splitDose } from "./markdown-lite-parse";
import "./MarkdownLite.scss";

/**
 * 轻量排版渲染器 —— 只认教练会用到的那一小撮语法：
 *
 *   ### 标题
 *   · 要点
 *   1. 动作名 · 3 组 × 12 次
 *     · 动作要点（缩进两格 = 子级）
 *   ---
 *
 * 设计取舍：不引入 markdown 库（Taro 小程序里体积和兼容性都不划算），
 * 也不做行内富文本 —— 后端 `sanitize_coach_plaintext()` 已经把加粗之类的
 * 符号剥干净了，这里只需要按行还原成「章节 + 列表 + 剂量徽章」。
 * 解析逻辑抽在 `markdown-lite-parse.ts`，无 UI 依赖，可单独校验。
 */

type Props = {
  text: string;
};

export default function MarkdownLite({ text }: Props) {
  const blocks = parseMarkdownLite(text);

  return (
    <View className="md">
      {blocks.map((b, i) => {
        if (b.kind === "heading") {
          return (
            <View className="md-heading" key={`h-${i}`}>
              <View className="md-heading-bar" />
              <Text className="md-heading-text">{b.text}</Text>
            </View>
          );
        }

        if (b.kind === "divider") {
          return <View className="md-divider" key={`d-${i}`} />;
        }

        if (b.kind === "item") {
          const sub = b.indent >= 2;
          const parsed = b.ordered
            ? splitDose(b.text)
            : { name: b.text, dose: undefined };
          const dose = parsed.dose;

          // 长句序号（例如结尾的追问「1. 现在膝盖有疼痛或肿胀吗？……」）不配
          // 方形序号徽章 —— 那是动作行的样式，套在问题会让用户误以为是训练项。
          if (b.ordered && !dose && b.text.length > 20) {
            return (
              <Text className="md-para md-para-num" key={`i-${i}`}>
                {`${b.index}. ${b.text}`}
              </Text>
            );
          }

          return (
            <View
              className={`md-item ${sub ? "md-item-sub" : ""} ${
                dose ? "md-item-dose" : ""
              }`}
              key={`i-${i}`}
            >
              {b.ordered ? (
                <View className="md-num">
                  <Text className="md-num-text">{b.index}</Text>
                </View>
              ) : (
                <View className={`md-dot ${sub ? "md-dot-sub" : ""}`} />
              )}
              <View className="md-item-body">
                <Text className="md-item-text">{parsed.name}</Text>
                {dose && (
                  <View className="md-dose">
                    <Text className="md-dose-text">{dose}</Text>
                  </View>
                )}
              </View>
            </View>
          );
        }

        return (
          <Text className="md-para" key={`p-${i}`}>
            {b.text}
          </Text>
        );
      })}
    </View>
  );
}
