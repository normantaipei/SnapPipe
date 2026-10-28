#!/usr/bin/env bash
# 樹莓派 snap-agent 一行安裝（Raspberry Pi OS Bookworm / Debian 12，以 root 執行；重跑即更新）
#
#   curl -fsSL https://raw.githubusercontent.com/normantaipei/SnapPipe/main/agent/bootstrap.sh | sudo bash -s -- \
#     --url https://snappipe.example.com --token <裝置token> --name pi-1 --mode gphoto2
#
# 參數：
#   --url URL           SnapPipe 伺服器（安裝完印出的網址，或反向代理的 https 網域）
#   --token TOKEN       這台 Pi 的裝置 token（伺服器 /etc/snappipe.env 的 SNAPPIPE_DEVICE_TOKENS 裡的那組）
#   --name NAME         裝置名稱（顯示用）                       預設 pi-1
#   --mode MODE         gphoto2（相機 USB 接 Pi）/ ftp（Pi 開 FTP 給相機連）/ watch（看資料夾）  預設 gphoto2
#   --ftp-user U --ftp-password P   mode=ftp 時相機登入 Pi 的帳密   預設 camera / 隨機
#   --send-raw          RAW 也傳（排在所有 JPG 之後、安靜期才傳）
#   --album NAME        預設相簿（不給 = 用拍攝日期；伺服器指定的優先）
#   --ref BRANCH        要裝哪個分支                            預設 main
# 沒給 --url / --token 且 /etc/snap-agent.toml 已存在：只更新程式，不動設定。
set -euo pipefail
export LC_ALL=C.UTF-8 LANG=C.UTF-8 LANGUAGE=

GIT="${SNAPPIPE_GIT:-https://github.com}"
REPO="${SNAPPIPE_REPO:-normantaipei/SnapPipe}"
REF=main
DIR=/opt/snap-agent/src
CONF=/etc/snap-agent.toml
URL="" TOKEN="" NAME="pi-1" MODE="gphoto2" FTP_USER="camera" FTP_PASS="" SEND_RAW="false" ALBUM=""

die() { printf '\n\033[1;31m✗ %b\033[0m\n' "$*" >&2; exit 1; }
say() { echo -e "\033[1;36m▸\033[0m $*"; }

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --url) URL="${2%/}"; shift 2 ;;
      --token) TOKEN="$2"; shift 2 ;;
      --name) NAME="$2"; shift 2 ;;
      --mode) MODE="$2"; shift 2 ;;
      --ftp-user) FTP_USER="$2"; shift 2 ;;
      --ftp-password) FTP_PASS="$2"; shift 2 ;;
      --send-raw) SEND_RAW="true"; shift ;;
      --album) ALBUM="$2"; shift 2 ;;
      --ref) REF="$2"; shift 2 ;;
      -h|--help) sed -n '2,18p' "$0" 2>/dev/null || true; exit 0 ;;
      *) die "不認得的參數：$1" ;;
    esac
  done
  [ "$(id -u)" = 0 ] || die "請用 sudo 執行"
  command -v apt-get >/dev/null || die "只支援 Raspberry Pi OS / Debian"
  case "$MODE" in gphoto2|ftp|watch) ;; *) die "--mode 只能是 gphoto2 / ftp / watch" ;; esac
  if [ -z "$URL" ] && [ ! -f "$CONF" ]; then die "第一次安裝需要 --url 與 --token（伺服器安裝完印出的）"; fi
  if [ -n "$URL" ] && [ -z "$TOKEN" ]; then die "有 --url 就要一起給 --token"; fi

  say "安裝 git"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq </dev/null
  apt-get install -y -qq git ca-certificates </dev/null >/dev/null

  if [ -d "$DIR/.git" ]; then
    say "更新程式碼（$DIR）"
    git -C "$DIR" fetch -q --depth 1 origin "$REF" </dev/null
    git -C "$DIR" checkout -q -f FETCH_HEAD </dev/null
  else
    say "下載程式碼 $GIT/$REPO（$REF）→ $DIR"
    mkdir -p "$(dirname "$DIR")"
    git clone -q --depth 1 --branch "$REF" "$GIT/$REPO.git" "$DIR" </dev/null
  fi
  say "版本：$(git -C "$DIR" log -1 --format='%h %s' </dev/null)"

  say "安裝 snap-agent（$MODE）"
  local extra=""
  [ "$MODE" = gphoto2 ] && extra="--gphoto2"
  bash "$DIR/agent/install.sh" $extra </dev/null

  if [ -n "$URL" ]; then
    say "寫入設定 $CONF"
    [ -n "$FTP_PASS" ] || FTP_PASS=$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')
    local delete_after=false
    [ "$MODE" = ftp ] && delete_after=true
    umask 027
    cat > "$CONF" <<TOML
# snap-agent 設定（由 bootstrap.sh 產生；改完 systemctl restart snap-agent）

[server]
url = "$URL"
token = "$TOKEN"
chunk_mb = 1
heartbeat_sec = 15
timeout_sec = 30

[device]
name = "$NAME"
album = "$ALBUM"                      # 空 = 用拍攝日期；伺服器指定的優先
newest_first = true
state_dir = "/var/lib/snap-agent"
battery_cmd = ""                     # 例 PiSugar："echo 'get battery' | nc -q 0 127.0.0.1 8423"

[source]
mode = "$MODE"                       # gphoto2 / ftp / watch
dir = "/var/lib/snap-agent/inbox"
delete_after = $delete_after
send_raw = $SEND_RAW
raw_idle_sec = 30
settle_sec = 1.0

[ftp]
listen = "0.0.0.0"
port = 2121
user = "$FTP_USER"
password = "$FTP_PASS"
TOML
    chown root:snap "$CONF"; chmod 640 "$CONF"
    systemctl restart snap-agent
  fi

  say "測試連線"
  sleep 1
  if sudo -u snap /opt/snap-agent/.venv/bin/python /opt/snap-agent/snap_agent.py -c "$CONF" test </dev/null; then :; else
    echo "  ⚠ 連不上伺服器或 token 錯，請檢查 $CONF 的 [server]；journalctl -u snap-agent -f 看詳細"
  fi
  local ip; ip=$(hostname -I 2>/dev/null | awk '{print $1}')
  echo
  echo "════════════════ ✅ snap-agent 安裝完成 ════════════════"
  echo "  裝置：$NAME   模式：$MODE   伺服器：$(sed -n 's/^url = "\(.*\)"/\1/p' "$CONF")"
  case "$MODE" in
    ftp) echo "  相機 FTP 設定：主機 ${ip:-<Pi 的 IP>}  port 2121  帳號 $(sed -n 's/^user = "\(.*\)"/\1/p' "$CONF")  密碼 $(sed -n 's/^password = "\(.*\)"/\1/p' "$CONF")  被動模式 開  只傳 JPEG" ;;
    gphoto2) echo "  相機：USB 接 Pi，設成 PC 遙控 / PTP，照片存記憶卡；接上後日誌會顯示「相機已連線」" ;;
    watch) echo "  把 JPG 放進 /var/lib/snap-agent/inbox 就會傳" ;;
  esac
  echo "  日誌：journalctl -u snap-agent -f"
  echo "  待傳 / 指定相簿（用 snap 身分跑，待傳清單才不會變成 root 的）："
  echo "    sudo -u snap /opt/snap-agent/.venv/bin/python /opt/snap-agent/snap_agent.py status | album <名稱> | retry"
  echo "  更新：重跑同一行（不給 --url 就只更新程式、保留設定）"
  echo "═══════════════════════════════════════════════════════"
}

main "$@"
