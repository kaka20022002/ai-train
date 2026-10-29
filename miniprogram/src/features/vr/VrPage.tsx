import { useEffect, useRef, useState } from "react";
import { Button, Switch, Text, View } from "@tarojs/components";
import Taro, { useDidHide, useDidShow } from "@tarojs/taro";
import { exerciseNameCn } from "../../utils/exercise-labels";
import {
  createVrClient,
  currentVrIdentity,
  VrRequestError,
  type Overview,
  type ReferencePlan,
} from "./api";
import "./vr.scss";

const date = (stamp: number | string) => {
  const d = new Date(typeof stamp === "number" ? stamp * 1000 : stamp);
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};

export default function VrPage() {
  const [userId, setUserId] = useState("");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [pairing, setPairing] = useState<{
    id: string;
    code: string;
    expires_at: number;
  } | null>(null);
  const [now, setNow] = useState(0);
  const [visible, setVisible] = useState(true);
  const [includeToday, setIncludeToday] = useState(false);
  const [tab, setTab] = useState<"prepare" | "records">("prepare");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loginRequired, setLoginRequired] = useState(false);
  const [message, setMessage] = useState("");
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [help, setHelp] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const client = useRef<ReturnType<typeof createVrClient> | null>(null);
  const generation = useRef(0);
  const locked = useRef(false);
  const previousIdentity = useRef<ReturnType<typeof currentVrIdentity> | null>(
    null,
  );

  const stop = () => {
    generation.current++;
    client.current?.cancel();
    client.current = null;
    locked.current = false;
  };
  useDidHide(() => {
    setVisible(false);
    stop();
  });
  useEffect(() => stop, []);
  const run = async (
    action: (
      c: ReturnType<typeof createVrClient>,
      valid: () => boolean,
    ) => Promise<void>,
  ) => {
    if (locked.current || !client.current) return;
    locked.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    const epoch = generation.current;
    const valid = () => epoch === generation.current;
    try {
      await action(client.current, valid);
    } catch (e) {
      if (valid()) {
        setError(e instanceof Error ? e.message : "操作未完成，请重试。");
        setLoginRequired(e instanceof VrRequestError && e.status === 401);
      }
    } finally {
      if (valid()) {
        locked.current = false;
        setBusy(false);
      }
    }
  };
  const refresh = () =>
    run(async (c, valid) => {
      const data = await c.overview();
      if (valid()) {
        setOverview(data);
        setIncludeToday(
          Boolean(data.connection?.reference || data.pairing?.reference),
        );
        setConfirmDisconnect(false);
        setNow(Date.now());
        setPairing((current) =>
          current?.id === data.pairing?.id && !data.connection ? current : null,
        );
      }
    });
  useDidShow(() => {
    stop();
    const identity = currentVrIdentity();
    if (
      identity.userId !== previousIdentity.current?.userId ||
      identity.token !== previousIdentity.current?.token
    )
      setPairing(null);
    previousIdentity.current = identity;
    setVisible(true);
    setUserId(identity.userId);
    setOverview(null);
    setNow(Date.now());
    setIncludeToday(false);
    setLoginRequired(false);
    setConfirmDisconnect(false);
    setError("");
    setMessage("");
    setBusy(false);
    setExpanded(null);
    client.current = createVrClient(identity);
    void refresh();
  });

  const connection = overview?.connection;
  const backToWorkout = () => {
    const home = () => Taro.switchTab({ url: "/pages/workout/index" });
    if (Taro.getCurrentPages().length > 1) Taro.navigateBack({ fail: home });
    else home();
  };
  const today = overview?.today_reference;
  const ready = Boolean(overview) && !busy;
  const expiry = pairing?.expires_at || overview?.pairing?.expires_at || 0;
  useEffect(() => {
    if (!visible || !expiry) return;
    const tick = () => setNow(Date.now());
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [expiry, visible]);
  const seconds = Math.max(0, Math.ceil(expiry - now / 1000));
  const generate = () =>
    run(async (c, valid) => {
      // Never leave a possibly invalidated old code visible after a failed renewal.
      setPairing(null);
      const item = await c.pairing(includeToday);
      if (valid()) {
        setPairing(item);
        setNow(Date.now());
        setOverview((v) => v && { ...v, pairing: item });
        setMessage("请在头显输入短码。匹配后倒计时 3 秒开练，可取消。");
      }
    });
  const cancelPairing = () =>
    run(async (c, valid) => {
      await c.cancelPairing();
      if (!valid()) return;
      setPairing(null);
      setOverview((v) => v && { ...v, pairing: null });
      const latest = await c.overview();
      if (valid()) {
        setOverview(latest);
        setIncludeToday(
          Boolean(latest.connection?.reference || latest.pairing?.reference),
        );
        setMessage(
          latest.connection
            ? "头显已完成匹配。如需解除关联，请在此操作。"
            : "短码已取消。",
        );
      }
    });
  const saveReference = () =>
    run(async (c, valid) => {
      const item = await c.reference(includeToday);
      if (valid()) {
        setOverview((v) => v && { ...v, connection: item });
        setMessage(
          includeToday
            ? "参考计划已保存，头显下次准备时可读取。"
            : "已移除参考计划，仍可按 VR 安排跟练。",
        );
      }
    });
  const disconnect = () =>
    run(async (c, valid) => {
      await c.disconnect();
      if (valid()) {
        setOverview((v) => v && { ...v, connection: null });
        setIncludeToday(false);
        setConfirmDisconnect(false);
        setMessage("已解除关联，历史记录保留。");
      }
    });

  const referenceChoice = (
    <View className="vr-choice">
      <View className="vr-flex">
        <View className="vr-grow">
          <Text className="vr-label">附带今日计划作为参考</Text>
          <Text className="vr-small">
            {today
              ? "可选，不限制 VR 的动作或顺序。"
              : includeToday
                ? "已有参考可保留或取消，当前没有新计划。"
                : "当前没有今日计划，不影响关联或跟练。"}
          </Text>
        </View>
        <Switch
          color="#0f766e"
          checked={includeToday}
          disabled={
            !ready || (!connection && seconds > 0) || (!today && !includeToday)
          }
          onChange={(e) => setIncludeToday(e.detail.value)}
        />
      </View>
    </View>
  );

  return (
    <View className="vr-page">
      <View className="vr-top">
        <Button className="vr-back" onClick={backToWorkout}>
          ‹ 今日训练
        </Button>
        <Button
          className="vr-refresh"
          disabled={busy}
          onClick={() => void refresh()}
        >
          {busy ? "读取中…" : "刷新"}
        </Button>
      </View>
      <Text className="vr-eyebrow">DGTCOACH · VR TRAINING</Text>
      <Text className="vr-title">VR 跟练</Text>
      <Text className="vr-subtitle">戴上头显，跟着数字教练练。</Text>
      <Text className="vr-identity">
        当前用户 {userId || "未登录"} · 关联前请确认
      </Text>
      <View className="vr-tabs">
        <Button
          className={`vr-tab ${tab === "prepare" ? "vr-tab-active" : ""}`}
          onClick={() => setTab("prepare")}
        >
          连接与准备
        </Button>
        <Button
          className={`vr-tab ${tab === "records" ? "vr-tab-active" : ""}`}
          onClick={() => setTab("records")}
        >
          跟练记录
          {overview?.results.length ? ` · ${overview.results.length}` : ""}
        </Button>
      </View>
      {!!error && (
        <View className="vr-notice vr-error">
          <Text>{error}</Text>
          {(!userId || loginRequired) && (
            <Button
              className="vr-link"
              onClick={() => Taro.switchTab({ url: "/pages/profile/index" })}
            >
              去登录 ›
            </Button>
          )}
        </View>
      )}
      {!!message && (
        <View className="vr-notice vr-success">
          <Text>{message}</Text>
        </View>
      )}
      {tab === "prepare" ? (
        <>
          <View className="vr-card">
            <View className="vr-flex vr-card-heading">
              <Text className="vr-heading">
                {connection ? "头显已关联" : "生成头显连接短码"}
              </Text>
              <Text className="vr-step">01 / 准备</Text>
            </View>
            {!connection ? (
              <>
                <Text className="vr-body">
                  先确认当前账号，生成短码后到头显「网页连接跟练」输入。
                </Text>
                {expiry > 0 && (
                  <View className="vr-pairing-box">
                    {pairing && seconds > 0 ? (
                      <>
                        <Text className="vr-small">在头显输入以下短码</Text>
                        <Text className="vr-pairing-digits">
                          {pairing.code}
                        </Text>
                        <Text className="vr-small">
                          {Math.floor(seconds / 60)} 分 {seconds % 60} 秒后过期
                          · 仅限一次匹配
                        </Text>
                      </>
                    ) : (
                      <Text className="vr-body">
                        {seconds === 0
                          ? "短码已过期，请重新申请。"
                          : "已有待匹配短码，请在申请页面查看或重新生成。"}
                      </Text>
                    )}
                  </View>
                )}
                {referenceChoice}
                <Button
                  className="vr-primary"
                  disabled={!ready || (includeToday && !today)}
                  onClick={() => void generate()}
                >
                  {busy ? "请稍候…" : expiry ? "重新生成短码" : "生成连接短码"}
                </Button>
                {expiry > 0 && (
                  <>
                    <Button
                      className="vr-secondary"
                      disabled={busy}
                      onClick={() => void refresh()}
                    >
                      已在头显输入，刷新关联
                    </Button>
                    <Button
                      className="vr-unlink"
                      disabled={busy}
                      onClick={() => void cancelPairing()}
                    >
                      取消短码
                    </Button>
                  </>
                )}
                <Text className="vr-small">
                  重新生成会使旧码失效。请只向自己的头显输入此码。
                </Text>
              </>
            ) : (
              <>
                <View className="vr-device">
                  <View className="vr-grow">
                    <Text className="vr-device-name">
                      {connection.device_name}
                    </Text>
                    <Text className="vr-small">
                      关联于 {date(connection.connected_at)}
                    </Text>
                  </View>
                  <Text className="vr-badge">已关联</Text>
                </View>
                <View className="vr-next">
                  <Text className="vr-label">接下来，请回到头显</Text>
                  <Text className="vr-body">
                    首次匹配后显示用户，倒计时 3
                    秒开始默认课表，可取消后自选动作。再次进入需确认用户。
                  </Text>
                </View>
                {referenceChoice}
                {!!connection.reference && (
                  <Text className="vr-small">
                    已保存参考：{connection.reference.title}
                    。这不表示头显已读取。
                  </Text>
                )}
                <Button
                  className="vr-secondary"
                  disabled={busy || (includeToday && !today)}
                  onClick={() => void saveReference()}
                >
                  保存参考设置
                </Button>
                <Button
                  className="vr-unlink"
                  disabled={busy}
                  onClick={() => setConfirmDisconnect(true)}
                >
                  解除关联
                </Button>
                {confirmDisconnect && (
                  <View className="vr-confirm">
                    <Text className="vr-body">
                      解除后头显不能读取参考或上传新结果。请先结束训练并同步，历史记录会保留。
                    </Text>
                    <View className="vr-flex">
                      <Button
                        className="vr-secondary vr-grow"
                        disabled={busy}
                        onClick={() => setConfirmDisconnect(false)}
                      >
                        保留关联
                      </Button>
                      <Button
                        className="vr-danger vr-grow"
                        disabled={busy}
                        onClick={() => void disconnect()}
                      >
                        确认解除
                      </Button>
                    </View>
                  </View>
                )}
              </>
            )}
          </View>
          <View className="vr-flow">
            <Text>01 这里生成短码</Text>
            <Text>›</Text>
            <Text>02 头显输入开练</Text>
            <Text>›</Text>
            <Text>03 训练回顾</Text>
          </View>
          <View className="vr-card vr-reference">
            <Text className="vr-step">今日计划 · 可选参考</Text>
            {today ? (
              <ReferencePreview plan={today} />
            ) : (
              <>
                <Text className="vr-heading">按 VR 的安排也能开练</Text>
                <Text className="vr-body">
                  不需要先生成计划。关联后，直接在 VR 中选择支持的训练。
                </Text>
                <Button
                  className="vr-link"
                  onClick={() =>
                    Taro.navigateTo({ url: "/pages/generate/index" })
                  }
                >
                  也可以先创建计划 ›
                </Button>
              </>
            )}
            <Text className="vr-reference-note">
              仅提供训练方向，动作与组次以 VR 端为主。
            </Text>
          </View>
          <Button className="vr-help" onClick={() => setHelp((v) => !v)}>
            如何在头显输入？ {help ? "−" : "+"}
          </Button>
          {help && (
            <Text className="vr-help-body">
              在头显首页进入「网页连接跟练」，输入这里生成的六位码，点击「匹配并开始」。匹配后倒计时
              3 秒，可取消。两端需连接同一服务；短码过期后在此重新生成。
            </Text>
          )}
          <Text className="vr-footer">
            训练中无实时同步或远程控制，暂停与结束请在头显操作。
          </Text>
        </>
      ) : (
        <>
          <Text className="vr-record-intro">
            头显回传的最近 20 场实际训练 · 手动刷新获取最新结果
          </Text>
          {!overview?.results.length ? (
            <View className="vr-card vr-empty">
              <Text className="vr-heading">
                {busy ? "正在读取记录…" : "还没有回传的跟练记录"}
              </Text>
              <Text className="vr-body">
                在头显完成训练并同步后，这里会展示实际完成内容。
              </Text>
              <Button
                className="vr-secondary"
                onClick={() => setTab("prepare")}
              >
                返回连接与准备
              </Button>
            </View>
          ) : (
            overview.results.map((result) => (
              <View className="vr-card vr-result" key={result.id}>
                <View
                  className="vr-flex"
                  onClick={() =>
                    setExpanded(expanded === result.id ? null : result.id)
                  }
                >
                  <View className="vr-grow">
                    <Text className="vr-label">{date(result.ended_at)}</Text>
                    <Text className="vr-small">
                      {result.actions.length} 个动作 ·{" "}
                      {Math.round(
                        (Date.parse(result.ended_at) -
                          Date.parse(result.started_at)) /
                          60000,
                      ) < 1
                        ? "不足 1"
                        : Math.round(
                            (Date.parse(result.ended_at) -
                              Date.parse(result.started_at)) /
                              60000,
                          )}{" "}
                      分钟 · VR 实际安排
                    </Text>
                  </View>
                  <Text className="vr-outcome">
                    {result.outcome === "completed" ? "已完成" : "提前结束"}{" "}
                    {expanded === result.id ? "−" : "+"}
                  </Text>
                </View>
                {expanded === result.id && (
                  <View className="vr-result-detail">
                    {result.actions.map((action, i) => (
                      <View
                        className="vr-action"
                        key={`${action.action_id}-${i}`}
                      >
                        <Text className="vr-label">{action.action_name}</Text>
                        <Text className="vr-body">
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
                        </Text>
                        <Text className="vr-small">
                          {action.quality_score_01 == null
                            ? "未提供有效质量评分"
                            : `动作质量 ${Math.round(action.quality_score_01 * 100)} 分`}
                          {action.tracking_good_ratio_01 != null
                            ? ` · 追踪有效占比 ${Math.round(action.tracking_good_ratio_01 * 100)}%`
                            : ""}
                        </Text>
                      </View>
                    ))}
                    <Text className="vr-small">
                      接收于 {date(result.received_at)} · 评分由设备提供
                    </Text>
                  </View>
                )}
              </View>
            ))
          )}
          <Text className="vr-footer">
            VR 记录独立保存，不会自动勾选今日计划或推进周期计划。
          </Text>
        </>
      )}
    </View>
  );
}

function ReferencePreview({ plan }: { plan: ReferencePlan }) {
  const phased = plan.phases
    ? [...(plan.phases.main_lifts || []), ...(plan.phases.accessories || [])]
    : [];
  const items = phased.length ? phased : plan.key_exercises;
  return (
    <>
      <Text className="vr-heading">{plan.title}</Text>
      <Text className="vr-body">
        第 {plan.source_week} 周
        {plan.estimated_duration_minutes
          ? ` · 约 ${plan.estimated_duration_minutes} 分钟`
          : ""}
      </Text>
      {items.slice(0, 5).map((ex, i) => (
        <View className="vr-reference-ex" key={`${ex.name}-${i}`}>
          <Text className="vr-grow">{exerciseNameCn(ex.name)}</Text>
          <Text>
            {ex.sets} 组 × {ex.reps}
          </Text>
        </View>
      ))}
      {items.length > 5 && (
        <Text className="vr-small">另有 {items.length - 5} 个动作</Text>
      )}
      <Button
        className="vr-link"
        onClick={() => Taro.switchTab({ url: "/pages/workout/index" })}
      >
        查看完整今日计划 ›
      </Button>
    </>
  );
}
