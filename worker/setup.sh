#!/bin/bash
# 第一次使用：建 venv、裝依賴（需要 Python 3.10+ 與 exiftool）
#   Mac：Homebrew（brew install python exiftool）
#   Debian / Ubuntu / 樹莓派 OS：sudo apt install python3-venv libimage-exiftool-perl
#
# Meta API 金鑰：
#   worker/setup.sh                      沒設過就問你（輸入時不顯示），驗證通過才存；留空 = 不用 AI，只當普通相簿
#   worker/setup.sh --api-key <金鑰>      直接帶（自動化用；也可以設環境變數 META_API_KEY）
#                                        兩種都會留在 shell 歷史，手動安裝建議用上面那種、等它問再貼
#   worker/setup.sh --ask-key            重新輸入 / 換金鑰
#   worker/setup.sh --no-ai              不用 AI
set -e
cd "$(dirname "$0")"

KEY_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --api-key) [ -n "${2:-}" ] || { echo "--api-key 後面要接金鑰"; exit 1; }; export META_API_KEY="$2"; shift 2 ;;
    --api-key=*) export META_API_KEY="${1#*=}"; shift ;;
    --ask-key) KEY_ARGS+=(--ask); shift ;;
    --no-ai) KEY_ARGS+=(--no-ai); shift ;;
    -h|--help) sed -n '2,11p' "$(basename "$0")"; exit 0 ;;
    *) echo "不認得的參數：$1（--api-key / --ask-key / --no-ai）"; exit 1 ;;
  esac
done

if ! command -v exiftool >/dev/null; then
  if command -v brew >/dev/null; then brew install exiftool
  elif command -v apt-get >/dev/null; then sudo apt-get install -y libimage-exiftool-perl
  else echo "⚠ 找不到 exiftool：照片不會寫入 IPTC。請自行安裝 https://exiftool.org"; fi
fi

new_enough() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; }
pick_python() {
  local cands=(python3 python3.13 python3.12 python3.11 python3.10)
  command -v brew >/dev/null && cands=("$(brew --prefix)/bin/python3" "${cands[@]}")
  for p in "${cands[@]}"; do
    command -v "$p" >/dev/null && new_enough "$p" && { command -v "$p"; return 0; }
  done
  return 0
}
PY=$(pick_python)
[ -n "$PY" ] || { echo "需要 Python 3.10 以上"; exit 1; }

[ -x .venv/bin/python ] && ! new_enough .venv/bin/python && rm -rf .venv
[ -x .venv/bin/python ] || "$PY" -m venv .venv || { echo "建立 venv 失敗（Debian / Ubuntu 請先 sudo apt install python3-venv）"; exit 1; }
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || { cp .env.example .env; chmod 600 .env; echo "已建立 worker/.env（記得填 SERVER_URL）"; }
.venv/bin/python setup_key.py ${KEY_ARGS[@]+"${KEY_ARGS[@]}"}
[ -d games ] && [ ! -f games/default.toml ] && cp games/example.toml games/default.toml && \
  echo "已建立 worker/games/default.toml（比賽資料範本，請改成你的署名與賽事）"
echo "✅ 安裝完成（$(.venv/bin/python --version)）"
