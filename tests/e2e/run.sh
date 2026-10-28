#!/bin/bash
# 端到端測試（不需要 Meta API 金鑰）：模擬的 Meta Model API + 伺服器 + 模擬 Pi 上傳 + worker --once，最後自動檢查結果。
#   tests/e2e/run.sh            跑完自動關掉
#   KEEP=1 tests/e2e/run.sh     跑完保留伺服器，瀏覽器開印出的 /live 網址看畫面（Ctrl-C 結束）
#   PLAIN=1 tests/e2e/run.sh    不用 AI（ANALYZER=none）：確認照片照常進相簿、可以下載、不呼叫 Meta
# 需要：Python 3.10+、exiftool；第一次會在 $TMPDIR/snappipe-e2e 建 venv。照片、資料都放在暫存資料夾，不碰 repo。
set -e
REPO=$(cd "$(dirname "$0")/../.." && pwd)
E2E="$REPO/tests/e2e"
S="${SNAPPIPE_E2E_DIR:-${TMPDIR:-/tmp}/snappipe-e2e}"
PORT=${PORT:-18080}; MOCK_PORT=${MOCK_PORT:-18099}
mkdir -p "$S"
PY=$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3)
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "需要 Python 3.10+"; exit 1; }
command -v exiftool >/dev/null || { echo "需要 exiftool"; exit 1; }
[ -x "$S/venv/bin/uvicorn" ] || { "$PY" -m venv "$S/venv" && "$S/venv/bin/pip" install -q -r "$REPO/server/requirements.txt" -r "$REPO/worker/requirements.txt"; }
V="$S/venv/bin"
rm -rf "$S/data" "$S/work" "$S/photos" "$S/games" "$S/meta.log"; mkdir -p "$S/games"

"$V/python" "$E2E/mock_meta.py" "$MOCK_PORT" "$S/meta.log" & MOCK=$!
(cd "$REPO/server" && SNAPPIPE_DATA="$S/data" SNAPPIPE_UPLOAD_TOKEN=up-token SNAPPIPE_DEVICE_TOKENS="pi-1:dev-token" \
  exec "$V/uvicorn" app.main:app --port "$PORT" --log-level warning) > "$S/server.log" 2>&1 & SRV=$!
trap 'kill $MOCK $SRV 2>/dev/null' EXIT
for _ in $(seq 1 40); do curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break; sleep 0.25; done

ALBUM=2026_10_30_test
# 一台一本相簿：拍攝計劃（比賽資料與名單）就是 default.toml
cat > "$S/games/default.toml" <<TOML
[game]
sport = "basketball"
event = "2026 城市聯賽"
home = "台北雄鷹"
away = "新竹獵豹"
home_color = "白底紅字"
away_color = "深藍底白字"
venue = "台北體育館"
city = "台北"
country = "台灣"
lang = "zh"
creator = "預設攝影"
credit = "SnapPipe"
[cameras]
"5530" = "李攝影"
TOML
cp "$REPO/worker/games/example.csv" "$S/games/default.csv"

"$V/python" "$E2E/make_and_upload.py" "$S/photos" "http://127.0.0.1:$PORT" dev-token "$ALBUM"

cat > "$S/worker.env" <<ENV
SERVER_URL=http://127.0.0.1:$PORT
WORKER_NAME=e2e
WORK_DIR=$S/work
ANALYZER=$([ -n "$PLAIN" ] && echo none || echo meta_ai)
META_API_KEY=test-key
META_API_BASE=http://127.0.0.1:$MOCK_PORT/v1
GAMES_DIR=$S/games
ENV
(cd "$REPO/worker" && SP_ENV_FILE="$S/worker.env" "$V/python" worker.py --once)
"$V/python" "$E2E/check.py" "http://127.0.0.1:$PORT" up-token "$ALBUM" "$S/meta.log" ${PLAIN:+--plain}
if [ -n "$KEEP" ]; then
  [ -d "$REPO/web/dist" ] || echo "（網頁還沒 build：cd web && npm ci && npm run build）"
  curl -s -H 'Authorization: Bearer up-token' "http://127.0.0.1:$PORT/api/live/status" | "$V/python" -c \
    "import json,sys; a=json.load(sys.stdin)['albums'][0]; print(f'即時監看：http://127.0.0.1:$PORT/live/{a[\"live_key\"]}\n返圖頁：  http://127.0.0.1:$PORT/a/{a[\"share_key\"]}')"
  wait
fi
