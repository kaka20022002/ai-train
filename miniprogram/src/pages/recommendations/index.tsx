import { useState } from "react";
import { View, Text } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import {
  api,
  ensureLoggedIn,
  type PlanRecommendationResponse,
  type RecommendedPlan,
  type UserProfile,
} from "../../services/api";
import "./index.scss";

const DIFFICULTY_CN: Record<string, string> = {
  beginner: "初级",
  intermediate: "中级",
  advanced: "高级",
};

export default function RecommendationsPage() {
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [data, setData] = useState<PlanRecommendationResponse | null>(null);
  const [adopting, setAdopting] = useState("");

  const load = async (refresh = false) => {
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError("");

    try {
      const uid = await ensureLoggedIn();
      const [user, recommendations] = await Promise.all([
        api.getUser(uid),
        api.planRecommendations(uid, 6),
      ]);
      setProfile(user);
      setData(recommendations);
    } catch (e: any) {
      setError(e?.message || "推荐加载失败");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useDidShow(() => {
    load();
  });

  const adopt = async (plan: RecommendedPlan) => {
    if (!profile || adopting) return;
    setAdopting(plan.template_id);
    setError("");

    try {
      const program = await api.generateProgram({
        user_profile: {
          user_id: profile.user_id,
          basic_info: profile.basic_info,
          fitness_level: profile.fitness_level,
          fitness_goal: plan.goal,
          training_frequency: plan.sessions_per_week,
          available_equipment: profile.available_equipment || [],
          medical_history: profile.medical_history || [],
        },
        goal: plan.goal,
        total_weeks: plan.total_weeks,
        sessions_per_week: plan.sessions_per_week,
        split_type: plan.split_type,
        use_history: true,
      });

      const modal = await Taro.showModal({
        title: "计划已启用",
        content: `${program.name || plan.name} 已生成，原进行中计划已暂停。`,
        confirmText: "查看计划",
        cancelText: "留在这里",
      });
      if (modal.confirm) {
        Taro.switchTab({ url: "/pages/plans/index" });
      }
    } catch (e: any) {
      setError(e?.message || "计划生成失败");
      Taro.showToast({
        title: e?.message?.slice(0, 40) || "计划生成失败",
        icon: "none",
      });
    } finally {
      setAdopting("");
    }
  };

  if (loading) {
    return (
      <View className="page">
        <View className="card hero-card">
          <Text className="hero-kicker">PLAN MATCH</Text>
          <Text className="title">训练计划推荐</Text>
          <Text className="subtitle">正在分析训练目标、历史表现与安全约束</Text>
        </View>
        <View className="card loading-card">
          <View className="loading-mark">✦</View>
          <Text className="section-title">正在计算契合度</Text>
          <Text className="subtitle">通常只需几秒钟</Text>
        </View>
      </View>
    );
  }

  if (error && !data) {
    return (
      <View className="page">
        <View className="card hero-card">
          <Text className="hero-kicker">PLAN MATCH</Text>
          <Text className="title">训练计划推荐</Text>
          <Text className="subtitle">根据当前档案生成个性化排序</Text>
        </View>
        <View className="card">
          <View className="empty">
            <Text className="empty-icon">!</Text>
            <Text className="empty-title">暂时无法生成推荐</Text>
            <Text className="empty-desc">{error}</Text>
            <View className="btn-primary" onClick={() => load()}>
              <Text>重新计算</Text>
            </View>
          </View>
        </View>
      </View>
    );
  }

  if (!data || data.recommendations.length === 0) {
    return null;
  }

  const [featured, ...remaining] = data.recommendations;
  const snapshot = data.user_snapshot;

  return (
    <View className="page">
      <View className="card hero-card recommendation-hero">
        <View className="row-between hero-top">
          <View className="hero-copy">
            <Text className="hero-kicker">PLAN MATCH</Text>
            <Text className="title">训练计划推荐</Text>
            <Text className="subtitle">画像、历史行为和安全约束共同排序</Text>
          </View>
          <View className="refresh-btn" onClick={() => load(true)}>
            <Text>{refreshing ? "…" : "↻"}</Text>
          </View>
        </View>
        <View className="meta-grid">
          <Text className="meta-pill">{snapshot.goal_label}</Text>
          <Text className="meta-pill">{snapshot.training_frequency} 次/周</Text>
          <Text className="meta-pill">{snapshot.session_count} 次历史</Text>
        </View>
      </View>

      {error && (
        <View className="card inline-error">
          <Text>{error}</Text>
        </View>
      )}

      <View className="card">
        <View className="row-between">
          <Text className="section-title">当前画像</Text>
          <Text className="tag">v{data.model.version}</Text>
        </View>
        <View className="stat-grid">
          <View className="stat-card">
            <Text className="stat-label">平均完成率</Text>
            <Text className="stat-value">
              {snapshot.average_completion_rate == null
                ? "待积累"
                : `${Math.round(snapshot.average_completion_rate)}%`}
            </Text>
          </View>
          <View className="stat-card">
            <Text className="stat-label">近期平均 RPE</Text>
            <Text className="stat-value">
              {snapshot.average_rpe == null ? "待积累" : snapshot.average_rpe.toFixed(1)}
            </Text>
          </View>
          <View className="stat-card">
            <Text className="stat-label">实际频率</Text>
            <Text className="stat-value">
              {snapshot.actual_sessions_per_week == null
                ? "待积累"
                : snapshot.actual_sessions_per_week.toFixed(1)}
            </Text>
          </View>
          <View className="stat-card">
            <Text className="stat-label">安全动作</Text>
            <Text className="stat-value">{featured.safe_exercise_count}</Text>
          </View>
        </View>
      </View>

      <View className="featured-card">
        <View className="featured-glow" />
        <View className="row-between featured-head">
          <View>
            <Text className="featured-kicker">首选匹配 · 第 {featured.rank} 名</Text>
            <Text className="featured-title">{featured.name}</Text>
          </View>
          <View className="score-box">
            <Text className="score-number">{featured.score.toFixed(0)}</Text>
            <Text className="score-label">匹配分</Text>
          </View>
        </View>

        <View className="score-track">
          <View className="score-fill" style={{ width: `${featured.score}%` }} />
        </View>

        <Text className="featured-desc">{featured.description}</Text>

        <View className="chip-row compact">
          <Text className="info-chip">{featured.goal_label}</Text>
          <Text className="info-chip">{featured.total_weeks} 周</Text>
          <Text className="info-chip">每周 {featured.sessions_per_week} 次</Text>
          <Text className="info-chip">约 {featured.estimated_duration_minutes} 分钟</Text>
          <Text className="info-chip accent">
            {DIFFICULTY_CN[featured.difficulty] || featured.difficulty_label}
          </Text>
        </View>

        <View className="reason-block">
          <Text className="mini-title">推荐依据</Text>
          {featured.match_reasons.slice(0, 3).map((reason) => (
            <View className="reason-row" key={reason}>
              <Text className="reason-dot ok">✓</Text>
              <Text className="reason-text">{reason}</Text>
            </View>
          ))}
        </View>

        {!!featured.cautions.length && (
          <View className="caution-block">
            {featured.cautions.map((caution) => (
              <View className="reason-row" key={caution}>
                <Text className="reason-dot warn">!</Text>
                <Text className="reason-text">{caution}</Text>
              </View>
            ))}
          </View>
        )}

        <View className="component-row">
          <ComponentBar label="画像" value={featured.component_scores.profile} />
          <ComponentBar label="行为" value={featured.component_scores.behaviour} />
          <ComponentBar label="群体" value={featured.component_scores.population} />
        </View>

        <View
          className={`btn-primary adopt-btn ${adopting ? "disabled" : ""}`}
          onClick={() => adopt(featured)}
        >
          <Text>
            {adopting === featured.template_id ? "正在生成完整计划…" : "采用此计划"}
          </Text>
        </View>
        <Text className="adopt-note">采用后仍会按伤病史重新筛选训练动作</Text>
      </View>

      <View className="section-head">
        <View>
          <Text className="section-title no-margin">更多匹配</Text>
          <Text className="muted">按综合推荐分从高到低排列</Text>
        </View>
        <Text className="section-count">{remaining.length + 1} 个</Text>
      </View>

      {remaining.map((plan) => (
        <View className="card plan-rec-card" key={plan.template_id}>
          <View className="row-between">
            <View className="rank-title-wrap">
              <Text className="rank-badge">{plan.rank}</Text>
              <View className="rank-copy">
                <Text className="plan-rec-title">{plan.name}</Text>
                <Text className="muted">
                  {plan.goal_label} · {plan.split_label}
                </Text>
              </View>
            </View>
            <View className="mini-score">
              <Text className="mini-score-value">{plan.score.toFixed(1)}</Text>
              <Text className="mini-score-label">匹配分</Text>
            </View>
          </View>

          <Text className="plan-rec-desc">{plan.description}</Text>

          <View className="chip-row compact">
            <Text className="info-chip">{DIFFICULTY_CN[plan.difficulty] || plan.difficulty_label}</Text>
            <Text className="info-chip">{plan.total_weeks} 周</Text>
            <Text className="info-chip">每周 {plan.sessions_per_week} 次</Text>
            <Text className="info-chip">{plan.estimated_duration_minutes} 分钟</Text>
          </View>

          <View className="plan-rec-footer">
            <Text className="reason-single">
              {plan.match_reasons[0] || "根据当前画像完成排序"}
            </Text>
            <View
              className={`adopt-mini ${adopting ? "disabled" : ""}`}
              onClick={() => adopt(plan)}
            >
              <Text>{adopting === plan.template_id ? "生成中…" : "采用"}</Text>
            </View>
          </View>
        </View>
      ))}

      <View className="card algorithm-card">
        <Text className="section-title">混合推荐模型</Text>
        <Text className="subtitle">{data.model.name}</Text>
        <View className="divider" />
        <WeightLine label="内容画像" value={data.model.weights.profile} color="#0f766e" />
        <WeightLine label="历史行为" value={data.model.weights.behaviour} color="#14b8a6" />
        <WeightLine label="群体采用" value={data.model.weights.population} color="#f59e0b" />
        <Text className="algorithm-note">
          当前为可解释混合排序算法。更多真实用户产生训练和计划记录后，群体采用信号会自动增强。
        </Text>
      </View>
    </View>
  );
}

function ComponentBar({ label, value }: { label: string; value: number }) {
  return (
    <View className="component-item">
      <View className="component-head">
        <Text className="component-label">{label}</Text>
        <Text className="component-value">{value.toFixed(0)}</Text>
      </View>
      <View className="component-track">
        <View className="component-fill" style={{ width: `${Math.min(100, value)}%` }} />
      </View>
    </View>
  );
}

function WeightLine({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  const pct = Math.round(value * 100);
  return (
    <View className="weight-row">
      <View className="row-between">
        <Text className="weight-label">{label}</Text>
        <Text className="weight-value">{pct}%</Text>
      </View>
      <View className="weight-track">
        <View className="weight-fill" style={{ width: `${pct}%`, background: color }} />
      </View>
    </View>
  );
}
