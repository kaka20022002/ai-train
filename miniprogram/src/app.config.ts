export default defineAppConfig({
  pages: [
    "pages/workout/index",
    "pages/plans/index",
    "pages/exercises/index",
    "pages/coach/index",
    "pages/profile/index",
    "pages/profile-edit/index",
    "pages/session/index",
    "pages/dashboard/index",
    "pages/generate/index",
    "pages/recommendations/index",
    "pages/risk/index",
    "pages/video-analysis/index",
    "pages/vr/index",
  ],
  window: {
    backgroundTextStyle: "light",
    navigationBarBackgroundColor: "#0f1419",
    navigationBarTitleText: "AI 健身教练",
    navigationBarTextStyle: "white",
    backgroundColor: "#f2f4f6",
  },
  networkTimeout: {
    request: 20000,
    uploadFile: 600000,
    downloadFile: 60000,
  },
  // 录音权限在使用时通过 authorize 申请；permission.scope.record 在新基础库/游客模式下会报「无效」
  requiredPrivateInfos: [],
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
