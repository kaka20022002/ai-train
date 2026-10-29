# VR 跟练验证与交付

## 工程边界

网页新增代码在 `frontend/features/vr/` 和 `frontend/app/vr/`；原页面只在 Sidebar 增加导航。
小程序新增代码在 `miniprogram/src/features/vr/` 和 `src/pages/vr/`；原今日训练只引入一个无网络请求的入口组件，原五个 Tab 保留。
样式使用 CSS Module 或 `vr-` 命名空间，不覆盖原页面的按钮、表单和布局。

业务 API 全部在 `vr_bridge/`，主程序仅导入、挂载 router。新表使用独立名称，首次启动随现有
`metadata.create_all` 创建；没有改写原有用户、计划和训练表的结构。开发登录首次初始化必要用户记录
是既有账号机制；VR 结果不会生成普通打卡、推进周次、改动档案或原课表。
旧计划预览异常只在 VR 读取边界做兼容，原始计划数据不被修复或覆盖。

生产客户端没有引入新运行时依赖。Playwright 和 Prettier 仅位于独立的 `tests/browser` 开发工具目录。
Unity 源代码在独立 DGTCoach 工程中，不属于本仓库提交。

## 已补强的异常处理

- 网页超时覆盖响应体读取；无效 JSON、缺字段和非法评分在 API 边界被拒绝，不进入页面渲染。
- 小程序请求取消会主动结束 Promise，不依赖平台一定回调；取消只作用于本模块的请求。
- 离开页面取消请求，重新进入更新代次；旧账号的延迟响应不能覆盖新账号。
- 小程序登录过期提供重新登录入口，VR 模块不清除或改写共享登录状态。
- 同一用户从后台恢复时可保留内存短码；换用户、刷新发现配对 ID 已变化或已匹配时清除。
- 重新出码响应丢失时隐藏旧码；取消短码后重新确认服务端状态，处理头显恰好已完成兑换的情况。
- 缺少或异常的可选参考不会阻塞不附带计划的配对；空评分保持 null，不补零。
- 新增 `build:h5:preview` 只写 `dist-h5/`，避免覆盖微信产物；原构建命令及默认输出保持不变。

## 复现步骤

需要项目原有 Python 依赖、Node.js 20 或更新版本；先按根目录说明准备虚拟环境。
下面命令从仓库根目录开始执行，Windows 可使用 `npm.cmd`，Python 可用 `.venv/Scripts/python.exe`。

```bash
python -m pytest tests/ -q -o addopts=

cd frontend
npm ci
npx tsc --noEmit
npm run build

cd ../miniprogram
npm ci
npx tsc --noEmit --skipLibCheck
npm run build:weapp
npm run build:h5:preview

cd ../tests/browser
npm ci
npm run test:clients
npx playwright install chromium
npm test
```

可用 `VR_TEST_PYTHON` 指定 Python；默认优先使用仓库 `.venv`，否则使用 PATH 中的 Python。
本机已有 Edge 时可用 `VR_BROWSER_CHANNEL=msedge` 跳过 Chromium 下载；PowerShell 写法为
`$env:VR_BROWSER_CHANNEL='msedge'`。

浏览器脚本自动启动随机端口的测试 API、Next 服务和 H5 静态服务，不依赖桌面工具、绝对路径
或现有 localhost 服务。测试 API 始终创建独立临时 SQLite，关闭真实模型调用；测试控制接口
只存在于 `tests/browser/server.py` 的独立进程，不挂载到生产程序。脚本退出后回收自己启动的服务。

报告、截图、日志和临时库位于 `tests/browser/artifacts/`，依赖和产物均在 Git 忽略范围。
截图和训练记录是模拟验收数据，不是实际用户训练。

## 验证内容与已知边界

后端全量回归包含原有档案、风险分析、计划生成、推荐、会话与训练记录测试，以及新增 VR 协议测试。
客户端测试覆盖取消、账号隔离、登录失效、响应体超时及异常数据。
浏览器使用真实构建产物验证新用户无档案出码、两端交叉配对、并发兑换唯一性、结果去重与空评分、
503/429/坏 JSON/坏数据后的恢复、弱网出码、过期码、迟到响应、原页面导航、原样式及窄屏布局。
普通档案、计划和已有普通训练记录在 VR 操作前后进行数据库快照对比。

本次验证结果：后端 254 项通过、1 项跳过；客户端边界 14 项通过；浏览器 11 项通过；
网页生产构建、H5 和微信构建通过。Taro 仍有现有 Sass 弃用和产物体积提示，不影响本次编译。

这些结果支持“已覆盖路径未发现原有功能回归”，不代表所有设备与线上环境都已验收。
微信原生 UI、真实微信登录、PICO、HTTPS 域名和真实动作评分仍需真机联调。
当前开发登录及单进程限流适用于可信原型环境；公开部署前需替换开发登录并统一可信 HTTPS 后端。
代码可以准备提交 GitHub，不能据此认定已经完成公开部署。
