#!/bin/bash
# 第一次使用：建 venv、裝依賴（需要 Python 3.10+ 與 exiftool：讀 EXIF、從 RAW 抽 JPG 預覽）
#   Mac：Homebrew（brew install python exiftool）
#   Debian / Ubuntu / 樹莓派 OS：sudo apt install python3-venv libimage-exiftool-perl
set -e
cd "$(dirname "$0")"

if ! command -v exiftool >/dev/null; then
  if command -v brew >/dev/null; then brew install exiftool
  elif command -v apt-get >/dev/null; then sudo apt-get install -y libimage-exiftool-perl
  else echo "⚠ 找不到 exiftool：無法讀 EXIF。請自行安裝 https://exiftool.org"; fi
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
[ -f .env ] || { cp .env.example .env; chmod 600 .env; echo "已建立 ingest/.env"; }
echo "✅ 安裝完成（$(.venv/bin/python --version)）"
