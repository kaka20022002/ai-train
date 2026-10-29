/** Reproducible checks. Owns isolated API/preview servers and never writes live data. */
import { chromium } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import net from "node:net";
import http from "node:http";
import crypto from "node:crypto";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const artifacts = path.join(here, "artifacts");
fs.mkdirSync(artifacts, { recursive: true });
const children = [],
  logs = [],
  checks = [],
  errors = [];
let browser, staticServer, apiUrl, webUrl, miniUrl;
let miniStyleBefore;
const vrRequests = [];
const modes = new Map();

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}
function start(command, args, cwd, name, env = {}) {
  const log = fs.createWriteStream(path.join(artifacts, name + ".log"));
  logs.push(log);
  const child = spawn(command, args, {
    cwd,
    env: { ...process.env, ...env },
    windowsHide: true,
  });
  child.stdout.pipe(log);
  child.stderr.pipe(log);
  children.push(child);
  child.on("error", (error) => log.write(error.message + "\n"));
  return child;
}
async function waitReady(url, child) {
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error("Test server exited: " + url);
    try {
      const r = await fetch(url);
      if (r.ok) return;
    } catch {
      /* Still starting. */
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error("Test server did not become ready: " + url);
}
async function api(route, method = "GET", data, token) {
  const response = await fetch(apiUrl + route, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: "Bearer " + token } : {}),
    },
    ...(data ? { body: JSON.stringify(data) } : {}),
  });
  const body = response.status === 204 ? null : await response.json();
  assert(response.ok, route + " returned " + response.status);
  return body;
}
async function step(name, action) {
  await action();
  checks.push(name);
  console.log("PASS " + name);
}
async function pageFor(kind, viewport) {
  const page = await browser.newPage({ viewport });
  modes.set(page, {
    mode: "",
    holdProfile: null,
    holdOverview: null,
    expire: false,
  });
  page.on("pageerror", (error) => errors.push(kind + ": " + error.message));
  await page.route(
    /http:\/\/(?:localhost|127\.0\.0\.1):8000\//,
    async (route) => {
      const request = route.request(),
        state = modes.get(page),
        url = new URL(request.url());
      if (url.pathname.startsWith("/vr/"))
        vrRequests.push({ kind, path: url.pathname });
      try {
        if (
          url.pathname === "/users/usr_001" &&
          request.method() === "GET" &&
          state.holdProfile
        )
          await state.holdProfile;
        if (url.pathname === "/vr/overview" && state.holdOverview)
          await state.holdOverview;
        const response = await route.fetch({
          url: apiUrl + url.pathname + url.search,
          headers: { ...request.headers(), "x-vr-test-mode": state.mode },
        });
        if (
          url.pathname === "/vr/pairings" &&
          request.method() === "POST" &&
          state.mode === "lost-code" &&
          response.ok()
        ) {
          await route.fulfill({
            response,
            status: 503,
            json: { detail: "短码结果未收到，请重新生成。" },
          });
          return;
        }
        if (
          url.pathname === "/vr/pairings" &&
          request.method() === "POST" &&
          state.expire &&
          response.ok()
        ) {
          const body = await response.json(),
            expired = await api("/__test/expire", "POST");
          await route.fulfill({
            response,
            json: { ...body, expires_at: expired.expires_at },
          });
        } else await route.fulfill({ response });
      } catch {
        /* Request cancellation during page navigation is expected. */
      }
    },
  );
  return page;
}
const miniButton = (page, label) =>
  page.locator("taro-button-core").filter({
    hasText: new RegExp(
      "^" + label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "$",
    ),
  });
async function miniLogin(page, uid) {
  await page.goto(miniUrl);
  await page
    .locator(".weui-tabbar__item")
    .getByText("我的", { exact: true })
    .click();
  await page.locator("input:visible").fill(uid);
  await page.getByText("使用该 ID 登录", { exact: true }).click();
  await page.getByText("已登录 · " + uid, { exact: true }).waitFor();
  await page.goto(miniUrl);
  await page.getByText("已同步 · " + uid, { exact: true }).waitFor();
  if (!miniStyleBefore) miniStyleBefore = await originalButtonStyle(page);
  await page.locator(".vr-entry").click();
  await page.locator(".vr-identity").filter({ hasText: uid }).waitFor();
}

async function originalButtonStyle(page) {
  return page
    .locator(".btn-primary")
    .first()
    .evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        color: style.color,
        background: style.backgroundImage,
        radius: style.borderRadius,
        fontSize: style.fontSize,
      };
    });
}

try {
  assert(
    fs.existsSync(path.join(root, "frontend/.next/BUILD_ID")),
    "Build the frontend first.",
  );
  const h5 = path.join(root, "miniprogram/dist-h5");
  assert(
    fs.existsSync(path.join(h5, "index.html")),
    "Run npm run build:h5:preview first.",
  );
  const apiPort = await freePort(),
    webPort = await freePort();
  apiUrl = "http://127.0.0.1:" + apiPort;
  webUrl = "http://127.0.0.1:" + webPort;
  const venvPython = path.join(
    root,
    process.platform === "win32"
      ? ".venv/Scripts/python.exe"
      : ".venv/bin/python",
  );
  const python =
    process.env.VR_TEST_PYTHON ||
    (fs.existsSync(venvPython)
      ? venvPython
      : process.platform === "win32"
        ? "python"
        : "python3");
  const apiProcess = start(
    python,
    [path.join(here, "server.py")],
    root,
    "api",
    { VR_TEST_API_PORT: String(apiPort) },
  );
  const webProcess = start(
    process.execPath,
    [
      path.join(root, "frontend/node_modules/next/dist/bin/next"),
      "start",
      "-p",
      String(webPort),
      "-H",
      "127.0.0.1",
    ],
    path.join(root, "frontend"),
    "web",
  );
  staticServer = http.createServer((request, response) => {
    const pathname = decodeURIComponent(
      new URL(request.url, "http://local").pathname,
    );
    const target = path.resolve(
      h5,
      "." + (pathname === "/" ? "/index.html" : pathname),
    );
    if (
      !target.startsWith(h5 + path.sep) ||
      !fs.existsSync(target) ||
      !fs.statSync(target).isFile()
    ) {
      response.writeHead(404).end();
      return;
    }
    const types = {
      ".html": "text/html",
      ".js": "application/javascript",
      ".css": "text/css",
      ".png": "image/png",
      ".svg": "image/svg+xml",
    };
    response.setHeader(
      "Content-Type",
      types[path.extname(target)] || "application/octet-stream",
    );
    fs.createReadStream(target).pipe(response);
  });
  await new Promise((resolve) => staticServer.listen(0, "127.0.0.1", resolve));
  miniUrl = "http://127.0.0.1:" + staticServer.address().port + "/";
  await Promise.all([
    waitReady(apiUrl + "/__test/ready", apiProcess),
    waitReady(webUrl + "/vr", webProcess),
  ]);
  browser = await chromium.launch({
    headless: true,
    ...(process.env.VR_BROWSER_CHANNEL
      ? { channel: process.env.VR_BROWSER_CHANNEL }
      : {}),
  });
  const web = await pageFor("web", { width: 1440, height: 1000 });
  const mini = await pageFor("mini", { width: 390, height: 844 });

  await step(
    "new user pairs without a profile form or waiting for profile loading",
    async () => {
      assert.equal((await fetch(apiUrl + "/users/usr_001")).status, 404);
      let release;
      modes.get(web).holdProfile = new Promise(
        (resolve) => (release = resolve),
      );
      try {
        await web.goto(webUrl + "/vr", { waitUntil: "domcontentloaded" });
        await web
          .getByRole("button", { name: "生成连接短码", exact: true })
          .click();
        await web.locator('[aria-label="连接短码"]').waitFor();
        assert.equal(
          await web.getByText("先建立你的训练档案", { exact: true }).count(),
          0,
        );
      } finally {
        release();
        modes.get(web).holdProfile = null;
      }
      await web.getByRole("button", { name: "取消短码", exact: true }).click();
      await web.getByText("短码已取消。", { exact: true }).waitFor();
    },
  );

  await api("/__test/reference/usr_001", "POST");
  const before = await api("/__test/original/usr_001");
  let device, resultId;
  await step(
    "shared association, regeneration and concurrent one-time redemption",
    async () => {
      await web.getByRole("button", { name: "刷新关联与训练记录" }).click();
      await web.getByRole("checkbox").check();
      await web
        .getByRole("button", { name: "生成连接短码", exact: true })
        .dblclick();
      const digits = web.locator('[aria-label="连接短码"]');
      await digits.waitFor();
      const old = await digits.innerText();
      assert.match(old, /^[0-9]{6}$/);
      await miniLogin(mini, "usr_001");
      assert.equal(await mini.locator(".vr-pairing-digits").count(), 0);
      await miniButton(mini, "重新生成短码").click();
      await mini.locator(".vr-pairing-digits").waitFor();
      const code = await mini.locator(".vr-pairing-digits").innerText();
      await web.getByRole("button", { name: "刷新关联与训练记录" }).click();
      await digits.waitFor({ state: "hidden" });
      const secret = crypto.randomBytes(32).toString("base64url");
      const redeem = (code) =>
        fetch(apiUrl + "/vr/device/pairings/redeem", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            code,
            device_name: "隔离验收设备（协议模拟）",
            device_secret: secret,
          }),
        });
      assert.equal((await redeem(old)).status, 400);
      const response = await redeem(code);
      assert.equal(response.status, 200);
      device = await response.json();
      assert.equal(device.user_id, "usr_001");
      assert.equal(device.today_reference.title, "全身力量参考");
      assert.equal(
        (await (await redeem(code)).json()).device_token,
        device.device_token,
      );
      await web.getByRole("button", { name: "刷新关联与训练记录" }).click();
      await web.getByRole("heading", { name: "头显已关联" }).waitFor();
      await mini.locator(".vr-refresh").click();
      await mini.getByText("头显已关联", { exact: true }).waitFor();
      const raceLogin = await api("/auth/dev-login", "POST", {
        user_id: "usr_race",
      });
      const raceCode = await api(
        "/vr/pairings",
        "POST",
        {},
        raceLogin.access_token,
      );
      const winners = await Promise.all(
        [1, 2].map(() =>
          fetch(apiUrl + "/vr/device/pairings/redeem", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              code: raceCode.code,
              device_name: "并发验收",
              device_secret: crypto.randomBytes(32).toString("base64url"),
            }),
          }),
        ),
      );
      assert.equal(
        winners.filter((response) => response.status === 200).length,
        1,
      );
      assert(
        winners.every((response) => [200, 400, 409].includes(response.status)),
      );
      await api("/vr/connection", "DELETE", null, raceLogin.access_token);
    },
  );

  await step(
    "actual result values and null quality render identically; retries deduplicate",
    async () => {
      const ended = new Date(),
        started = new Date(ended.getTime() - 60000);
      const body = {
        client_session_id: "browser-fixture",
        context_user_id: "usr_001",
        started_at: started.toISOString(),
        ended_at: ended.toISOString(),
        outcome: "stopped",
        actions: [
          {
            action_id: "fixture",
            action_name: "验收模拟动作",
            completed_sets: 2,
            completed_reps: 6,
            duration_seconds: 40,
            quality_score_01: null,
            tracking_good_ratio_01: 0.95,
          },
        ],
      };
      const first = await api(
        "/vr/device/results",
        "POST",
        body,
        device.device_token,
      );
      resultId = first.id;
      assert.equal(
        (await api("/vr/device/results", "POST", body, device.device_token)).id,
        resultId,
      );
      await web.getByRole("button", { name: "刷新关联与训练记录" }).click();
      await web.getByRole("tab", { name: /跟练记录/ }).click();
      await web.locator("summary").filter({ hasText: "提前结束" }).click();
      await web.getByText("验收模拟动作", { exact: true }).waitFor();
      await mini.locator(".vr-refresh").click();
      await mini.locator(".vr-tab").filter({ hasText: "跟练记录" }).click();
      await mini.getByText("提前结束 +", { exact: true }).click();
      await mini
        .getByText("未提供有效质量评分 · 追踪有效占比 95%", { exact: true })
        .waitFor();
    },
  );

  await step(
    "503, rate limiting, malformed JSON/data and native login expiry are recoverable",
    async () => {
      await web.getByRole("tab", { name: "连接与准备", exact: true }).click();
      await miniButton(mini, "连接与准备").click();
      for (const mode of ["503", "429", "bad-json", "bad-data"]) {
        modes.get(web).mode = mode;
        await web.getByRole("button", { name: "刷新关联与训练记录" }).click();
        await web.locator('main [role="alert"]').waitFor();
        modes.get(web).mode = "";
        await web.getByRole("button", { name: "刷新关联与训练记录" }).click();
        await web.locator('main [role="alert"]').waitFor({ state: "hidden" });
        modes.get(mini).mode = mode;
        await mini.locator(".vr-refresh").click();
        await mini.locator(".vr-error").waitFor();
        modes.get(mini).mode = "";
        await mini.locator(".vr-refresh").click();
        await mini.locator(".vr-error").waitFor({ state: "hidden" });
      }
      modes.get(mini).mode = "401";
      await mini.locator(".vr-refresh").click();
      await mini.getByText("去登录 ›", { exact: true }).waitFor();
      modes.get(mini).mode = "";
      await mini.locator(".vr-refresh").click();
      await mini.locator(".vr-error").waitFor({ state: "hidden" });
      await mini.getByText("头显已关联", { exact: true }).waitFor();
    },
  );

  await step(
    "unlink preserves results and cannot alter original profile/program/session tables",
    async () => {
      await miniButton(mini, "解除关联").click();
      await miniButton(mini, "保留关联").click();
      await miniButton(mini, "解除关联").click();
      await miniButton(mini, "确认解除").click();
      await miniButton(mini, "生成连接短码").waitFor();
      assert.equal(
        (
          await fetch(apiUrl + "/vr/device/context", {
            headers: { Authorization: "Bearer " + device.device_token },
          })
        ).status,
        410,
      );
      const login = await api("/auth/dev-login", "POST", {
        user_id: "usr_001",
      });
      assert.equal(
        (await api("/vr/overview", "GET", null, login.access_token)).results[0]
          .id,
        resultId,
      );
      assert.deepEqual(await api("/__test/original/usr_001"), before);
    },
  );

  await step(
    "uncertain issuance failure hides the invalidated previous code",
    async () => {
      await web.getByRole("tab", { name: "连接与准备", exact: true }).click();
      await web.getByRole("button", { name: "刷新关联与训练记录" }).click();
      await web
        .getByRole("button", { name: "生成连接短码", exact: true })
        .click();
      await web.locator('[aria-label="连接短码"]').waitFor();
      modes.get(web).mode = "lost-code";
      await web
        .getByRole("button", { name: "重新生成短码", exact: true })
        .click();
      await web.locator('main [role="alert"]').waitFor();
      assert.equal(await web.locator('[aria-label="连接短码"]').count(), 0);
      modes.get(web).mode = "";
      await web
        .getByRole("button", { name: "重新生成短码", exact: true })
        .click();
      await web.locator('[aria-label="连接短码"]').waitFor();
      await mini.locator(".vr-refresh").click();
      await miniButton(mini, "重新生成短码").click();
      await mini.locator(".vr-pairing-digits").waitFor();
      modes.get(mini).mode = "lost-code";
      await miniButton(mini, "重新生成短码").click();
      await mini.locator(".vr-error").waitFor();
      assert.equal(await mini.locator(".vr-pairing-digits").count(), 0);
      modes.get(mini).mode = "";
      await miniButton(mini, "重新生成短码").click();
      await mini.locator(".vr-pairing-digits").waitFor();
      await miniButton(mini, "取消短码").click();
      await miniButton(mini, "生成连接短码").waitFor();
    },
  );

  await step("expired code is hidden and cannot be redeemed", async () => {
    modes.get(mini).expire = true;
    await miniButton(mini, "生成连接短码").click();
    await mini.locator(".vr-pairing-digits").waitFor();
    const code = await mini.locator(".vr-pairing-digits").innerText();
    await mini.getByText("短码已过期，请重新申请。", { exact: true }).waitFor();
    modes.get(mini).expire = false;
    assert.equal(
      (
        await fetch(apiUrl + "/vr/device/pairings/redeem", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            code,
            device_name: "过期验收",
            device_secret: crypto.randomBytes(32).toString("base64url"),
          }),
        })
      ).status,
      400,
    );
    await miniButton(mini, "取消短码").click();
    await miniButton(mini, "生成连接短码").waitFor();
  });

  await step(
    "switching mini users does not reveal old pairing, plan or records",
    async () => {
      await miniButton(mini, "‹ 今日训练").click();
      await miniLogin(mini, "usr_other");
      await mini
        .getByText("当前没有今日计划，不影响关联或跟练。", { exact: true })
        .waitFor();
      await miniButton(mini, "跟练记录").click();
      await mini.getByText("还没有回传的跟练记录", { exact: true }).waitFor();
      await miniButton(mini, "连接与准备").click();
    },
  );

  await step(
    "delayed previous-account response is discarded after web account switch",
    async () => {
      await web.getByRole("button", { name: "刷新关联与训练记录" }).click();
      await web.getByRole("heading", { name: "生成头显连接短码" }).waitFor();
      let release;
      modes.get(web).holdOverview = new Promise(
        (resolve) => (release = resolve),
      );
      await web.getByRole("button", { name: "刷新关联与训练记录" }).click();
      await web.locator('nav a[href="/profile"]').click();
      await web.getByRole("button", { name: "编辑", exact: true }).click();
      await web
        .getByRole("textbox", { name: "用户 ID", exact: true })
        .fill("usr_other");
      release();
      modes.get(web).holdOverview = null;
      await web.locator('nav a[href="/vr"]').click();
      await web.getByText("usr_other", { exact: true }).waitFor();
      await web
        .getByText("当前没有今日计划，不影响关联或 VR 跟练。", { exact: true })
        .waitFor();
      await web.getByRole("tab", { name: "跟练记录", exact: true }).click();
      await web
        .getByRole("heading", { name: "还没有回传的跟练记录" })
        .waitFor();
    },
  );

  await step(
    "original web routes and all five mini tabs still render",
    async () => {
      for (const [route, heading] of [
        ["/workout", "今日训练"],
        ["/profile", "我的档案"],
        ["/generate", "生成训练计划"],
        ["/risk", "伤病风险分析"],
        ["/exercises", "动作知识库"],
      ]) {
        await web.goto(webUrl + route);
        await web
          .getByRole("heading", { name: heading, exact: true })
          .waitFor();
      }
      await web.goto(webUrl + "/programs");
      await web.getByText("训练计划", { exact: true }).waitFor();
      assert.deepEqual(
        await web
          .locator("nav a")
          .evaluateAll((links) =>
            links.map((link) => link.getAttribute("href")),
          ),
        [
          "/workout",
          "/",
          "/generate",
          "/recommendations",
          "/programs",
          "/risk",
          "/exercises",
          "/chat",
          "/video-analysis",
          "/profile",
          "/vr",
        ],
      );
      await miniButton(mini, "‹ 今日训练").click();
      for (const [tab, text] of [
        ["今日训练", "开始演示训练"],
        ["计划", "我的计划"],
        ["动作库", "点击动作可播放示范并查看要领"],
        ["AI 教练", "上传视频分析动作"],
        ["我的", "账号与登录"],
      ]) {
        await mini
          .locator(".weui-tabbar__item")
          .getByText(tab, { exact: true })
          .click();
        await mini.getByText(text, { exact: true }).waitFor();
        if (tab === "今日训练")
          assert.deepEqual(await originalButtonStyle(mini), miniStyleBefore);
      }
      assert.deepEqual(
        await mini.locator(".weui-tabbar__label").allTextContents(),
        ["今日训练", "计划", "动作库", "AI 教练", "我的"],
      );
    },
  );

  await step(
    "320/390/768 layouts, no global VR styles on original pages, no page errors",
    async () => {
      await mini.goto(miniUrl);
      await mini.locator(".vr-entry").click();
      await miniButton(mini, "生成连接短码").waitFor();
      for (const width of [320, 390, 768]) {
        await mini.setViewportSize({ width, height: 844 });
        assert(
          await mini.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        );
      }
      await web.goto(webUrl + "/vr");
      await web
        .getByRole("button", { name: "生成连接短码", exact: true })
        .waitFor();
      await web.waitForFunction(() =>
        Array.from(document.querySelectorAll("button")).some(
          (button) =>
            button.textContent.trim() === "生成连接短码" && !button.disabled,
        ),
      );
      const requestCount = vrRequests.length;
      await new Promise((resolve) => setTimeout(resolve, 1200));
      assert.equal(
        vrRequests.length,
        requestCount,
        "There must be no background polling.",
      );
      await mini.screenshot({
        path: path.join(artifacts, "mini.png"),
        fullPage: true,
      });
      await web.screenshot({
        path: path.join(artifacts, "web.png"),
        fullPage: true,
      });
      assert.deepEqual(errors, []);
    },
  );
} finally {
  if (browser) await browser.close();
  if (staticServer) await new Promise((resolve) => staticServer.close(resolve));
  for (const child of children) {
    if (child.exitCode !== null) continue;
    if (process.platform === "win32")
      await new Promise((resolve) => {
        const kill = spawn(
          "taskkill",
          ["/PID", String(child.pid), "/T", "/F"],
          { windowsHide: true, stdio: "ignore" },
        );
        kill.on("exit", resolve);
        kill.on("error", resolve);
      });
    else child.kill("SIGTERM");
  }
  logs.forEach((log) => log.end());
  fs.writeFileSync(
    path.join(artifacts, "report.json"),
    JSON.stringify(
      {
        passed: checks.length === 11,
        source:
          "real built clients, isolated SQLite, simulated device requests",
        native_wechat_test: false,
        headset_test: false,
        checks,
        errors,
      },
      null,
      2,
    ),
  );
}
