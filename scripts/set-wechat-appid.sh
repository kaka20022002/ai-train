#!/usr/bin/env bash
# 将正式微信小程序 AppID 写入 miniprogram 工程配置。
# 用法: ./scripts/set-wechat-appid.sh wx0123456789abcdef
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APPID="${1:-}"

if [[ -z "$APPID" ]]; then
  echo "用法: $0 <AppID>"
  echo "示例: $0 wx0123456789abcdef"
  echo "申请步骤见: docs/微信AppID申请与接入.md"
  exit 1
fi

if [[ ! "$APPID" =~ ^wx[0-9a-zA-Z]{16}$ ]]; then
  echo "警告: AppID 格式通常为 wx + 16 位字符，当前为: $APPID"
  echo "若确认无误可忽略；官方格式以公众平台为准。"
fi

CFG="$ROOT/miniprogram/project.config.json"
PRIV="$ROOT/miniprogram/project.private.config.json"

if [[ ! -f "$CFG" ]]; then
  echo "未找到 $CFG"
  exit 1
fi

python3 - "$CFG" "$PRIV" "$APPID" <<'PY'
import json, sys
from pathlib import Path

cfg_path, priv_path, appid = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]

def set_appid(path: Path, create_if_missing: bool = False) -> None:
    if not path.exists():
        if not create_if_missing:
            return
        data = {}
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    data["appid"] = appid
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已更新 {path}: appid={appid}")

set_appid(cfg_path)
if priv_path.exists():
    set_appid(priv_path)
else:
    print(f"跳过（不存在）: {priv_path}")
PY

echo
echo "下一步:"
echo "  1. 微信开发者工具重新打开 miniprogram/ ，确认详情里是正式 AppID"
echo "  2. cd miniprogram && npm run build:weapp"
echo "  3. 清缓存后编译"
echo "说明: docs/微信AppID申请与接入.md"
