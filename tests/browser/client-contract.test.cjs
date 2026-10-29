/** Run after installing frontend dependencies; no browser, network, or real login. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../..");
const ts = require(path.join(root, "frontend/node_modules/typescript"));

function load(file, imports = {}, globals = {}) {
  const module = { exports: {} };
  const compiled = ts.transpileModule(
    fs.readFileSync(path.join(root, file), "utf8"),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2020,
        esModuleInterop: true,
      },
    },
  ).outputText;
  vm.runInNewContext(
    compiled,
    {
      module,
      exports: module.exports,
      require: (name) => {
        if (name in imports) return imports[name];
        throw new Error("Unexpected import: " + name);
      },
      setTimeout,
      clearTimeout,
      AbortController,
      Error,
      TypeError,
      SyntaxError,
      ...globals,
    },
    { filename: file },
  );
  return module.exports;
}

const empty = () => ({
  connection: null,
  pairing: null,
  today_reference: null,
  results: [],
});
const pairing = () => ({
  id: "issued",
  code: "000123",
  expires_at: 1900000000,
  reference: null,
});
for (const folder of ["frontend/features/vr", "miniprogram/src/features/vr"]) {
  const parser = load(folder + "/validation.ts");
  test(folder + ": empty state and leading-zero code are valid", () => {
    assert.equal(parser.parseOverview(empty()).results.length, 0);
    assert.equal(parser.parsePairing(pairing()).code, "000123");
  });
  test(folder + ": malformed nested data fails before rendering", () => {
    for (const data of [
      null,
      {},
      { ...empty(), results: [null] },
      { ...empty(), today_reference: { phases: "wrong" } },
    ]) {
      assert.throws(() => parser.parseOverview(data), /数据不完整/);
    }
    assert.throws(
      () => parser.parsePairing({ ...pairing(), code: 123 }),
      /数据不完整/,
    );
    assert.throws(
      () => parser.parsePairing({ ...pairing(), code: "12345" }),
      /数据不完整/,
    );
  });
  test(
    folder + ": null measurement stays null; corrupt scores and times fail",
    () => {
      const record = {
        id: "result",
        started_at: "2026-10-29T10:00:00Z",
        ended_at: "2026-10-29T10:01:00Z",
        received_at: 1900000000,
        outcome: "stopped",
        actions: [
          {
            action_id: "squat",
            action_name: "深蹲",
            completed_sets: null,
            completed_reps: null,
            duration_seconds: 40,
            quality_score_01: null,
            tracking_good_ratio_01: null,
          },
        ],
      };
      const data = { ...empty(), results: [record] };
      assert.equal(
        parser.parseOverview(data).results[0].actions[0].quality_score_01,
        null,
      );
      assert.throws(
        () =>
          parser.parseOverview({
            ...data,
            results: [{ ...record, ended_at: "invalid" }],
          }),
        /数据不完整/,
      );
      record.actions[0].quality_score_01 = 2;
      assert.throws(() => parser.parseOverview(data), /数据不完整/);
    },
  );
}

function miniClient(requestOverride) {
  const current = { userId: "user-a", token: "token-a" },
    calls = [];
  const taro = {
    getStorageSync: (key) => current[key],
    request:
      requestOverride ||
      ((options) => {
        const task = {
          aborted: false,
          abort() {
            this.aborted = true;
          },
        };
        calls.push({ options, task });
        return task;
      }),
  };
  const api = load("miniprogram/src/features/vr/api.ts", {
    "@tarojs/taro": { __esModule: true, default: taro },
    "../../utils/config": {
      API_BASE: "https://test.invalid",
      STORAGE_KEYS: { userId: "userId", token: "token" },
    },
    "./validation": load("miniprogram/src/features/vr/validation.ts"),
  });
  return { current, calls, api, client: api.createVrClient({ ...current }) };
}
test("mini: cancellation settles even if native abort never calls back", async () => {
  const { client, calls } = miniClient();
  const pending = client.overview();
  const rejected = assert.rejects(pending, /取消/);
  client.cancel();
  await rejected;
  assert.equal(calls[0].task.aborted, true);
  calls[0].options.success({ statusCode: 200, data: empty() });
});
test("mini: a late previous-user response is rejected", async () => {
  const { client, current, calls } = miniClient();
  const pending = client.overview();
  current.userId = "user-b";
  current.token = "token-b";
  calls[0].options.success({ statusCode: 200, data: empty() });
  await assert.rejects(pending, /用户已变化/);
});
test("mini: cancelling one client does not abort another request owner", async () => {
  const { client, api, current, calls } = miniClient();
  const other = api.createVrClient({ ...current });
  const first = client.overview(),
    second = other.overview();
  const rejected = assert.rejects(first, /取消/);
  client.cancel();
  await rejected;
  assert.equal(calls[1].task.aborted, false);
  calls[1].options.success({ statusCode: 200, data: empty() });
  assert.equal((await second).results.length, 0);
});
test("mini: expired login has a typed error without altering shared login", async () => {
  const { client, current, calls } = miniClient();
  const pending = client.overview();
  calls[0].options.success({ statusCode: 401, data: { detail: "expired" } });
  await assert.rejects(
    pending,
    (error) => error.status === 401 && /重新登录/.test(error.message),
  );
  assert.equal(current.token, "token-a");
});
test("mini: synchronous transport failures are readable and settle", async () => {
  const { client } = miniClient(() => {
    throw new TypeError("platform unavailable");
  });
  await assert.rejects(client.overview(), /暂时无法访问服务/);
});

function webClient(fetch) {
  return load(
    "frontend/features/vr/api.ts",
    {
      "@/lib/api": { API_BASE: "https://test.invalid" },
      "./validation": load("frontend/features/vr/validation.ts"),
    },
    { fetch, setTimeout: (callback) => setTimeout(callback, 15) },
  );
}
test(
  "web: timeout covers response body, not just response headers",
  { timeout: 1000 },
  async () => {
    const api = webClient(async (url, options) =>
      url.endsWith("/auth/dev-login")
        ? {
            ok: true,
            status: 200,
            json: async () => ({ access_token: "token-a", user_id: "user-a" }),
          }
        : {
            ok: true,
            status: 200,
            json: () =>
              new Promise((_, reject) => {
                options.signal.addEventListener(
                  "abort",
                  () => reject(new Error("body aborted")),
                  { once: true },
                );
              }),
          },
    );
    await assert.rejects(
      api.vrApi.overview("user-a", new AbortController().signal),
      /连接超时/,
    );
  },
);
test("web: wrong-user login cannot request another user's overview", async () => {
  const paths = [];
  const api = webClient(async (url) => {
    paths.push(url);
    return {
      ok: true,
      status: 200,
      json: async () => ({
        access_token: "wrong-user-token",
        user_id: "user-b",
      }),
    };
  });
  await assert.rejects(
    api.vrApi.overview("user-a", new AbortController().signal),
    /用户状态已变化/,
  );
  assert.equal(paths.length, 1);
});
test("web: malformed JSON reports a readable error", async () => {
  const api = webClient(async () => ({
    ok: true,
    status: 200,
    json: async () => {
      throw new SyntaxError("bad JSON");
    },
  }));
  await assert.rejects(
    api.vrApi.overview("user-a", new AbortController().signal),
    /数据无法读取/,
  );
});
