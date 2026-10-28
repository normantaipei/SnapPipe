#!/usr/bin/env bash
# SnapPipe 一鍵安裝（Debian 12 / Ubuntu LXC，以 root 執行）
#
# 兩種用法，再次執行即為更新，資料、token 與設定都會保留：
#   1. 打包版：在 Mac 上執行 deploy/build-installer.sh，把後端 + 前端 build 打包成單一檔案
#      dist/snappipe-install.sh，再複製到伺服器執行（安裝法 A）
#   2. 原始碼版：bootstrap.sh 在伺服器上 clone repo、build 前端後，以 SNAPPIPE_SRC=<repo> 直接執行（安裝法 B）
#
# 參數（不給就互動詢問；沒有終端機時用預設值）：
#   --site-name NAME   網站名稱：整個返圖站的名字（首頁標題、分頁標題、分享預覽）  預設「返圖」
#                      每本相簿的名稱不在這裡設，是插卡上傳時用 ingest 的 --album / --title（或 Pi 依拍攝日期自動建）
#   --port N           返圖站 port               預設 8080
#   --upload-nets CIDR 允許上傳的網段（逗號分隔）  預設 LXC 所在區網
#   --public-url URL   對外網址（反向代理/網域）   預設 http://<LXC IP>:<port>
#   --no-prompt        不詢問，沒給的用預設值（Proxmox 一鍵安裝時用）
set -euo pipefail
# 容器通常沒裝 en_US.UTF-8：一律用 Debian 內建的 C.UTF-8，中文輸入與輸出才正常，apt 也不會一直警告
export LC_ALL=C.UTF-8 LANG=C.UTF-8 LANGUAGE=

INGEST_CMD="__INGEST_CMD__"   # build 時填入打包那台電腦上 ingest.sh 的路徑
case "$INGEST_CMD" in __*__) INGEST_CMD="ingest/ingest.sh" ;; esac   # 原始碼版：不知道插卡電腦上 clone 在哪
NO_PROMPT=""
APP=/opt/snappipe
DATA=/var/lib/snappipe
ENV_FILE=/etc/snappipe.env

die() { echo "❌ $*" >&2; exit 1; }
say() { echo -e "\033[1;36m▸\033[0m $*"; }

has_tty() { [ -t 1 ] && ( : </dev/tty ) 2>/dev/null; }

# ask 變數名 提示 預設值：變數已有值就不問
ask() {
  local __v="${!1:-}"
  if [ -z "$__v" ] && [ -z "$NO_PROMPT" ] && has_tty; then
    read -r -p "$2 [${3:-留空}]: " __v </dev/tty || true
  fi
  printf -v "$1" '%s' "${__v:-$3}"
}

env_get() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | tail -1 | sed "s/^'\(.*\)'\$/\1/" || true; }

main() {
  local SITE_NAME="" PORT="" UPLOAD_NETS="" PUBLIC_URL=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --site-name) SITE_NAME="$2"; shift 2 ;;
      --staging|--nas) shift 2 ;;   # 舊版參數：暫存資料夾與 NAS 已改在插卡電腦設定，忽略
      --port) PORT="$2"; shift 2 ;;
      --upload-nets) UPLOAD_NETS="$2"; shift 2 ;;
      --public-url) PUBLIC_URL="$2"; shift 2 ;;
      --no-prompt) NO_PROMPT=1; shift ;;
      -h|--help) sed -n '2,15p' "$0" 2>/dev/null || true; exit 0 ;;
      *) die "不認得的參數：$1" ;;
    esac
  done
  [ "$(id -u)" = 0 ] || die "請用 root 執行"
  command -v apt-get >/dev/null || die "只支援 Debian / Ubuntu"

  # 重跑時沿用上次的設定（照片放哪也沿用：手動搬過資料夾的話，更新後不會指回空的預設位置）
  DATA=$(env_get SNAPPIPE_DATA); DATA=${DATA:-/var/lib/snappipe}
  PORT=${PORT:-$(env_get SNAPPIPE_PORT)}; PORT=${PORT:-8080}
  SITE_NAME=${SITE_NAME:-$(env_get SNAPPIPE_SITE_NAME)}

  say "安裝系統套件"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq </dev/null
  apt-get install -y -qq python3 python3-venv iproute2 curl ca-certificates </dev/null >/dev/null
  python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
    || die "需要 Python 3.10 以上（目前 $(python3 --version)），請用 Debian 12 / Ubuntu 22.04 以上"

  local IP CIDR NET
  IP=$(ip -o -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')
  [ -n "$IP" ] || IP=$(hostname -I | awk '{print $1}')
  CIDR=$(ip -o -4 addr show scope global | awk -v ip="$IP" '{split($4,a,"/"); if (a[1]==ip) print $4}' | head -1)
  NET=$(python3 -c "import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network)" "${CIDR:-$IP/24}")
  UPLOAD_NETS=${UPLOAD_NETS:-$(env_get SNAPPIPE_UPLOAD_NETS)}
  UPLOAD_NETS=${UPLOAD_NETS:-$NET,127.0.0.1/32}
  PUBLIC_URL=${PUBLIC_URL:-$(env_get SNAPPIPE_PUBLIC_URL)}
  # 舊版把區網 IP 寫成對外網址，經反向代理分享時通訊軟體抓不到縮圖；是那個舊預設值就清掉，改自動判斷
  [ "$PUBLIC_URL" = "http://$IP:$PORT" ] && PUBLIC_URL=""

  echo
  ask SITE_NAME "網站名稱：整個返圖站的名字，例「小明的返圖」（每本相簿的名稱之後上傳時才設定）" "返圖"
  # 清掉終端機可能夾帶的控制字元、無效位元組與單引號（設定檔用單引號包）
  SITE_NAME=$(python3 -c '
import sys
s = sys.argv[1].encode("utf-8", "surrogateescape").decode("utf-8", "ignore")
print("".join(c for c in s if c.isprintable() and c not in "\x27\ufffd").strip())' "$SITE_NAME")
  [ -n "$SITE_NAME" ] || SITE_NAME="返圖"

  say "取得程式（後端 + 前端）"
  TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
  if [ -n "${SNAPPIPE_SRC:-}" ]; then
    # 原始碼版：從 repo 取後端與已 build 好的前端
    [ -f "$SNAPPIPE_SRC/web/dist/index.html" ] || die "找不到 $SNAPPIPE_SRC/web/dist，前端還沒 build"
    mkdir -p "$TMP/server" "$TMP/web"
    cp -a "$SNAPPIPE_SRC/server/app" "$SNAPPIPE_SRC/server/requirements.txt" "$TMP/server/"
    cp -a "$SNAPPIPE_SRC/web/dist" "$TMP/web/dist"
    cp "$SNAPPIPE_SRC/deploy/snappipe.service" "$TMP/"
  else
    printf '%s' "$PAYLOAD_B64" | base64 -d | tar -xz -C "$TMP"
  fi
  id snappipe &>/dev/null || useradd --system --home "$DATA" --shell /usr/sbin/nologin snappipe
  mkdir -p "$APP" "$DATA"
  rm -rf "$APP/server/app" "$APP/web"
  mkdir -p "$APP/server" "$APP/web"
  cp -a "$TMP/server/." "$APP/server/"
  cp -a "$TMP/web/." "$APP/web/"
  cp "$TMP/snappipe.service" /etc/systemd/system/snappipe.service

  say "建立 Python 環境"
  [ -x "$APP/server/.venv/bin/python" ] || python3 -m venv "$APP/server/.venv"
  "$APP/server/.venv/bin/pip" install -q --upgrade pip </dev/null
  "$APP/server/.venv/bin/pip" install -q -r "$APP/server/requirements.txt" </dev/null
  chown -R snappipe:snappipe "$DATA"

  say "寫入設定 $ENV_FILE"
  # 自己手動加進設定檔、這支腳本不認得的設定，原樣保留到新設定檔最後
  local EXTRA=""
  [ -f "$ENV_FILE" ] && EXTRA=$(grep -v -E '^(#|$|SNAPPIPE_(DATA|PORT|UPLOAD_TOKEN|UPLOAD_NETS|PUBLIC_URL|SITE_NAME|WORKER_TOKEN|DEVICE_TOKENS|HINT_[A-Z]+)=)' "$ENV_FILE" || true)
  local TOKEN; TOKEN=$(env_get SNAPPIPE_UPLOAD_TOKEN)
  [ -n "$TOKEN" ] || TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  # worker 預設不用 token（區網信任模式）：區網或同一台機器直連即可；之前設過的保留
  local WTOKEN; WTOKEN=$(env_get SNAPPIPE_WORKER_TOKEN)
  # 裝置 token：第一次給一台 pi-1；要加 Pi 就在設定檔多寫一組 名稱:token（逗號分隔）
  local DTOKENS; DTOKENS=$(env_get SNAPPIPE_DEVICE_TOKENS)
  [ -n "$DTOKENS" ] || DTOKENS="pi-1:$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  umask 077
  cat > "$ENV_FILE" <<ENV
# SnapPipe 設定（重跑安裝會保留 token）
SNAPPIPE_DATA=$DATA
SNAPPIPE_PORT=$PORT
SNAPPIPE_UPLOAD_TOKEN=$TOKEN
# 只有這些網段直連才能上傳（逗號分隔 CIDR），經反向代理轉進來的上傳一律拒絕
SNAPPIPE_UPLOAD_NETS=$UPLOAD_NETS
# 網站名稱（改完 systemctl restart snappipe）
SNAPPIPE_SITE_NAME='${SITE_NAME}'
# 對外網址，例 https://photos.example.com。留空 = 自動用瀏覽者連進來的網域
#（經反向代理時讀 X-Forwarded-Host / Proto），通訊軟體縮圖與分享連結都靠它
SNAPPIPE_PUBLIC_URL=$PUBLIC_URL
# 即時路徑：worker（Meta AI 處理端）與管理 API。留空 = 區網直連免 token（一個 worker 可服務多個返圖站）；
# 要讓外面的 worker 經 VPN / 反向代理連回來時，填一組 token（python3 -c 'import secrets; print(secrets.token_urlsafe(32))'）
SNAPPIPE_WORKER_TOKEN=$WTOKEN
# 樹莓派裝置 token：名稱:token，多台用逗號分隔；遺失就換掉那一組再 systemctl restart snappipe
SNAPPIPE_DEVICE_TOKENS=$DTOKENS
# 裝置 / worker 預設不限來源網段（通常經 WireGuard 或反向代理進來）；要限就填 CIDR，逗號分隔
#SNAPPIPE_DEVICE_NETS=
#SNAPPIPE_WORKER_NETS=
# 上傳端口的保護（JPG 與 RAW 共用）：單檔上限 MB、磁碟至少保留 GB、每台裝置同時進行中的上傳數
#SNAPPIPE_UPLOAD_MAX_MB=256
#SNAPPIPE_MIN_FREE_GB=2
#SNAPPIPE_MAX_INFLIGHT=16
# 以下只用來印出插卡電腦與 worker 的指令
SNAPPIPE_HINT_INGEST='$INGEST_CMD'
SNAPPIPE_HINT_SERVER=http://$IP:$PORT
ENV
  [ -z "$EXTRA" ] || printf '# 自訂設定（重跑安裝會保留）\n%s\n' "$EXTRA" >> "$ENV_FILE"
  umask 022

  # 之後忘記指令可在 LXC 執行 snappipe-cmd 再印一次
  cat > /usr/local/bin/snappipe-cmd <<'CMD'
#!/bin/bash
# 安裝完的「下一步」清單；忘了指令時再執行一次
set -a; source /etc/snappipe.env; set +a
RAW=https://raw.githubusercontent.com/normantaipei/SnapPipe/main
LAN="$SNAPPIPE_HINT_SERVER"
PUB="${SNAPPIPE_PUBLIC_URL%/}"
URL="${PUB:-$LAN}"
# 裝在 Proxmox 的 LXC（create-lxc.sh 記下了容器編號）：伺服器上的指令改成在 Proxmox Shell 執行的寫法
# pct exec 的 PATH 不含 /usr/local/bin，所以指令要寫完整路徑
P=""; [ -n "${SNAPPIPE_CTID:-}" ] && P="pct exec $SNAPPIPE_CTID -- /usr/local/bin/"

echo "返圖站：${SNAPPIPE_SITE_NAME:-SnapPipe}　${PUB:+$PUB（對外）　}$LAN（區網）"
echo
echo "── 下一步 ──────────────────────────────────────────────"
echo
echo "① 裝樹莓派：在 Pi 上貼這行（--mode：gphoto2 = 相機 USB 接 Pi、ftp = 相機用 FTP 傳給 Pi、watch = 看資料夾）"
IFS=',' read -ra _devs <<< "$SNAPPIPE_DEVICE_TOKENS"
for _d in "${_devs[@]}"; do
  _d="${_d// /}"; [ -n "$_d" ] || continue
  printf '   curl -fsSL %s/agent/bootstrap.sh | sudo bash -s -- --url %s --token %s --name %s --mode gphoto2\n' \
    "$RAW" "$URL" "${_d#*:}" "${_d%%:*}"
done
if [ -z "$PUB" ]; then
  echo "   ⚠ 這是區網網址，Pi 離開這個網路就連不到；要在外面上傳請設對外網址（見最下面「常用指令」）"
fi
echo "   看 Pi 的記錄（在 Pi 上）：journalctl -u snap-agent -f"
echo
echo "② 開拍：照片傳上來就自動建相簿（名稱預設是拍攝日期）。下面兩個連結現在就能用，永遠導到最新的相簿："
/usr/local/bin/snappipe-live links 2>/dev/null | sed 's/^/ /'
echo "   之後隨時查（含每本相簿各自的連結）：${P}snappipe-live links"
echo
echo "③ 賽後插卡匯入（Mac 或 Linux，在 SnapPipe 資料夾裡執行；要和伺服器在同一個區網）："
case "$SNAPPIPE_HINT_INGEST" in
  /*|~*) ;;
  *) echo "   （第一次先 git clone https://github.com/normantaipei/SnapPipe ）" ;;
esac
printf '   %s --server %s --token %s --save\n' "$SNAPPIPE_HINT_INGEST" "$LAN" "$SNAPPIPE_UPLOAD_TOKEN"
echo "   選用：--nas smb://帳號@NAS位址/共用資料夾/子資料夾（備份整張卡）、--album <相簿名稱>、--staging <暫存資料夾>"
echo
_unit=/etc/systemd/system/snappipe-worker.service
if [ -f "$_unit" ]; then
  _w=$(sed -n 's/^WorkingDirectory=//p' "$_unit")
  _a=$(sed -n 's/^ANALYZER=//p' "$_w/.env" 2>/dev/null | tail -1)
  echo "AI：$([ "$_a" = meta_ai ] && echo "Meta AI 開啟（選片、星等、圖說）" || echo "不用 AI，普通相簿")　worker $(systemctl is-active snappipe-worker 2>/dev/null)"
  echo "   worker 記錄：${SNAPPIPE_CTID:+pct exec $SNAPPIPE_CTID -- }journalctl -u snappipe-worker -f"
  echo "   比賽資料與名單：容器裡的 $_w/games/<相簿名稱>.toml / .csv（範本 example.toml）"
else
  echo "worker（Meta AI 處理端；可以裝在這台、Mac 或任何 Linux）："
  echo "   worker/setup.sh 會問並驗證 Meta API 金鑰（留空 = 不用 AI）；worker/.env 填 SERVER_URL=$LAN"
  [ -z "$SNAPPIPE_WORKER_TOKEN" ] || echo "   WORKER_TOKEN=$SNAPPIPE_WORKER_TOKEN"
fi
echo
echo "── 常用指令 ────────────────────────────────────────────"
echo "   即時上傳開關：${P}snappipe-live off | on | status"
echo "   再看一次這份清單：${P}snappipe-cmd"
if [ -n "${SNAPPIPE_CTID:-}" ]; then
  _upd="curl -fsSL $RAW/bootstrap.sh | bash -s -- --no-prompt"
  echo "   更新（返圖站與 worker 一起）：pct exec $SNAPPIPE_CTID -- bash -c '$_upd'"
  [ -n "$PUB" ] || echo "   設對外網址：pct exec $SNAPPIPE_CTID -- bash -c '$_upd --public-url https://你的網域'"
  [ -f "$_unit" ] && echo "   換 Meta 金鑰 / 開 AI：curl -fsSL $RAW/deploy/create-lxc.sh | bash -s -- --set-key --id $SNAPPIPE_CTID"
  echo "   進容器：pct enter $SNAPPIPE_CTID"
else
  echo "   更新：curl -fsSL $RAW/bootstrap.sh | bash -s -- --no-prompt$([ -n "$PUB" ] || echo "（加 --public-url https://你的網域 設對外網址）")"
fi
CMD
  chmod 700 /usr/local/bin/snappipe-cmd

  # 即時上傳總開關：snappipe-live on / off / status
  cat > /usr/local/bin/snappipe-live <<'CMD'
#!/bin/bash
set -a; source /etc/snappipe.env; set +a
cd /opt/snappipe/server && exec .venv/bin/python -m app.ctl "$@"
CMD
  chmod 755 /usr/local/bin/snappipe-live

  say "啟動服務"
  systemctl daemon-reload
  systemctl enable snappipe >/dev/null 2>&1
  systemctl restart snappipe
  local ok=""
  for _ in $(seq 1 20); do
    curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && { ok=1; break; }
    sleep 0.5
  done
  [ -n "$ok" ] || die "服務沒有起來，請看 journalctl -u snappipe -n 50"

  echo
  echo "════════════════════ ✅ SnapPipe 安裝完成 ════════════════════"
  echo "  返圖站：${SITE_NAME}　${PUBLIC_URL:-http://$IP:$PORT}"
  [ -n "$PUBLIC_URL" ] || echo "  對外網址：自動（經反向代理 / https 網域連進來時，縮圖與連結會用那個網域）"
  echo "  插卡上傳 / 管理：token + 只接受 $UPLOAD_NETS 直連"
  echo "  Pi 上傳：裝置 token，不限網段（伺服器只在區網時，外面要經 WireGuard / Tailscale 或反向代理）"
  echo "  worker（Meta AI）：$([ -n "$WTOKEN" ] && echo token || echo "區網直連免 token")"
  echo "  資料：$DATA   設定：$ENV_FILE"
  echo
  /usr/local/bin/snappipe-cmd
  echo
  echo "  忘記指令：在這台 LXC 執行 snappipe-cmd"
  echo "═════════════════════════════════════════════════════════════════"
}

# 原始碼版（bootstrap.sh 設了 SNAPPIPE_SRC）直接執行；打包版由 build-installer.sh 在下面附加程式包與 main "$@"
if [ -n "${SNAPPIPE_SRC:-}" ]; then main "$@"; fi
# ---- 以下由 build-installer.sh 附加 ----
