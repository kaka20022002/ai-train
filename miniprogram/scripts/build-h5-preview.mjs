/** Opt-in preview build; leaves the existing WeChat dist/ output untouched. */
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL("../", import.meta.url));
const cli = path.join(root, "node_modules/@tarojs/cli/bin/taro");
const result = spawnSync(process.execPath, [cli, "build", "--type", "h5"], {
  cwd: root,
  stdio: "inherit",
  env: { ...process.env, AI_TRAIN_H5_PREVIEW: "1" },
});
if (result.error) console.error(result.error.message);
process.exitCode = result.status ?? 1;
