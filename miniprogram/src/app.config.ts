export default defineAppConfig({
  pages: [
    "pages/workout/index",
    "pages/plans/index",
    "pages/exercises/index",
    "pages/coach/index",
    "pages/profile/index",
    "pages/session/index",
    "pages/dashboard/index",
    "pages/generate/index",
    "pages/risk/index",
  ],
  window: {
    backgroundTextStyle: "light",
    navigationBarBackgroundColor: "#0f1419",
    navigationBarTitleText: "AI 健身教练",
    navigationBarTextStyle: "white",
    backgroundColor: "#f2f4f6",
  },
  permission: {
    "scope.record": {
      desc: "用于向 AI 教练语音提问",
    },
  },
  requiredPrivateInfos: [],
  // 同声传译插件需正式 AppID 并在公众平台授权；测试号会报「插件未授权」导致整包失败，故默认不声明。
  // 正式环境可在此恢复：
  // plugins: { WechatSI: { version: "0.3.5", provider: "wx069ba97219f66d99" } },
  tabBar: {
    color: "#94a3b8",
    selectedColor: "#0f766e",
    backgroundColor: "#ffffff",
    borderStyle: "white",
    list: [
      {
        pagePath: "pages/workout/index",
        text: "今日训练",
        iconPath: "assets/tab-workout.png",
        selectedIconPath: "assets/tab-workout-active.png",
      },
      {
        pagePath: "pages/plans/index",
        text: "计划",
        iconPath: "assets/tab-plans.png",
        selectedIconPath: "assets/tab-plans-active.png",
      },
      {
        pagePath: "pages/exercises/index",
        text: "动作库",
        iconPath: "assets/tab-exercises.png",
        selectedIconPath: "assets/tab-exercises-active.png",
      },
      {
        pagePath: "pages/coach/index",
        text: "AI 教练",
        iconPath: "assets/tab-coach.png",
        selectedIconPath: "assets/tab-coach-active.png",
      },
      {
        pagePath: "pages/profile/index",
        text: "我的",
        iconPath: "assets/tab-profile.png",
        selectedIconPath: "assets/tab-profile-active.png",
      },
    ],
  },
});
