import { useState } from "react";
import { View, Text, Input } from "@tarojs/components";
import Taro, { useDidShow } from "@tarojs/taro";
import {
  api,
  clearAuth,
  devLogin,
  ensureLoggedIn,
  getStoredUserId,
  type UserProfile,
  wechatLogin,
} from "../../services/api";
import {
  FITNESS_CN,
  GENDER_CN,
  GOAL_CN,
  INJURY_CONDITION_CN,
  JOINT_CN,
  SEVERITY_CN,
} from "../../utils/labels";
import "./index.scss";

export default function ProfilePage() {
  const [userId, setUserId] = useState("");
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [customId, setCustomId] = useState("usr_demo");
  const [loading, setLoading] = useState(false);
  const [loggedIn, setLoggedIn] = useState(!!getStoredUserId());

  const refresh = async () => {
    setLoading(true);
    try {
      const uid = await ensureLoggedIn();
      setUserId(uid);
      setLoggedIn(true);
      const p = await api.getUser(uid);
      setProfile(p);
    } catch (e: any) {
      setProfile(null);
      Taro.showToast({
        title: e?.message?.slice(0, 40) || "加载档案失败",
        icon: "none",
      });
    } finally {
      setLoading(false);
    }
  };

  useDidShow(() => {
    if (getStoredUserId()) refresh();
    else {
      setLoggedIn(false);
      setUserId("");
      setProfile(null);
    }
  });

  const onDevLogin = async () => {
    try {
      setLoading(true);
      const data = await devLogin(customId.trim() || "usr_demo");
      setUserId(data.user_id);
      setLoggedIn(true);
      Taro.showToast({ title: "登录成功", icon: "success" });
      const p = await api.getUser(data.user_id);
      setProfile(p);
    } catch (e: any) {
      Taro.showToast({ title: e?.message?.slice(0, 40) || "登录失败", icon: "none" });
    } finally {
      setLoading(false);
    }
  };

  const onQuickLogin = async (id: string) => {
    setCustomId(id);
    try {
      setLoading(true);
      const data = await devLogin(id);
      setUserId(data.user_id);
      setLoggedIn(true);
      Taro.showToast({ title: `已切换为 ${id}`, icon: "success" });
      const p = await api.getUser(data.user_id);
      setProfile(p);
    } catch (e: any) {
      Taro.showToast({ title: e?.message?.slice(0, 40) || "登录失败", icon: "none" });
    } finally {
      setLoading(false);
    }
  };

  const onWechatLogin = async () => {
    try {
      setLoading(true);
      const data = await wechatLogin();
      setUserId(data.user_id);
      setLoggedIn(true);
      Taro.showToast({
        title: data.mode === "dev" ? "开发模式登录成功" : "微信登录成功",
        icon: "success",
      });
      const p = await api.getUser(data.user_id);
      setProfile(p);
    } catch (e: any) {
      Taro.showToast({ title: e?.message?.slice(0, 40) || "微信登录失败", icon: "none" });
    } finally {
      setLoading(false);
    }
  };

  const onLogout = () => {
    clearAuth();
    setUserId("");
    setProfile(null);
    setLoggedIn(false);
    Taro.showToast({ title: "已退出", icon: "none" });
  };

  const initial = (userId || "U").slice(0, 1).toUpperCase();

  return (
    <View className="page">
      <View className="card hero-card">
        <View className="row-between">
          <View className="hero-left">
            <Text className="hero-kicker">PROFILE</Text>
            <Text className="title">{loggedIn ? "我的档案" : "欢迎使用"}</Text>
            <Text className="subtitle">
              {loggedIn
                ? loading
                  ? "正在刷新档案…"
                  : `已登录 · ${userId}`
                : "先登录后才能同步训练与教练对话"}
            </Text>
          </View>
          <View className="avatar">
            <Text>{initial}</Text>
          </View>
        </View>
      </View>

      {!loggedIn && (
        <View className="card">
          <Text className="section-title">快速开始</Text>
          <Text className="subtitle">
            本地调试推荐一键登录演示账号，无需微信 AppSecret。
          </Text>
          <View className="quick-logins">
            <View className="btn-primary" onClick={() => onQuickLogin("usr_demo")}>
              <Text>登录 usr_demo</Text>
            </View>
            <View className="btn-ghost stack-gap" onClick={() => onQuickLogin("usr_001")}>
              <Text>登录 usr_001（演示伤病用户）</Text>
            </View>
          </View>
        </View>
      )}

      <View className="card">
        <Text className="section-title">功能入口</Text>
        <View className="menu-grid">
          <View
            className="menu-item"
            onClick={() => Taro.navigateTo({ url: "/pages/profile-edit/index" })}
          >
            <Text className="menu-icon">✎</Text>
            <Text className="menu-text">编辑档案</Text>
            <Text className="menu-hint">身体与目标</Text>
          </View>
          <View className="menu-item" onClick={() => Taro.navigateTo({ url: "/pages/dashboard/index" })}>
            <Text className="menu-icon">◎</Text>
            <Text className="menu-text">仪表盘</Text>
            <Text className="menu-hint">趋势总览</Text>
          </View>
          <View className="menu-item" onClick={() => Taro.navigateTo({ url: "/pages/generate/index" })}>
            <Text className="menu-icon">+</Text>
            <Text className="menu-text">生成计划</Text>
            <Text className="menu-hint">智能编排</Text>
          </View>
          <View className="menu-item" onClick={() => Taro.navigateTo({ url: "/pages/risk/index" })}>
            <Text className="menu-icon">⬡</Text>
            <Text className="menu-text">风险分析</Text>
            <Text className="menu-hint">安全评估</Text>
          </View>
          <View
            className="menu-item"
            onClick={() =>
              Taro.navigateTo({ url: "/pages/video-analysis/index" })
            }
          >
            <Text className="menu-icon">▶</Text>
            <Text className="menu-text">视频动作分析</Text>
            <Text className="menu-hint">上传视频检查动作</Text>
          </View>
        </View>
      </View>

      {profile && (
        <View className="card">
          <View className="row-between">
            <Text className="section-title">基础信息</Text>
            <Text
              className="tag"
              onClick={() => Taro.navigateTo({ url: "/pages/profile-edit/index" })}
            >
              编辑档案
            </Text>
          </View>
          <View className="info-grid">
            <View className="info-item">
              <Text className="info-label">年龄</Text>
              <Text className="info-value">{profile.basic_info?.age ?? "—"}</Text>
            </View>
            <View className="info-item">
              <Text className="info-label">性别</Text>
              <Text className="info-value">
                {GENDER_CN[profile.basic_info?.gender || ""] ||
                  profile.basic_info?.gender ||
                  "—"}
              </Text>
            </View>
            <View className="info-item">
              <Text className="info-label">身高</Text>
              <Text className="info-value">
                {profile.basic_info?.height_cm
                  ? `${profile.basic_info.height_cm} cm`
                  : "—"}
              </Text>
            </View>
            <View className="info-item">
              <Text className="info-label">体重</Text>
              <Text className="info-value">
                {profile.basic_info?.weight_kg
                  ? `${profile.basic_info.weight_kg} kg`
                  : "—"}
              </Text>
            </View>
            <View className="info-item">
              <Text className="info-label">水平</Text>
              <Text className="info-value">
                {FITNESS_CN[profile.fitness_level] || profile.fitness_level}
              </Text>
            </View>
            <View className="info-item">
              <Text className="info-label">目标</Text>
              <Text className="info-value">
                {GOAL_CN[profile.fitness_goal || ""] ||
                  profile.fitness_goal ||
                  "未设置"}
              </Text>
            </View>
            <View className="info-item">
              <Text className="info-label">每周次数</Text>
              <Text className="info-value">
                {profile.training_frequency
                  ? `${profile.training_frequency} 次`
                  : "—"}
              </Text>
            </View>
          </View>

          <View className="divider" />
          <Text className="section-title">伤病史</Text>
          {profile.medical_history?.length ? (
            profile.medical_history.map((m, i) => (
              <View className="injury-row" key={`${m.location}-${i}`}>
                <Text className="tag warn">
                  {SEVERITY_CN[m.severity] || m.severity}
                </Text>
                <Text className="injury-text">
                  {JOINT_CN[m.location] || m.location} ·{" "}
                  {INJURY_CONDITION_CN[m.condition] || m.condition}
                </Text>
              </View>
            ))
          ) : (
            <Text className="muted">暂无伤病记录</Text>
          )}

          <View
            className="btn-primary stack-gap"
            onClick={() => Taro.navigateTo({ url: "/pages/profile-edit/index" })}
          >
            <Text>编辑身体状况与目标</Text>
          </View>
        </View>
      )}

      {loggedIn && !profile && !loading && (
        <View className="card">
          <Text className="section-title">完善档案</Text>
          <Text className="subtitle">
            还没有身体数据。填写后，训练计划与 AI 教练会更贴合你的情况。
          </Text>
          <View
            className="btn-primary stack-gap"
            onClick={() => Taro.navigateTo({ url: "/pages/profile-edit/index" })}
          >
            <Text>去填写档案</Text>
          </View>
        </View>
      )}

      <View className="card">
        <Text className="section-title">账号与登录</Text>
        <Text className="subtitle">切换用户 ID，或使用微信登录（未配置密钥时走开发模式）。</Text>

        <Text className="field-label">用户 ID</Text>
        <Input
          className="input"
          value={customId}
          placeholder="例如 usr_demo"
          onInput={(e) => setCustomId(e.detail.value)}
        />

        <View className="btn-primary" onClick={onDevLogin}>
          <Text>{loading ? "处理中…" : "使用该 ID 登录"}</Text>
        </View>
        <View className="btn-ghost stack-gap" onClick={onWechatLogin}>
          <Text>微信登录</Text>
        </View>
        {loggedIn && (
          <View className="btn-danger stack-gap" onClick={onLogout}>
            <Text>退出登录</Text>
          </View>
        )}
      </View>
    </View>
  );
}
