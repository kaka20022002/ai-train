"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Check,
  ChevronDown,
  CircleHelp,
  ClipboardList,
  Headset,
  Link2,
  Loader2,
  RefreshCw,
  Unplug,
} from "lucide-react";
import { useUser } from "@/contexts/UserContext";
import { ExerciseName } from "@/components/ExerciseName";
import { vrApi } from "./api";
import type { Overview, ReferencePlan, TrainingResult } from "./api";
import styles from "./vr.module.css";

const date = (stamp: number | string) =>
  new Date(typeof stamp === "number" ? stamp * 1000 : stamp).toLocaleString(
    "zh-CN",
    { hour12: false },
  );

export function VrFollowPage() {
  const { userId } = useUser();
  const [identityReady, setIdentityReady] = useState(false);
  // Let the shared provider restore the selected account before making requests.
  useEffect(() => {
    setIdentityReady(true);
  }, []);
  return (
    <Workspace
      key={userId}
      userId={userId}
      ready={identityReady && Boolean(userId.trim())}
    />
  );
}

function Workspace({ userId, ready }: { userId: string; ready: boolean }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [pairing, setPairing] = useState<{
    id: string;
    code: string;
    expires_at: number;
  } | null>(null);
  const [now, setNow] = useState(0);
  const [includeToday, setIncludeToday] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [tab, setTab] = useState<"prepare" | "records">("prepare");
  const request = useRef<AbortController | null>(null);
  const locked = useRef(false);

  const run = useCallback(
    async (name: string, action: (signal: AbortSignal) => Promise<void>) => {
      if (locked.current) return;
      locked.current = true;
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      setBusy(name);
      setError(null);
      setMessage(null);
      try {
        await action(controller.signal);
      } catch (e) {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "操作未完成，请重试。");
      } finally {
        if (!controller.signal.aborted) {
          locked.current = false;
          setBusy(null);
        }
      }
    },
    [],
  );

  const refresh = useCallback(
    () =>
      run("load", async (signal) => {
        const data = await vrApi.overview(userId, signal);
        if (signal.aborted) return;
        setOverview(data);
        setConfirmDisconnect(false);
        setIncludeToday(
          Boolean(data.connection?.reference || data.pairing?.reference),
        );
        setNow(Date.now());
        setPairing((current) =>
          current?.id === data.pairing?.id && !data.connection ? current : null,
        );
      }),
    [run, userId],
  );

  useEffect(() => {
    if (ready) void refresh();
    return () => {
      request.current?.abort();
      locked.current = false;
    };
  }, [ready, refresh]);

  const connection = overview?.connection;
  const today = overview?.today_reference;
  const disabled = Boolean(busy) || !ready || overview === null;

  const expiry = pairing?.expires_at || overview?.pairing?.expires_at || 0;
  useEffect(() => {
    if (!expiry) return;
    const tick = () => setNow(Date.now());
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [expiry]);
  const seconds = Math.max(0, Math.ceil(expiry - now / 1000));
  const generate = () =>
    run("generate", async (signal) => {
      // A lost response may still invalidate the previous server-side code.
      setPairing(null);
      const item = await vrApi.pairing(userId, includeToday, signal);
      if (signal.aborted) return;
      setPairing(item);
      setNow(Date.now());
      setOverview((current) => current && { ...current, pairing: item });
      setMessage(
        "短码已生成，请在头显输入。匹配后显示用户并倒计时 3 秒，可取消。",
      );
    });
  const cancelPairing = () =>
    run("cancel", async (signal) => {
      await vrApi.cancelPairing(userId, signal);
      if (signal.aborted) return;
      setPairing(null);
      setOverview((current) => current && { ...current, pairing: null });
      const latest = await vrApi.overview(userId, signal);
      if (signal.aborted) return;
      setOverview(latest);
      setIncludeToday(
        Boolean(latest.connection?.reference || latest.pairing?.reference),
      );
      setMessage(
        latest.connection
          ? "头显已完成匹配。如需解除关联，请在此操作。"
          : "短码已取消。",
      );
    });

  const saveReference = () =>
    run("reference", async (signal) => {
      const item = await vrApi.reference(userId, includeToday, signal);
      if (signal.aborted) return;
      setOverview((current) => current && { ...current, connection: item });
      setMessage(
        includeToday
          ? "参考计划已保存，头显下次训练准备时可读取。"
          : "已移除参考计划，仍可按 VR 的训练安排跟练。",
      );
    });

  const disconnect = () =>
    run("disconnect", async (signal) => {
      await vrApi.disconnect(userId, signal);
      if (signal.aborted) return;
      setOverview((current) => current && { ...current, connection: null });
      setConfirmDisconnect(false);
      setIncludeToday(false);
      setMessage("已解除关联。历史记录保留；新的关联请在这里重新生成短码。");
    });

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>DGTCOACH · VR TRAINING</p>
          <h1>VR 跟练</h1>
          <p className={styles.subtitle}>
            戴上头显，跟着数字教练练。训练安排以 VR 端为主。
          </p>
          <p className={styles.identity}>
            当前用户 <span>{userId}</span> · 请确认后再关联头显
          </p>
        </div>
        <button
          className={styles.secondary}
          onClick={() => void refresh()}
          disabled={!ready || Boolean(busy)}
          aria-label="刷新关联与训练记录"
        >
          <RefreshCw size={15} className={busy === "load" ? styles.spin : ""} />
          刷新
        </button>
      </header>

      <div className={styles.tabs} role="tablist" aria-label="VR 跟练内容">
        <button
          id="vr-prepare-tab"
          role="tab"
          aria-selected={tab === "prepare"}
          aria-controls="vr-prepare-panel"
          onClick={() => setTab("prepare")}
        >
          连接与准备
        </button>
        <button
          id="vr-records-tab"
          role="tab"
          aria-selected={tab === "records"}
          aria-controls="vr-records-panel"
          onClick={() => setTab("records")}
        >
          跟练记录
          {overview?.results.length ? (
            <span>{overview.results.length}</span>
          ) : null}
        </button>
      </div>

      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}
      {message && (
        <div className={styles.success} role="status">
          <Check size={17} />
          {message}
        </div>
      )}
      {busy === "load" && (
        <p className={styles.loading}>
          <Loader2 size={17} className={styles.spin} />
          正在读取连接信息…
        </p>
      )}

      {tab === "prepare" && (
        <section
          id="vr-prepare-panel"
          role="tabpanel"
          aria-labelledby="vr-prepare-tab"
        >
          <div className={styles.layout}>
            <div className={styles.mainColumn}>
              <section
                className={styles.card}
                aria-labelledby="connection-title"
              >
                <div className={styles.cardHeading}>
                  <span className={styles.icon}>
                    <Headset size={23} />
                  </span>
                  <div>
                    <h2 id="connection-title">
                      {connection ? "头显已关联" : "生成头显连接短码"}
                    </h2>
                    <p>
                      {connection
                        ? "关联用于训练前准备，不代表头显当前在线。"
                        : "在这里申请短码，再到头显「网页连接跟练」输入。"}
                    </p>
                  </div>
                </div>

                {!connection ? (
                  <>
                    {expiry > 0 && (
                      <div className={styles.pairingBox}>
                        {pairing && seconds > 0 ? (
                          <>
                            <p>在头显输入以下短码</p>
                            <strong
                              className={styles.pairingDigits}
                              aria-label="连接短码"
                            >
                              {pairing.code}
                            </strong>
                            <p>
                              {Math.floor(seconds / 60)} 分 {seconds % 60}{" "}
                              秒后过期 · 仅限一次匹配
                            </p>
                          </>
                        ) : (
                          <p>
                            {seconds === 0
                              ? "短码已过期，请重新申请。"
                              : "当前用户已有待匹配短码。请在申请页面查看，或重新生成。"}
                          </p>
                        )}
                      </div>
                    )}
                    <ReferenceChoice
                      checked={includeToday}
                      onChange={setIncludeToday}
                      available={Boolean(today)}
                      disabled={Boolean(busy) || !ready || seconds > 0}
                    />
                    <div className={styles.actions}>
                      <button
                        className={styles.primary}
                        disabled={disabled || (includeToday && !today)}
                        onClick={() => void generate()}
                      >
                        <Link2 size={16} />
                        {busy === "generate"
                          ? "正在生成…"
                          : expiry
                            ? "重新生成短码"
                            : "生成连接短码"}
                      </button>
                      {expiry > 0 && (
                        <button
                          className={styles.textButton}
                          disabled={Boolean(busy)}
                          onClick={() => void cancelPairing()}
                        >
                          取消短码
                        </button>
                      )}
                    </div>
                    {expiry > 0 && (
                      <button
                        className={styles.secondary}
                        disabled={Boolean(busy)}
                        onClick={() => void refresh()}
                      >
                        已在头显输入，刷新关联
                      </button>
                    )}
                    <p className={styles.hint}>
                      重新生成会使旧码失效。请只向自己的头显输入此码；匹配后按默认
                      VR 课表开练。
                    </p>
                  </>
                ) : (
                  <>
                    <div className={styles.device}>
                      <div>
                        <strong>{connection.device_name}</strong>
                        <span>关联于 {date(connection.connected_at)}</span>
                      </div>
                      <span className={styles.badge}>
                        <Check size={13} />
                        已关联
                      </span>
                    </div>
                    <div className={styles.nextStep}>
                      <strong>接下来，请回到头显</strong>
                      <p>
                        首次匹配后显示用户，倒计时 3
                        秒开始默认课表，可取消后自选动作。再次进入需确认用户。网页无需保持打开。
                      </p>
                    </div>
                    <ReferenceChoice
                      checked={includeToday}
                      onChange={setIncludeToday}
                      available={Boolean(today)}
                      disabled={Boolean(busy)}
                    />
                    {connection.reference && (
                      <p className={styles.hint}>
                        已保存参考：{connection.reference.title}
                        。这不表示头显已读取。
                      </p>
                    )}
                    <div className={styles.actions}>
                      <button
                        className={styles.secondary}
                        disabled={Boolean(busy) || (includeToday && !today)}
                        onClick={() => void saveReference()}
                      >
                        {busy === "reference" ? (
                          <Loader2 size={15} className={styles.spin} />
                        ) : (
                          <ClipboardList size={15} />
                        )}
                        保存参考设置
                      </button>
                      <button
                        className={styles.textButton}
                        disabled={Boolean(busy)}
                        onClick={() => setConfirmDisconnect(true)}
                      >
                        <Unplug size={15} />
                        解除关联
                      </button>
                    </div>
                    {confirmDisconnect && (
                      <div
                        className={styles.confirm}
                        role="group"
                        aria-label="确认解除头显关联"
                      >
                        <p>
                          解除后头显不能再读取参考或上传新结果。建议先结束训练并完成结果同步；现有记录会保留。
                        </p>
                        <div className={styles.actions}>
                          <button
                            className={styles.dangerButton}
                            disabled={Boolean(busy)}
                            onClick={() => void disconnect()}
                          >
                            确认解除
                          </button>
                          <button
                            className={styles.secondary}
                            disabled={Boolean(busy)}
                            onClick={() => setConfirmDisconnect(false)}
                          >
                            保留关联
                          </button>
                        </div>
                      </div>
                    )}
                  </>
                )}
              </section>

              <section className={styles.steps} aria-label="跟练流程">
                {[
                  ["01", "这里生成短码", "确认当前用户"],
                  ["02", "头显输入并跟练", "匹配后倒计时开始"],
                  ["03", "训练后回顾", "结果回传后在此查看"],
                ].map(([n, title, description]) => (
                  <div key={n}>
                    <span>{n}</span>
                    <h3>{title}</h3>
                    <p>{description}</p>
                  </div>
                ))}
              </section>
              <details className={styles.help}>
                <summary>
                  <CircleHelp size={16} />
                  如何在头显输入？
                  <ChevronDown size={15} />
                </summary>
                <p>
                  头显首页进入「网页连接跟练」，用数字键盘输入此处生成的六位码，再点击「匹配并开始」。匹配后显示用户身份并倒计时
                  3 秒，可取消或改选动作。
                </p>
                <p>
                  两端需连接同一服务。短码过期后在这里重新生成；训练中无需保持网页打开。
                </p>
              </details>
            </div>

            <aside className={styles.sideColumn}>
              <section className={styles.card}>
                <div className={styles.sectionLabel}>
                  <ClipboardList size={17} />
                  今日计划 · 可选参考
                </div>
                {today ? (
                  <ReferencePreview plan={today} />
                ) : (
                  <>
                    <h2>按 VR 的安排也能开练</h2>
                    <p className={styles.muted}>
                      不需要先生成网页计划。关联后，你可以直接在 VR
                      中选择支持的训练。
                    </p>
                    <Link href="/generate" className={styles.inlineLink}>
                      也可以先创建今日计划
                      <ArrowRight size={14} />
                    </Link>
                  </>
                )}
                <div className={styles.referenceNote}>
                  今日计划只提供训练方向参考。VR
                  可根据自己的动作库调整内容，不要求逐项一致。
                </div>
              </section>
              <div className={styles.quietNote}>
                <strong>专心在 VR 里练</strong>
                <p>
                  训练中没有实时同步、远程控制或网页开练按钮。暂停与结束在头显内操作。
                </p>
              </div>
            </aside>
          </div>
        </section>
      )}

      {tab === "records" && (
        <section
          id="vr-records-panel"
          role="tabpanel"
          aria-labelledby="vr-records-tab"
          className={styles.records}
        >
          <div className={styles.recordsHeading}>
            <h2>VR 实际训练记录</h2>
            <p>
              展示头显训练结束后回传的最近 20 场记录，点击刷新读取最新结果。
            </p>
          </div>
          {overview?.results.length ? (
            overview.results.map((result) => (
              <ResultCard key={result.id} result={result} />
            ))
          ) : (
            <div className={styles.empty}>
              <Headset size={30} />
              <h3>
                {busy === "load" ? "正在读取训练记录" : "还没有回传的跟练记录"}
              </h3>
              <p>
                在头显完成训练并回传结果后，这里会展示实际完成内容。不会根据网页计划推算完成情况。
              </p>
              <button
                className={styles.secondary}
                onClick={() => setTab("prepare")}
              >
                返回连接与准备
                <ArrowRight size={14} />
              </button>
            </div>
          )}
          <p className={styles.hint}>
            VR
            记录独立保存，不会自动勾选网页今日计划或推进周期计划；未回传的训练暂不展示。
          </p>
        </section>
      )}
    </main>
  );
}

function ReferenceChoice({
  checked,
  onChange,
  available,
  disabled,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  available: boolean;
  disabled: boolean;
}) {
  return (
    <label className={styles.checkbox}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled || (!available && !checked)}
      />
      <span>
        <strong>附带今日计划作为参考</strong>
        <small>
          {available
            ? "可选；不限制 VR 的动作选择或训练顺序。"
            : checked
              ? "已保存的参考可保留或取消；当前没有新的今日计划。"
              : "当前没有今日计划，不影响关联或 VR 跟练。"}
        </small>
      </span>
    </label>
  );
}

function ReferencePreview({ plan }: { plan: ReferencePlan }) {
  const phases = plan.phases;
  const phased = phases
    ? [...(phases.main_lifts || []), ...(phases.accessories || [])]
    : [];
  const items = phased.length ? phased : plan.key_exercises;
  return (
    <>
      <h2>{plan.title}</h2>
      <p className={styles.muted}>
        第 {plan.source_week} 周
        {plan.estimated_duration_minutes
          ? ` · 约 ${plan.estimated_duration_minutes} 分钟`
          : ""}
      </p>
      {items.length > 0 && (
        <ul className={styles.exerciseList}>
          {items.slice(0, 5).map((ex, i) => (
            <li key={`${ex.name}-${i}`}>
              <ExerciseName name={ex.name} showEnglish={false} />
              <span>
                {ex.sets} 组 × {ex.reps}
              </span>
            </li>
          ))}
        </ul>
      )}
      {items.length > 5 && (
        <p className={styles.hint}>另有 {items.length - 5} 个动作</p>
      )}
      <Link href="/workout" className={styles.inlineLink}>
        查看完整今日计划
        <ArrowRight size={14} />
      </Link>
    </>
  );
}

function ResultCard({ result }: { result: TrainingResult }) {
  const minutes = Math.max(
    0,
    Math.round(
      (Date.parse(result.ended_at) - Date.parse(result.started_at)) / 60000,
    ),
  );
  return (
    <details className={styles.result}>
      <summary>
        <div>
          <strong>{date(result.ended_at)}</strong>
          <p>
            {result.actions.length} 个动作 · {minutes < 1 ? "不足 1" : minutes}{" "}
            分钟 · VR 实际安排
          </p>
        </div>
        <span className={styles.resultOutcome}>
          {result.outcome === "completed" ? "已完成" : "提前结束"}
          <ChevronDown size={16} />
        </span>
      </summary>
      <div className={styles.resultBody}>
        {result.actions.map((action, i) => (
          <div className={styles.resultAction} key={`${action.action_id}-${i}`}>
            <strong>{action.action_name}</strong>
            <span>
              {[
                action.completed_sets != null
                  ? `${action.completed_sets} 组`
                  : null,
                action.completed_reps != null
                  ? `${action.completed_reps} 次`
                  : null,
                action.duration_seconds != null
                  ? `${Math.round(action.duration_seconds)} 秒`
                  : null,
              ]
                .filter(Boolean)
                .join(" · ") || "完成量未提供"}
            </span>
            <small>
              {action.quality_score_01 == null
                ? "未提供有效质量评分"
                : `动作质量 ${Math.round(action.quality_score_01 * 100)} 分`}
              {action.tracking_good_ratio_01 != null
                ? ` · 追踪有效占比 ${Math.round(action.tracking_good_ratio_01 * 100)}%`
                : ""}
            </small>
          </div>
        ))}
        <p className={styles.hint}>
          结果接收于 {date(result.received_at)}
          。以上为设备回传，网页未重新计算评分。
        </p>
      </div>
    </details>
  );
}
