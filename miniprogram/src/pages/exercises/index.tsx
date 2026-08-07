import { useEffect, useMemo, useState } from "react";
import { View, Text, Input } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import { api, type ExerciseRecord } from "../../services/api";
import {
  exerciseNameCn,
  muscleCn,
  translateExerciseText,
} from "../../utils/exercise-labels";
import ExerciseGuideModal from "../../components/ExerciseGuideModal";
import "./index.scss";

export default function ExercisesPage() {
  const [list, setList] = useState<ExerciseRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [maxRisk, setMaxRisk] = useState<number | null>(null);
  const [guideName, setGuideName] = useState<string | null>(null);
  const [guideMuscle, setGuideMuscle] = useState<string | undefined>();

  const load = async (risk: number | null = maxRisk) => {
    setLoading(true);
    try {
      const data = await api.listExercises(
        risk != null ? { max_risk_level: risk } : undefined
      );
      setList(data);
    } catch (e: any) {
      Taro.showToast({ title: e?.message?.slice(0, 40) || "加载失败", icon: "none" });
    } finally {
      setLoading(false);
    }
  };

  useDidShow(() => {
    load();
  });

  useEffect(() => {
    load(maxRisk);
  }, [maxRisk]);

  const filtered = useMemo(() => {
    const q = keyword.trim().toLowerCase();
    if (!q) return list;
    return list.filter((e) => {
      const cn = exerciseNameCn(e.name).toLowerCase();
      const muscle = muscleCn(e.target_muscle || "").toLowerCase();
      return (
        e.name.toLowerCase().includes(q) ||
        cn.includes(q) ||
        e.target_muscle?.toLowerCase().includes(q) ||
        muscle.includes(q)
      );
    });
  }, [list, keyword]);

  return (
    <View className="page">
      <View className="card hero-card">
        <Text className="hero-kicker">LIBRARY</Text>
        <Text className="title">动作库</Text>
        <Text className="subtitle">点击动作可播放示范并查看要领</Text>
      </View>

      <View className="card">
        <Input
          className="input"
          value={keyword}
          placeholder="搜索中文 / 英文动作名、肌群"
          onInput={(e) => setKeyword(e.detail.value)}
        />
        <Text className="field-label">最高风险等级</Text>
        <View className="chip-row">
          <View
            className={maxRisk == null ? "chip on" : "chip"}
            onClick={() => {
              setMaxRisk(null);
            }}
          >
            <Text>全部</Text>
          </View>
          {[2, 3, 4, 5].map((n) => (
            <View
              key={n}
              className={maxRisk === n ? "chip on" : "chip"}
              onClick={() => {
                setMaxRisk(n);
              }}
            >
              <Text>≤{n}</Text>
            </View>
          ))}
        </View>
      </View>

      {loading ? (
        <View className="card">
          <Text className="muted">加载中…</Text>
        </View>
      ) : (
        <View className="card">
          <Text className="muted">共 {filtered.length} 个动作</Text>
          {filtered.map((ex) => (
            <View
              className="ex-item"
              key={ex.id || ex.name}
              onClick={() => {
                setGuideName(ex.name);
                setGuideMuscle(ex.target_muscle);
              }}
            >
              <View className="ex-main">
                <Text className="ex-name">{exerciseNameCn(ex.name)}</Text>
                <Text className="muted">
                  {muscleCn(ex.target_muscle || "")} · 风险 {ex.risk_level}
                  {ex.substitution
                    ? ` · 可替：${translateExerciseText(ex.substitution)}`
                    : ""}
                </Text>
              </View>
              <Text className="tag">{ex.has_guide ? "播放" : "要领"}</Text>
            </View>
          ))}
        </View>
      )}

      <ExerciseGuideModal
        exerciseName={guideName}
        targetMuscle={guideMuscle}
        onClose={() => {
          setGuideName(null);
          setGuideMuscle(undefined);
        }}
      />
    </View>
  );
}
