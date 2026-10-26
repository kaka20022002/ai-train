"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  CalendarDays,
  CheckCircle2,
  Clock3,
  Dumbbell,
  Gauge,
  Loader2,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Target,
  TrendingUp,
  Users,
} from "lucide-react";
import { programsApi, recommendationsApi } from "@/lib/api";
import type {
  PlanRecommendationResponse,
  RecommendedPlan,
  TrainingProgram,
} from "@/lib/api";
import { useUser } from "@/contexts/UserContext";

const DIFFICULTY_STYLE: Record<string, { bg: string; color: string }> = {
  beginner: { bg: "rgba(16,185,129,0.12)", color: "var(--success)" },
  intermediate: { bg: "rgba(108,99,255,0.12)", color: "var(--accent)" },
  advanced: { bg: "rgba(245,158,11,0.13)", color: "var(--warning)" },
};

export default function RecommendationsPage() {
  const { userId, profile, profileLoading } = useUser();
  const [data, setData] = useState<PlanRecommendationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingTemplate, setPendingTemplate] = useState<string | null>(null);
  const [adoptedProgram, setAdoptedProgram] = useState<TrainingProgram | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);

    recommendationsApi
      .plans(userId)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "推荐加载失败");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [userId]);

  const refresh = async () => {
    setRefreshing(true);
    setError(null);
    setAdoptedProgram(null);
    try {
      const result = await recommendationsApi.plans(userId);
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "推荐加载失败");
    } finally {
      setRefreshing(false);
    }
  };

  const adoptPlan = async (plan: RecommendedPlan) => {
    if (!profile) {
      setError("请先在“我的档案”创建用户档案，再采用推荐计划。");
      return;
    }

    setPendingTemplate(plan.template_id);
    setError(null);
    setAdoptedProgram(null);
    try {
      const program = await programsApi.generate({
        user_profile: {
          user_id: profile.user_id,
          basic_info: profile.basic_info,
          fitness_level: profile.fitness_level,
          fitness_goal: plan.goal,
          training_frequency: plan.sessions_per_week,
          available_equipment: profile.available_equipment ?? [],
          medical_history: profile.medical_history,
        },
        goal: plan.goal,
        total_weeks: plan.total_weeks,
        sessions_per_week: plan.sessions_per_week,
        split_type: plan.split_type,
        use_history: true,
      });
      setAdoptedProgram(program);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成计划失败");
    } finally {
      setPendingTemplate(null);
    }
  };

  if (profileLoading || loading) {
    return <LoadingState />;
  }

  if (!profile) {
    return (
      <div className="flex min-h-full items-center justify-center p-6">
        <div className="dashboard-card max-w-lg p-8 text-center">
          <div
            className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl"
            style={{ background: "rgba(108,99,255,0.12)" }}
          >
            <Target size={24} style={{ color: "var(--accent)" }} />
          </div>
          <h1 className="text-xl font-bold" style={{ color: "var(--text)" }}>
            先完善训练档案
          </h1>
          <p className="mt-2 text-sm leading-relaxed" style={{ color: "var(--text-muted)" }}>
            推荐算法需要目标、训练水平、频率、器材和伤病史才能计算计划匹配度。
          </p>
          <Link
            href="/profile"
            className="mt-5 inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold"
            style={{ background: "var(--accent)", color: "#fff" }}
          >
            前往我的档案
            <ArrowRight size={15} />
          </Link>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex min-h-full items-center justify-center p-6">
        <div className="dashboard-card max-w-lg p-8 text-center">
          <AlertTriangle size={30} className="mx-auto mb-3" style={{ color: "var(--warning)" }} />
          <h1 className="text-lg font-bold" style={{ color: "var(--text)" }}>
            暂时无法生成推荐
          </h1>
          <p className="mt-2 break-words text-xs" style={{ color: "var(--text-muted)" }}>
            {error}
          </p>
          <button
            type="button"
            onClick={() => void refresh()}
            className="mt-5 inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold"
            style={{ background: "var(--accent)", color: "#fff" }}
          >
            <RefreshCw size={15} />
            重新计算
          </button>
        </div>
      </div>
    );
  }

  if (!data || data.recommendations.length === 0) {
    return <LoadingState />;
  }

  const [featured, ...remaining] = data.recommendations;
  const snapshot = data.user_snapshot;

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6 md:p-8">
      <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div>
          <div className="mb-2 flex items-center gap-2">
            <Sparkles size={15} style={{ color: "var(--accent)" }} />
            <p
              className="text-xs font-semibold uppercase tracking-[0.18em]"
              style={{ color: "var(--accent)" }}
            >
              Plan Matching · {data.model.version}
            </p>
          </div>
          <h1 className="text-2xl font-bold md:text-3xl" style={{ color: "var(--text)" }}>
            训练计划推荐
          </h1>
          <p className="mt-1.5 max-w-2xl text-sm leading-relaxed" style={{ color: "var(--text-muted)" }}>
            结合目标、训练水平、可用器材、历史完成质量和训练负荷，为当前用户排序最合适的周期计划。
          </p>
        </div>
        <button
          type="button"
          onClick={() => void refresh()}
          disabled={refreshing}
          className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-medium disabled:opacity-50"
          style={{
            background: "var(--surface)",
            borderColor: "var(--border)",
            color: "var(--text)",
          }}
        >
          {refreshing ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
          {refreshing ? "重新计算中" : "重新计算"}
        </button>
      </div>

      {adoptedProgram && (
        <div
          className="flex flex-col gap-3 rounded-2xl border p-4 sm:flex-row sm:items-center"
          style={{
            background: "rgba(16,185,129,0.08)",
            borderColor: "rgba(16,185,129,0.2)",
          }}
        >
          <CheckCircle2 size={20} className="shrink-0" style={{ color: "var(--success)" }} />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold" style={{ color: "var(--text)" }}>
              已生成并启用：{adoptedProgram.name}
            </p>
            <p className="mt-0.5 text-xs" style={{ color: "var(--text-muted)" }}>
              原有的进行中周期已暂停，可以进入周期计划查看每周安排。
            </p>
          </div>
          <Link
            href="/programs"
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold"
            style={{ background: "var(--success)", color: "#fff" }}
          >
            查看周期计划
            <ArrowRight size={13} />
          </Link>
        </div>
      )}

      {error && (
        <div
          className="rounded-xl border px-4 py-3 text-sm"
          style={{
            background: "rgba(239,68,68,0.08)",
            borderColor: "rgba(239,68,68,0.18)",
            color: "var(--danger)",
          }}
        >
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <SnapshotMetric
          icon={<Target size={15} />}
          label="训练目标"
          value={snapshot.goal_label}
          hint={`${snapshot.training_frequency} 次 / 周`}
        />
        <SnapshotMetric
          icon={<BarChart3 size={15} />}
          label="平均完成率"
          value={
            snapshot.average_completion_rate == null
              ? "待积累"
              : `${Math.round(snapshot.average_completion_rate)}%`
          }
          hint={`${snapshot.session_count} 次历史训练`}
        />
        <SnapshotMetric
          icon={<Gauge size={15} />}
          label="近期平均 RPE"
          value={snapshot.average_rpe == null ? "待积累" : snapshot.average_rpe.toFixed(1)}
          hint={
            snapshot.actual_sessions_per_week == null
              ? "尚无频率估计"
              : `实际约 ${snapshot.actual_sessions_per_week.toFixed(1)} 次 / 周`
          }
        />
        <SnapshotMetric
          icon={<ShieldCheck size={15} />}
          label="安全过滤"
          value={`${featured.safe_exercise_count} 个可用`}
          hint={`排除 ${featured.forbidden_exercise_count} 个高风险动作`}
        />
      </div>

      <FeaturedRecommendation
        plan={featured}
        pending={pendingTemplate === featured.template_id}
        onAdopt={() => void adoptPlan(featured)}
      />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_19rem]">
        <section className="space-y-3">
          <div className="flex items-end justify-between">
            <div>
              <h2 className="text-base font-semibold" style={{ color: "var(--text)" }}>
                更多匹配计划
              </h2>
              <p className="mt-0.5 text-xs" style={{ color: "var(--text-muted)" }}>
                按混合推荐分数排序，采用后仍会执行安全动作替换
              </p>
            </div>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              {remaining.length + 1} 个候选
            </span>
          </div>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {remaining.map((plan) => (
              <RecommendationCard
                key={plan.template_id}
                plan={plan}
                pending={pendingTemplate === plan.template_id}
                disabled={pendingTemplate !== null}
                onAdopt={() => void adoptPlan(plan)}
              />
            ))}
          </div>
        </section>

        <AlgorithmPanel data={data} featured={featured} />
      </div>
    </div>
  );
}

function FeaturedRecommendation({
  plan,
  pending,
  onAdopt,
}: {
  plan: RecommendedPlan;
  pending: boolean;
  onAdopt: () => void;
}) {
  const difficulty = DIFFICULTY_STYLE[plan.difficulty] ?? {
    bg: "var(--surface2)",
    color: "var(--text-muted)",
  };

  return (
    <section className="dashboard-card relative overflow-hidden p-5 md:p-7">
      <div
        className="pointer-events-none absolute -right-24 -top-28 h-72 w-72 rounded-full opacity-70 blur-3xl"
        style={{ background: "radial-gradient(circle, rgba(108,99,255,0.24), transparent 68%)" }}
      />
      <div className="relative grid gap-6 lg:grid-cols-[minmax(0,1fr)_12rem]">
        <div>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span
              className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider"
              style={{ background: "rgba(108,99,255,0.12)", color: "var(--accent)" }}
            >
              <Sparkles size={11} />
              首选匹配
            </span>
            <span
              className="rounded-full px-2.5 py-1 text-[10px] font-semibold"
              style={{ background: difficulty.bg, color: difficulty.color }}
            >
              {plan.difficulty_label}
            </span>
            <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
              推荐分 {plan.score.toFixed(1)} / 100
            </span>
          </div>

          <h2 className="text-xl font-bold md:text-2xl" style={{ color: "var(--text)" }}>
            {plan.name}
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6" style={{ color: "var(--text-muted)" }}>
            {plan.description}
          </p>

          <div className="mt-4 flex flex-wrap gap-2">
            <InfoChip icon={<Target size={12} />} text={plan.goal_label} />
            <InfoChip icon={<CalendarDays size={12} />} text={`${plan.total_weeks} 周`} />
            <InfoChip icon={<TrendingUp size={12} />} text={`每周 ${plan.sessions_per_week} 次`} />
            <InfoChip icon={<Clock3 size={12} />} text={`约 ${plan.estimated_duration_minutes} 分钟`} />
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-2">
            <div>
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                推荐依据
              </p>
              <div className="space-y-1.5">
                {plan.match_reasons.slice(0, 3).map((reason) => (
                  <div key={reason} className="flex items-start gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
                    <CheckCircle2 size={13} className="mt-0.5 shrink-0" style={{ color: "var(--success)" }} />
                    <span>{reason}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                注意事项
              </p>
              {plan.cautions.length ? (
                <div className="space-y-1.5">
                  {plan.cautions.map((caution) => (
                    <div key={caution} className="flex items-start gap-2 text-xs" style={{ color: "var(--text-muted)" }}>
                      <AlertTriangle size={13} className="mt-0.5 shrink-0" style={{ color: "var(--warning)" }} />
                      <span>{caution}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                  当前没有额外风险提示
                </p>
              )}
            </div>
          </div>
        </div>

        <div className="flex flex-col items-center justify-center gap-4 lg:border-l lg:pl-6" style={{ borderColor: "var(--border)" }}>
          <ScoreRing score={plan.score} />
          <div className="w-full space-y-2">
            <ComponentBar label="内容画像" value={plan.component_scores.profile} />
            <ComponentBar label="训练行为" value={plan.component_scores.behaviour} />
            <ComponentBar label="群体先验" value={plan.component_scores.population} />
          </div>
          <button
            type="button"
            onClick={onAdopt}
            disabled={pending}
            className="flex w-full items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition-opacity disabled:opacity-50"
            style={{ background: "var(--accent)", color: "#fff" }}
          >
            {pending ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
            {pending ? "正在生成…" : "采用此计划"}
          </button>
          <p className="text-center text-[10px] leading-relaxed" style={{ color: "var(--text-muted)" }}>
            采用后会复用现有周期生成器，并按伤病史重新筛选动作。
          </p>
        </div>
      </div>
    </section>
  );
}

function RecommendationCard({
  plan,
  pending,
  disabled,
  onAdopt,
}: {
  plan: RecommendedPlan;
  pending: boolean;
  disabled: boolean;
  onAdopt: () => void;
}) {
  const style = DIFFICULTY_STYLE[plan.difficulty] ?? {
    bg: "var(--surface2)",
    color: "var(--text-muted)",
  };

  return (
    <article className="dashboard-card flex flex-col p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-xs font-bold"
            style={{ background: "rgba(108,99,255,0.1)", color: "var(--accent)" }}
          >
            {plan.rank}
          </span>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold" style={{ color: "var(--text)" }}>
              {plan.name}
            </h3>
            <p className="mt-0.5 text-[10px]" style={{ color: "var(--text-muted)" }}>
              {plan.goal_label} · {plan.split_label}
            </p>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-lg font-bold" style={{ color: "var(--accent)" }}>
            {plan.score.toFixed(1)}
          </p>
          <p className="text-[9px]" style={{ color: "var(--text-muted)" }}>
            匹配分
          </p>
        </div>
      </div>

      <p className="line-clamp-2 text-xs leading-5" style={{ color: "var(--text-muted)" }}>
        {plan.description}
      </p>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className="rounded-md px-2 py-1 text-[10px] font-medium" style={{ background: style.bg, color: style.color }}>
          {plan.difficulty_label}
        </span>
        <span className="rounded-md px-2 py-1 text-[10px]" style={{ background: "var(--surface2)", color: "var(--text-muted)" }}>
          {plan.total_weeks} 周
        </span>
        <span className="rounded-md px-2 py-1 text-[10px]" style={{ background: "var(--surface2)", color: "var(--text-muted)" }}>
          每周 {plan.sessions_per_week} 次
        </span>
      </div>

      <p className="mt-3 flex items-center gap-1.5 text-[11px]" style={{ color: "var(--text-muted)" }}>
        <CheckCircle2 size={12} style={{ color: "var(--success)" }} />
        {plan.match_reasons[0] ?? "根据用户画像完成排序"}
      </p>

      <div className="mt-4 flex items-center justify-between border-t pt-3" style={{ borderColor: "var(--border)" }}>
        <div className="flex items-center gap-1.5 text-[10px]" style={{ color: "var(--text-muted)" }}>
          <Clock3 size={11} />
          约 {plan.estimated_duration_minutes} 分钟
        </div>
        <button
          type="button"
          onClick={onAdopt}
          disabled={disabled}
          className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11px] font-semibold disabled:opacity-40"
          style={{ background: "rgba(108,99,255,0.1)", color: "var(--accent)" }}
        >
          {pending ? <Loader2 size={12} className="animate-spin" /> : <Dumbbell size={12} />}
          {pending ? "生成中" : "采用"}
        </button>
      </div>
    </article>
  );
}

function AlgorithmPanel({
  data,
  featured,
}: {
  data: PlanRecommendationResponse;
  featured: RecommendedPlan;
}) {
  return (
    <aside className="space-y-3">
      <div className="dashboard-card p-4">
        <div className="mb-4 flex items-center gap-2">
          <div
            className="flex h-8 w-8 items-center justify-center rounded-lg"
            style={{ background: "rgba(108,99,255,0.1)" }}
          >
            <BarChart3 size={15} style={{ color: "var(--accent)" }} />
          </div>
          <div>
            <p className="text-xs font-semibold" style={{ color: "var(--text)" }}>
              混合推荐模型
            </p>
            <p className="text-[10px]" style={{ color: "var(--text-muted)" }}>
              {data.model.name}
            </p>
          </div>
        </div>
        <div className="space-y-3">
          <WeightRow label="内容画像" weight={data.model.weights.profile} color="var(--accent)" />
          <WeightRow label="历史行为" weight={data.model.weights.behaviour} color="var(--success)" />
          <WeightRow label="群体采用" weight={data.model.weights.population} color="var(--warning)" />
        </div>
        <div className="mt-4 rounded-xl p-3 text-[11px] leading-5" style={{ background: "var(--surface2)", color: "var(--text-muted)" }}>
          当前首选计划由 {featured.component_scores.profile.toFixed(0)} 分内容匹配、
          {featured.component_scores.behaviour.toFixed(0)} 分行为匹配和
          {featured.component_scores.population.toFixed(0)} 分群体先验共同得到。
        </div>
      </div>

      <div className="dashboard-card p-4">
        <div className="mb-3 flex items-center gap-2">
          <ShieldCheck size={15} style={{ color: "var(--success)" }} />
          <p className="text-xs font-semibold" style={{ color: "var(--text)" }}>
            安全约束
          </p>
        </div>
        <div className="space-y-2 text-[11px]" style={{ color: "var(--text-muted)" }}>
          <div className="flex items-center justify-between">
            <span>伤病史数量</span>
            <span className="font-semibold" style={{ color: "var(--text)" }}>
              {data.user_snapshot.injury_count}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span>可用安全动作</span>
            <span className="font-semibold" style={{ color: "var(--success)" }}>
              {featured.safe_exercise_count}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span>高风险动作</span>
            <span className="font-semibold" style={{ color: "var(--danger)" }}>
              {featured.forbidden_exercise_count}
            </span>
          </div>
        </div>
      </div>

      <div className="dashboard-card p-4">
        <div className="mb-2 flex items-center gap-2">
          <Users size={14} style={{ color: "var(--accent)" }} />
          <p className="text-xs font-semibold" style={{ color: "var(--text)" }}>
            当前阶段
          </p>
        </div>
        <p className="text-[11px] leading-5" style={{ color: "var(--text-muted)" }}>
          现在以内容画像和历史行为为主。随着更多用户产生训练记录，群体采用信号会自动参与排序。
        </p>
      </div>
    </aside>
  );
}

function ScoreRing({ score }: { score: number }) {
  const degrees = Math.max(0, Math.min(100, score)) * 3.6;
  return (
    <div
      className="flex h-28 w-28 items-center justify-center rounded-full p-[7px]"
      style={{
        background: `conic-gradient(var(--accent) ${degrees}deg, var(--surface2) ${degrees}deg)`,
        boxShadow: "0 12px 32px -18px rgba(108,99,255,0.65)",
      }}
    >
      <div
        className="flex h-full w-full flex-col items-center justify-center rounded-full"
        style={{ background: "var(--surface)" }}
      >
        <span className="text-3xl font-bold" style={{ color: "var(--text)" }}>
          {score.toFixed(0)}
        </span>
        <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
          推荐匹配
        </span>
      </div>
    </div>
  );
}

function ComponentBar({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[10px]" style={{ color: "var(--text-muted)" }}>
        <span>{label}</span>
        <span>{value.toFixed(0)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full" style={{ background: "var(--surface2)" }}>
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: "var(--accent)" }}
        />
      </div>
    </div>
  );
}

function WeightRow({
  label,
  weight,
  color,
}: {
  label: string;
  weight: number;
  color: string;
}) {
  const percentage = Math.round(weight * 100);
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-[10px]" style={{ color: "var(--text-muted)" }}>
        <span>{label}</span>
        <span>{percentage}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full" style={{ background: "var(--surface2)" }}>
        <div className="h-full rounded-full" style={{ width: `${percentage}%`, background: color }} />
      </div>
    </div>
  );
}

function SnapshotMetric({
  icon,
  label,
  value,
  hint,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="dashboard-card p-3.5">
      <div className="mb-2 flex items-center gap-2 text-[10px] font-medium" style={{ color: "var(--text-muted)" }}>
        <span style={{ color: "var(--accent)" }}>{icon}</span>
        {label}
      </div>
      <p className="truncate text-lg font-bold" style={{ color: "var(--text)" }}>
        {value}
      </p>
      <p className="mt-1 truncate text-[10px]" style={{ color: "var(--text-muted)" }}>
        {hint}
      </p>
    </div>
  );
}

function InfoChip({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[10px]"
      style={{ background: "var(--surface2)", color: "var(--text-muted)" }}
    >
      {icon}
      {text}
    </span>
  );
}

function LoadingState() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="text-center">
        <div
          className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl"
          style={{ background: "rgba(108,99,255,0.1)" }}
        >
          <Loader2 size={23} className="animate-spin" style={{ color: "var(--accent)" }} />
        </div>
        <p className="text-sm font-medium" style={{ color: "var(--text)" }}>
          正在计算计划匹配度
        </p>
        <p className="mt-1 text-xs" style={{ color: "var(--text-muted)" }}>
          分析用户画像、训练行为与安全约束…
        </p>
      </div>
    </div>
  );
}
