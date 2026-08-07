import { useState } from "react";
import { View, Text, Input } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import {
  api,
  ensureLoggedIn,
  type RiskAnalysisResult,
  type UserProfile,
} from "../../services/api";
import {
  FITNESS_CN,
  INJURY_LOCATIONS,
  JOINT_CN,
  SEVERITY_CN,
} from "../../utils/labels";
import "./index.scss";

interface InjuryDraft {
  location: string;
  condition: string;
  severity: string;
}

export default function RiskPage() {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [level, setLevel] = useState("intermediate");
  const [injuries, setInjuries] = useState<InjuryDraft[]>([
    { location: "knee", condition: "meniscus_tear", severity: "medium" },
  ]);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [result, setResult] = useState<RiskAnalysisResult | null>(null);

  useDidShow(async () => {
    const uid = await ensureLoggedIn();
    try {
      const p = await api.getUser(uid);
      setProfile(p);
      if (p.fitness_level) setLevel(p.fitness_level);
      if (p.medical_history?.length) {
        setInjuries(
          p.medical_history.map((m) => ({
            location: m.location,
            condition: m.condition,
            severity: m.severity,
          }))
        );
      }
    } catch {
      setProfile(null);
    }
  });

  const updateInjury = (idx: number, patch: Partial<InjuryDraft>) => {
    setInjuries((prev) => prev.map((x, i) => (i === idx ? { ...x, ...patch } : x)));
  };

  const analyze = async () => {
    setLoading(true);
    setResult(null);
    try {
      const uid = await ensureLoggedIn();
      const data = await api.analyzeRisk({
        user_id: uid,
        basic_info: profile?.basic_info || { age: 28, gender: "male" },
        fitness_level: level,
        medical_history: injuries,
      });
      setResult(data);
    } catch (e: any) {
      Taro.showToast({ title: e?.message?.slice(0, 40) || "分析失败", icon: "none" });
    } finally {
      setLoading(false);
    }
  };

  const sync = async () => {
    setSyncing(true);
    try {
      const uid = await ensureLoggedIn();
      let updated;
      try {
        await api.getUser(uid);
        updated = await api.updateUser(uid, {
          medical_history: injuries,
          fitness_level: level,
        });
      } catch {
        updated = await api.createUser({
          user_id: uid,
          basic_info: profile?.basic_info || { age: 28, gender: "male" },
          fitness_level: level,
          medical_history: injuries,
          available_equipment: profile?.available_equipment || [],
        });
      }
      const rv = updated.safety_revalidation;
      Taro.showToast({
        title: rv
          ? `已同步，替换 ${rv.exercises_replaced || 0} 个动作`
          : "已同步到档案",
        icon: "success",
      });
    } catch (e: any) {
      Taro.showToast({ title: e?.message?.slice(0, 40) || "同步失败", icon: "none" });
    } finally {
      setSyncing(false);
    }
  };

  return (
    <View className="page">
      <View className="card hero-card">
        <Text className="hero-kicker">RISK</Text>
        <Text className="title">风险分析</Text>
        <Text className="subtitle">根据伤病史筛选禁止动作，并可同步到档案</Text>
      </View>

      <View className="card">
        <Text className="section-title">健身水平</Text>
        <View className="chip-row">
          {Object.entries(FITNESS_CN).map(([k, v]) => (
            <View key={k} className={level === k ? "chip on" : "chip"} onClick={() => setLevel(k)}>
              <Text>{v}</Text>
            </View>
          ))}
        </View>
      </View>

      {injuries.map((inj, idx) => (
        <View className="card" key={idx}>
          <Text className="section-title">伤病 {idx + 1}</Text>
          <Text className="field-label">部位</Text>
          <View className="chip-row">
            {INJURY_LOCATIONS.map((loc) => (
              <View
                key={loc}
                className={inj.location === loc ? "chip on" : "chip"}
                onClick={() => updateInjury(idx, { location: loc })}
              >
                <Text>{JOINT_CN[loc]}</Text>
              </View>
            ))}
          </View>
          <Text className="field-label">严重程度</Text>
          <View className="chip-row">
            {Object.entries(SEVERITY_CN).map(([k, v]) => (
              <View
                key={k}
                className={inj.severity === k ? "chip on" : "chip"}
                onClick={() => updateInjury(idx, { severity: k })}
              >
                <Text>{v}</Text>
              </View>
            ))}
          </View>
          <Text className="field-label">损伤描述（英文 snake_case 亦可）</Text>
          <Input
            className="input"
            value={inj.condition}
            placeholder="如 meniscus_tear"
            onInput={(e) => updateInjury(idx, { condition: e.detail.value })}
          />
        </View>
      ))}

      <View
        className="btn-ghost"
        onClick={() =>
          setInjuries((prev) => [
            ...prev,
            { location: "shoulder", condition: "impingement", severity: "low" },
          ])
        }
      >
        <Text>添加伤病</Text>
      </View>

      <View className="btn-primary stack-gap" onClick={analyze}>
        <Text>{loading ? "分析中…" : "开始风险分析"}</Text>
      </View>
      <View className="btn-ghost stack-gap" onClick={sync}>
        <Text>{syncing ? "同步中…" : "同步伤病史到档案"}</Text>
      </View>

      {result && (
        <View className="card">
          <Text className="section-title">分析结果</Text>
          <View className="stat-grid">
            <View className="stat-card">
              <Text className="stat-label">总动作</Text>
              <Text className="stat-value">{result.summary.total_exercises}</Text>
            </View>
            <View className="stat-card">
              <Text className="stat-label">禁止</Text>
              <Text className="stat-value">{result.summary.forbidden_count}</Text>
            </View>
            <View className="stat-card">
              <Text className="stat-label">安全</Text>
              <Text className="stat-value">{result.summary.safe_count}</Text>
            </View>
          </View>
          <View className="divider" />
          <Text className="section-title">禁止动作</Text>
          {result.forbidden_exercises.length === 0 ? (
            <Text className="muted">无禁止动作</Text>
          ) : (
            result.forbidden_exercises.map((f) => (
              <View className="forbid-row" key={f.name}>
                <Text className="forbid-name">{f.name}</Text>
                <Text className="muted">{f.reason}</Text>
                <Text className="tag">替代：{f.substitution}</Text>
              </View>
            ))
          )}
        </View>
      )}
    </View>
  );
}
