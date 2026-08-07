#!/bin/zsh
# 打印当前最适合真机调试的 API_BASE，并可选写入 config.ts
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CFG="$ROOT/miniprogram/src/utils/config.ts"

echo "正在探测本机局域网地址…"
CANDIDATES=()

# 优先 en0（Wi‑Fi / 连上手机热点后通常也是 en0）
for iface in en0 en1 bridge100 bridge0; do
  ip=$(ipconfig getifaddr "$iface" 2>/dev/null || true)
  if [[ -n "$ip" ]]; then
    CANDIDATES+=("$iface:$ip")
  fi
done

if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
  echo "未找到局域网 IP。请先让 Mac 连上手机热点，或接入可用 Wi‑Fi。"
  exit 1
fi

echo ""
echo "可选地址："
i=1
for c in "${CANDIDATES[@]}"; do
  iface="${c%%:*}"
  ip="${c#*:}"
  code=$(curl -s --max-time 2 -o /dev/null -w "%{http_code}" "http://$ip:8000/docs" 2>/dev/null || echo "000")
  echo "  [$i] $iface  http://$ip:8000   (后端探测: $code)"
  i=$((i+1))
done

BEST_IP="${CANDIDATES[1]#*:}"
# 若第一个探测失败，找第一个 200 的
for c in "${CANDIDATES[@]}"; do
  ip="${c#*:}"
  code=$(curl -s --max-time 2 -o /dev/null -w "%{http_code}" "http://$ip:8000/docs" 2>/dev/null || echo "000")
  if [[ "$code" == "200" ]]; then
    BEST_IP="$ip"
    break
  fi
done

NEW="http://${BEST_IP}:8000"
echo ""
echo "建议 API_BASE = $NEW"

if [[ "$1" == "--write" ]]; then
  if [[ ! -f "$CFG" ]]; then
    echo "找不到 $CFG"
    exit 1
  fi
  # 只替换 export const API_BASE = "..." 这一行
  perl -i -pe "s#^export const API_BASE = \".*\";#export const API_BASE = \"$NEW\";#" "$CFG"
  echo "已写入 $CFG"
  echo "请执行: cd miniprogram && npm run build:weapp"
  echo "然后在微信开发者工具重新编译 / 重新真机调试"
else
  echo ""
  echo "写入配置请执行："
  echo "  $0 --write"
fi
