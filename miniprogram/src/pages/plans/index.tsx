import { useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import { api, ensureLoggedIn, type TrainingProgram } from "../../services/api";
import { GOAL_CN } from "../../utils/labels";
import "./index.scss";

const STATUS_CN: Record<string, string> = {
  active: "进行中",
  paused: "已暂停",
  completed: "已完成",
};

export default function PlansPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [programs, setPrograms] = useState<TrainingProgram[]>([]);
  const [advancing, setAdvancing] = useState<string>("");

  const load = async () => {
    setLoading(true);
    setError("");
    try {
      const uid = await ensureLoggedIn();
      const list = await api.listPrograms(uid);
      setPrograms(list);
    } catch (e: any) {
      setError(e?.message || "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useDidShow(() => {
    load();
  });

  const advance = async (pid: string) => {
    setAdvancing(pid);
    try {
      await api.advanceProgram(pid);
      Taro.showToast({ title: "已推进到下一周", icon: "success" });
      await load();
    } catch (e: any) {
      Taro.showToast({ title: e?.message?.slice(0, 40) || "推进失败", icon: "none" });
    } finally {
      setAdvancing("");
    }
  };

  return (
    <View className="page">
      <View className="card hero-card">
        <Text className="hero-kicker">PROGRAMS</Text>
        <Text className="title">我的计划</Text>
        <Text className="subtitle">周期进度、生成新计划与周次推进</Text>
      </View>

      <View className="card">
        <View className="menu-grid">
          <View className="menu-item" onClick={() => Taro.navigateTo({ url: "/pages/generate/index" })}>
            <Text className="menu-icon">+</Text>
            <Text className="menu-text">生成计划</Text>
            <Text className="menu-hint">单次 / 周期</Text>
          </View>
          <View className="menu-item" onClick={() => Taro.navigateTo({ url: "/pages/dashboard/index" })}>
            <Text className="menu-icon">◎</Text>
            <Text className="menu-text">仪表盘</Text>
            <Text className="menu-hint">准备度与趋势</Text>
          </View>
          <View className="menu-item" onClick={() => Taro.navigateTo({ url: "/pages/risk/index" })}>
            <Text className="menu-icon">⬡</Text>
            <Text className="menu-text">风险分析</Text>
            <Text className="menu-hint">伤病与安全</Text>
          </View>
          <View
            className="menu-item recommend-entry"
            onClick={() => Taro.navigateTo({ url: "/pages/recommendations/index" })}
          >
            <Text className="menu-icon">✦</Text>
            <Text className="menu-text">计划推荐</Text>
            <Text className="menu-hint">智能匹配</Text>
          </View>
        </View>
      </View>

      {loading && (
        <View className="card">
          <View className="empty">
            <Text className="empty-icon">…</Text>
            <Text className="empty-desc">正在加载计划</Text>
          </View>
        </View>
      )}

      {!loading && !!error && (
        <View className="card">
          <View className="empty">
            <Text className="empty-icon">!</Text>
            <Text className="empty-title">加载失败</Text>
            <Text className="empty-desc">{error}</Text>
            <View className="btn-primary" onClick={load}>
              <Text>重试</Text>
            </View>
          </View>
        </View>
      )}

      {!loading && !error && programs.length === 0 && (
        <View className="card">
          <View className="empty">
            <Text className="empty-icon">计</Text>
            <Text className="empty-title">还没有周期计划</Text>
            <Text className="empty-desc">点击上方「生成计划」，创建单次或周期训练安排。</Text>
            <View
              className="btn-primary"
              onClick={() => Taro.navigateTo({ url: "/pages/generate/index" })}
            >
              <Text>去生成</Text>
            </View>
          </View>
        </View>
      )}

      {programs.map((p) => {
        const pct = Math.min(
          100,
          Math.round(((p.current_week || 1) / Math.max(1, p.total_weeks || 1)) * 100)
        );
        const status = STATUS_CN[p.status] || p.status;
        const tagClass =
          p.status === "active" ? "ok" : p.status === "paused" ? "warn" : "neutral";
        return (
          <View className="card plan-card" key={p.program_id}>
            <View className="row-between">
              <Text className="prog-title">
                {GOAL_CN[p.goal] || p.goal || p.name || "训练计划"}
              </Text>
              <Text className={`tag ${tagClass}`}>{status}</Text>
            </View>
            <Text className="muted">{p.program_id}</Text>
            <View className="progress-wrap">
              <View className="progress-bar">
                <View className="progress-fill" style={{ width: `${pct}%` }} />
              </View>
              <Text className="progress-text">
                第 {p.current_week}/{p.total_weeks} 周
                {p.sessions_per_week ? ` · 每周 ${p.sessions_per_week} 练` : ""}
              </Text>
            </View>
            {p.status === "active" && (
              <View className="actions">
                <View
                  className="btn-ghost half"
                  onClick={() => Taro.switchTab({ url: "/pages/workout/index" })}
                >
                  <Text>去训练</Text>
                </View>
                <View
                  className="btn-primary half"
                  onClick={() => advance(p.program_id)}
                >
                  <Text>{advancing === p.program_id ? "推进中…" : "推进下周"}</Text>
                </View>
              </View>
            )}
          </View>
        );
      })}
    </View>
  );
}
