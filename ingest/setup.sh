#!/bin/bash
# 第一次使用：建 venv、裝依賴（需要 Python 3.10+ 與 exiftool：讀 EXIF、從 RAW 抽 JPG 預覽）
#   Mac：Homebrew（brew install python exiftool）
#   Debian / Ubuntu / 樹莓派 OS：sudo apt install python3-venv libimage-exiftool-perl
#   ingest/setup.sh --lang en|zh   訊息語言（en = English；也可以設環境變數 SNAPPIPE_LANG）
set -e
t() { if [ "${SNAPPIPE_LANG:-}" = en ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }
cd "$(dirname "$0")"

# --lang 要在印出任何訊息之前處理；其他參數照舊忽略
while [ $# -gt 0 ]; do
  case "$1" in
    --lang|--lang=*)
      if [ "$1" = --lang ]; then v="${2:-}"; shift; [ $# -gt 0 ] && shift; else v="${1#*=}"; shift; fi
      case "$v" in en|zh) export SNAPPIPE_LANG="$v" ;; *) echo "--lang 只能是 en 或 zh / --lang must be en or zh"; exit 1 ;; esac ;;
    *) shift ;;
  esac
done

if ! command -v exiftool >/dev/null; then
  if command -v brew >/dev/null; then brew install exiftool
  elif command -v apt-get >/dev/null; then $([ "$(id -u)" = 0 ] || echo sudo) apt-get install -y libimage-exiftool-perl
  else echo "$(t '⚠ 找不到 exiftool：無法讀 EXIF。請自行安裝 https://exiftool.org' "⚠ exiftool not found: can't read EXIF. Please install it from https://exiftool.org")"; fi
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
[ -n "$PY" ] || { echo "$(t '需要 Python 3.10 以上' 'Python 3.10 or newer is required')"; exit 1; }

[ -x .venv/bin/python ] && ! new_enough .venv/bin/python && rm -rf .venv
[ -x .venv/bin/python ] || "$PY" -m venv .venv || { echo "$(t '建立 venv 失敗（Debian / Ubuntu 請先 sudo apt install python3-venv）' 'Could not create the venv (on Debian / Ubuntu, run sudo apt install python3-venv first)')"; exit 1; }
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || { cp .env.example .env; chmod 600 .env; echo "$(t '已建立 ingest/.env' 'Created ingest/.env')"; }
PYV=$(.venv/bin/python --version)
echo "$(t "✅ 安裝完成（$PYV）" "✅ Setup complete ($PYV)")"
