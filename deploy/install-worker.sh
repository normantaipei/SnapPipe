#!/usr/bin/env bash
# 在返圖站同一台機器（LXC）裡裝 / 更新 worker，設成開機常駐（以 root 執行）。
# 通常不用自己跑：PVE 上的 create-lxc.sh --install 與更新用的 bootstrap.sh 會呼叫它。
#
#   install-worker.sh                       安裝或更新；第一次沒有金鑰就不用 AI
#   echo "<金鑰>" | install-worker.sh --key-stdin   換 Meta API 金鑰（從 stdin 讀，不會出現在指令參數；會先驗證）
#   install-worker.sh --no-ai               不用 AI，只當普通相簿
#   install-worker.sh --update              bootstrap 更新時用：只有裝過 worker 才動作，金鑰設定不變
set -euo pipefail
export LC_ALL=C.UTF-8 LANG=C.UTF-8 LANGUAGE=

SRC="$(cd "$(dirname "$0")/.." && pwd)"
W="$SRC/worker"
UNIT=${SNAPPIPE_WORKER_UNIT:-/etc/systemd/system/snappipe-worker.service}
say() { echo -e "\033[1;36m▸\033[0m $*"; }
# 訊息語言：環境變數沒給就看伺服器安裝時選的（/etc/snappipe.env 的 SNAPPIPE_LANG）；export 讓 setup.sh 跟著
if [ -z "${SNAPPIPE_LANG:-}" ] && [ -f /etc/snappipe.env ]; then
  SNAPPIPE_LANG=$(sed -n 's/^SNAPPIPE_LANG=//p' /etc/snappipe.env | tail -1 | tr -d "\"'") || true
fi
export SNAPPIPE_LANG="${SNAPPIPE_LANG:-}"
t() { if [ "${SNAPPIPE_LANG:-}" = en ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }

main() {
  [ "$(id -u)" = 0 ] || { echo "$(t '請用 root 執行' 'Please run as root')" >&2; exit 1; }
  local args=() update="" key=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --key-stdin) IFS= read -r key || true; shift ;;
      --no-ai) args+=(--no-ai); shift ;;
      --no-check) args+=(--no-check); shift ;;
      --update) update=1; shift ;;
      *) echo "$(t "不認得的參數：$1" "Unknown option: $1")" >&2; exit 1 ;;
    esac
  done
  if [ -n "$update" ] && [ ! -f "$UNIT" ]; then
    return 0                                   # 這台沒裝 worker（例如 worker 裝在 Mac 上）
  fi

  say "$(t '安裝 worker（Meta AI 處理端）' 'Installing the worker (Meta AI processing)')"
  export DEBIAN_FRONTEND=noninteractive
  # setup.sh：venv、exiftool、.env；金鑰從環境變數帶進去，不放在指令參數
  META_API_KEY="$key" bash "$W/setup.sh" ${args[@]+"${args[@]}"} </dev/null

  # 連本機的返圖站：port 與 worker token 跟著伺服器設定走
  local port=8080 token=""
  if [ -f /etc/snappipe.env ]; then
    port=$(sed -n 's/^SNAPPIPE_PORT=//p' /etc/snappipe.env | tail -1); port=${port:-8080}
    token=$(sed -n 's/^SNAPPIPE_WORKER_TOKEN=//p' /etc/snappipe.env | tail -1)
  fi
  (cd "$W" && .venv/bin/python -c 'import sys; from pathlib import Path; from setup_key import write_env
write_env(Path(".env"), {"SERVER_URL": sys.argv[1], "WORKER_TOKEN": sys.argv[2]})' "http://127.0.0.1:$port" "$token")

  sed -e "s|__REPO__|$SRC|g" -e "s|__USER__|root|" "$W/snappipe-worker.service" > "$UNIT"
  systemctl daemon-reload
  systemctl enable -q snappipe-worker
  systemctl restart snappipe-worker
  sleep 2
  if systemctl is-active -q snappipe-worker; then
    local analyzer; analyzer=$(sed -n 's/^ANALYZER=//p' "$W/.env" | tail -1) || true
    say "$(t "worker 執行中（分析器：$analyzer）；記錄：journalctl -u snappipe-worker -f" "The worker is running (analyzer: $analyzer). Logs: journalctl -u snappipe-worker -f")"
  else
    echo "$(t '⚠ worker 沒有啟動成功，看記錄：journalctl -u snappipe-worker -n 50' "⚠ The worker didn't start. Check the logs: journalctl -u snappipe-worker -n 50")" >&2
    exit 1
  fi
}

main "$@"
