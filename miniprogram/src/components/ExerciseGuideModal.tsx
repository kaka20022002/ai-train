import { useEffect, useState } from "react";
import { View, Text, Image, ScrollView } from "@tarojs/components";
import Taro from "@tarojs/taro";
import { api, type ExerciseGuideMeta } from "../services/api";
import { exerciseNameCn, muscleCn } from "../utils/exercise-labels";
import {
  downloadMediaFrames,
  exerciseMediaUrl,
  mediaUrl,
} from "../utils/media";
import "./ExerciseGuideModal.scss";

type Props = {
  /** 英文动作名（API key） */
  exerciseName: string | null;
  targetMuscle?: string;
  onClose: () => void;
};

/**
 * 动作教程弹层：双帧轮播 + 中文要领
 * 真机：先 downloadFile 到本地再给 Image，避免 HTTP 直链不显示
 */
export default function ExerciseGuideModal({
  exerciseName,
  targetMuscle,
  onClose,
}: Props) {
  const [guide, setGuide] = useState<ExerciseGuideMeta | null>(null);
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(true);
  const [frame, setFrame] = useState(0);
  const [localFrames, setLocalFrames] = useState<string[]>([]);
  const [imgError, setImgError] = useState("");

  useEffect(() => {
    if (!exerciseName) {
      setGuide(null);
      setLocalFrames([]);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setGuide(null);
    setLocalFrames([]);
    setPlaying(true);
    setFrame(0);
    setImgError("");

    (async () => {
      try {
        const g = await api.guideMeta(exerciseName);
        if (cancelled) return;
        setGuide(g);

        // 优先用接口帧；若为空则按动作名直接拼 0/1 帧
        let remotes =
          (g.animation_frames || []).map(mediaUrl).filter(Boolean) || [];
        if (remotes.length === 0 && g.has_guide) {
          remotes = [
            exerciseMediaUrl(exerciseName, 0),
            exerciseMediaUrl(exerciseName, 1),
          ];
        } else if (remotes.length === 1) {
          remotes = [remotes[0], remotes[0]];
        } else if (remotes.length === 0 && g.image_url) {
          remotes = [mediaUrl(g.image_url)];
        } else if (remotes.length === 0) {
          // 即使 has_guide=false，也试一下媒体接口（有的动作只有图没有登记）
          remotes = [
            exerciseMediaUrl(exerciseName, 0),
            exerciseMediaUrl(exerciseName, 1),
          ];
        }

        // 真机：下载到本地；失败则保留远程 URL 再试一次 Image
        try {
          const locals = await downloadMediaFrames(remotes);
          if (!cancelled) setLocalFrames(locals);
        } catch (e: any) {
          if (!cancelled) {
            setLocalFrames(remotes);
            setImgError(
              `图片下载失败，将尝试直链。${String(e?.message || e).slice(0, 40)}`
            );
          }
        }
      } catch {
        if (!cancelled) {
          setGuide(null);
          Taro.showToast({ title: "教程加载失败", icon: "none" });
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [exerciseName]);

  const hasAnim = localFrames.length >= 2;
  const currentSrc = localFrames.length
    ? localFrames[frame % localFrames.length]
    : "";

  useEffect(() => {
    if (!playing || !hasAnim) return undefined;
    const timer = setInterval(() => {
      setFrame((f) => (f + 1) % localFrames.length);
    }, 1000);
    return () => clearInterval(timer);
  }, [playing, hasAnim, localFrames.length]);

  if (!exerciseName) return null;

  const cn = exerciseNameCn(exerciseName);

  return (
    <View className="guide-mask" catchMove onClick={onClose}>
      <View
        className="guide-sheet"
        onClick={(e) => {
          e.stopPropagation();
        }}
      >
        <View className="guide-sheet-head">
          <View className="guide-sheet-titles">
            <Text className="guide-kicker">TUTORIAL</Text>
            <Text className="guide-title">{cn}</Text>
            {cn !== exerciseName && (
              <Text className="guide-en">{exerciseName}</Text>
            )}
            <Text className="guide-meta">
              {targetMuscle ? muscleCn(targetMuscle) : "动作示范"}
              {localFrames.length >= 2 ? " · 可播放" : ""}
            </Text>
          </View>
          <View className="guide-close" onClick={onClose}>
            <Text>关闭</Text>
          </View>
        </View>

        <ScrollView scrollY className="guide-body">
          {loading && (
            <View className="guide-loading">
              <Text className="muted">正在加载示范图…</Text>
            </View>
          )}

          {!loading && currentSrc && (
            <View className="guide-player">
              <Image
                className="guide-frame-single"
                src={currentSrc}
                mode="aspectFit"
                lazyLoad={false}
                onError={() =>
                  setImgError(
                    "图片无法显示。请确认已勾选「不校验合法域名」，且手机能打开后端 /docs。"
                  )
                }
              />
              <View className="guide-badge">
                <Text>
                  {hasAnim
                    ? `${playing ? "播放中" : "已暂停"} · ${frame + 1}/${localFrames.length}`
                    : "示意图"}
                </Text>
              </View>
            </View>
          )}

          {!loading && !!imgError && (
            <View className="guide-empty">
              <Text className="muted">{imgError}</Text>
            </View>
          )}

          {!loading && hasAnim && (
            <View className="guide-controls">
              <View
                className="guide-ctrl-btn"
                onClick={() => setPlaying((p) => !p)}
              >
                <Text>{playing ? "暂停" : "播放"}</Text>
              </View>
              <View
                className="guide-ctrl-btn ghost"
                onClick={() => {
                  setPlaying(false);
                  setFrame((f) => (f + 1) % localFrames.length);
                }}
              >
                <Text>下一帧</Text>
              </View>
            </View>
          )}

          {!loading && !currentSrc && !imgError && (
            <View className="guide-empty">
              <Text className="muted">该动作暂无图示，可参考下方要领。</Text>
            </View>
          )}

          <View className="guide-tech">
            <Text className="guide-tech-title">动作要领</Text>
            {guide?.technique_cn?.length ? (
              guide.technique_cn.map((t, i) => (
                <Text className="guide-tech-line" key={i}>
                  {i + 1}. {t}
                </Text>
              ))
            ) : (
              <Text className="muted">
                {loading
                  ? "加载中…"
                  : "暂无专属要领：保持核心收紧，全程可控速度，出现锐痛请立即停止。"}
              </Text>
            )}
          </View>
        </ScrollView>
      </View>
    </View>
  );
}
