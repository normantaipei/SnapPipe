#!/usr/bin/env bash
# 在 Proxmox 主機上建立 SnapPipe 用的 Debian 12 LXC（以 root 執行）
#
# 安裝法 A：從 Mac 經 SSH（只建 LXC 並放入公鑰，之後在 Mac 上打包、安裝）
#   ssh root@<PVE_IP> "bash -s -- --ssh-key '$(cat ~/.ssh/id_ed25519.pub)'" < deploy/create-lxc.sh
#
# 安裝法 B：直接在 Proxmox 的 Shell（網頁介面 → 節點 → Shell），一行建 LXC + 裝好返圖站與 worker，不需要 SSH
#   curl -fsSL https://raw.githubusercontent.com/normantaipei/SnapPipe/main/deploy/create-lxc.sh | bash -s -- --install
#   一開始會問：網站名稱、磁碟大小、Meta API 金鑰（輸入時不顯示，當場驗證；留空 = 不用 AI，只當普通相簿）
#
# 換 Meta API 金鑰 / 之後才開 AI（不用進容器）：
#   curl -fsSL https://raw.githubusercontent.com/normantaipei/SnapPipe/main/deploy/create-lxc.sh | bash -s -- --set-key --id <容器編號>
#
# 參數（都可省略）：
#   --install          建好後直接在容器裡跑 bootstrap.sh：從 GitHub 抓程式、build、安裝返圖站
#   --site-name NAME   拍攝計劃名稱：一台 LXC = 一個拍攝計劃 = 一本相簿，這也是相簿名稱（--install 用，沒給會詢問）
#                      暫存資料夾、NAS 備份、相簿名稱都是之後在 Mac 上傳時設定，這裡只架伺服器
#   --public-url URL   對外網址（反向代理 / https 網域），例 https://photos.example.com（--install 用）
#   --ref BRANCH|TAG   要裝哪個分支或 tag              預設 main
#   --id N             容器編號            預設下一個可用編號
#   --hostname NAME    主機名稱            預設 snappipe
#   --disk GB          根磁碟大小（照片也存這裡）  預設 64（--install 時會詢問）
#   --cores N          CPU 核心            預設 2
#   --memory MB        記憶體              預設 1024
#   --storage NAME     根磁碟放哪個 storage  預設第一個可放容器的（通常是 local-lvm）
#   --bridge NAME      網路橋接            預設 vmbr0（DHCP 取得 IP）
#   --ssh-key "KEY"    root 的 SSH 公鑰
#   --meta-key KEY     Meta API 金鑰（自動化用；也可以設環境變數 META_API_KEY）。沒給就詢問
#   --no-ai            不用 AI，只當普通相簿（不問金鑰）
#   --no-worker        不在容器裡裝 worker（worker 要裝在 Mac 或別台時）
#   --set-key          只換已建好容器的金鑰（搭配 --id）
#   --lang en          英文介面（安裝過程、下一步清單、預設的標籤與圖說都用英文）；預設繁體中文
#
# English: add --lang en, e.g.
#   curl -fsSL https://raw.githubusercontent.com/normantaipei/SnapPipe/main/deploy/create-lxc.sh | bash -s -- --install --lang en
set -euo pipefail
# 容器通常沒裝 en_US.UTF-8：一律用 Debian 內建的 C.UTF-8，中文輸入與輸出才正常，apt 也不會一直警告
export LC_ALL=C.UTF-8 LANG=C.UTF-8 LANGUAGE=

# fork 的人改這裡（或設環境變數）就會從自己的 repo 抓；GIT 是 Gitea / GitHub 的網址
GIT="${SNAPPIPE_GIT:-https://github.com}"
REPO="${SNAPPIPE_REPO:-normantaipei/SnapPipe}"
raw_url() { case "$GIT" in *github.com*) echo "https://raw.githubusercontent.com/$REPO/$1/$2" ;; *) echo "$GIT/$REPO/raw/branch/$1/$2" ;; esac; }

# 介面語言：SNAPPIPE_LANG=en（或 --lang en）印英文，其他印中文。t '中文' 'English'
t() { if [ "${SNAPPIPE_LANG:-}" = en ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }
die() { echo "❌ $*" >&2; exit 1; }
say() { echo -e "\033[1;36m▸\033[0m $*"; }

has_tty() { ( : </dev/tty ) 2>/dev/null; }

# ask 變數名 提示 預設值：變數已有值、或沒有終端機（例如經 ssh bash -s）就不問
ask() {
  local __v="${!1:-}"
  if [ -z "$__v" ] && has_tty; then
    read -r -p "  $2 [${3:-$(t 留空 blank)}]: " __v </dev/tty || true
  fi
  printf -v "$1" '%s' "${__v:-$3}"
}

# ── Meta API 金鑰：在 PVE 主機上問、當場驗證（查詢模型的端點，不收費）──────────
META_BASE="${META_API_BASE:-https://api.meta.ai/v1}"
META_MODEL="${META_MODEL:-muse-spark-1.3}"
CHECK_MSG=""

# 回傳 0 = 可以用、1 = 金鑰 / 模型有問題、2 = 連不上（晚點可能會好）
check_meta_key() {
  local hdr="$TMP/meta-auth" code
  ( umask 077; printf 'Authorization: Bearer %s\n' "$1" > "$hdr" )   # 金鑰不放在指令參數（ps 看得到）
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -H "@$hdr" "$META_BASE/models/$META_MODEL" </dev/null) || code=000
  rm -f "$hdr"
  case "$code" in
    200) CHECK_MSG="$(t "$META_MODEL 可以使用" "$META_MODEL is available")"; return 0 ;;
    401) CHECK_MSG="$(t "金鑰錯誤或已撤銷" "wrong or revoked key")"; return 1 ;;
    403) CHECK_MSG="$(t "這把金鑰沒有權限（或帳號所在地區不能用）" "this key has no access (or your region is not supported)")"; return 1 ;;
    404) CHECK_MSG="$(t "找不到模型 $META_MODEL" "model $META_MODEL not found")"; return 1 ;;
    000) CHECK_MSG="$(t "連不上 Meta（$META_BASE）" "can't reach Meta ($META_BASE)")"; return 2 ;;
    429|5*) CHECK_MSG="$(t "Meta 暫時無法回應（HTTP $code）" "Meta is not responding right now (HTTP $code)")"; return 2 ;;
    *) CHECK_MSG="HTTP $code"; return 1 ;;
  esac
}

# 結果放在 META_KEY（空 = 不用 AI）
ask_meta_key() {
  local rc yn
  if [ -n "$META_KEY" ]; then
    rc=0; check_meta_key "$META_KEY" || rc=$?
    if [ "$rc" = 0 ]; then say "$(t "Meta API 金鑰：$CHECK_MSG" "Meta API key: $CHECK_MSG")"; return; fi
    echo "  ❌ $(t "帶入的 Meta API 金鑰沒有通過：$CHECK_MSG" "The Meta API key you passed did not work: $CHECK_MSG")"
    has_tty || die "$(t "換一把金鑰再跑，或加 --no-ai" "Use another key, or add --no-ai")"
    META_KEY=""
  fi
  if ! has_tty; then
    echo "  $(t "（沒有終端機可以詢問 Meta API 金鑰：先不用 AI，之後用 --set-key 補上）" "(No terminal to ask for a Meta API key: AI stays off for now; add it later with --set-key)")"
    return
  fi
  echo "  $(t "Meta API 金鑰：https://dev.meta.ai → API keys（輸入時不顯示；直接 Enter = 不用 AI，只當普通相簿）" "Meta API key: https://dev.meta.ai → API keys (input is hidden; press Enter to skip AI and use it as a plain album site)")"
  while :; do
    read -r -s -p "  $(t 金鑰 Key): " META_KEY </dev/tty || META_KEY=""
    echo
    if [ -z "$META_KEY" ]; then
      echo "  $(t "→ 不用 AI：照片照常進相簿，不評分、不選片、不寫圖說" "→ No AI: photos still go to the album, without stars, picks or captions")"
      return
    fi
    echo "  $(t 驗證中… Checking…)"
    rc=0; check_meta_key "$META_KEY" || rc=$?
    if [ "$rc" = 0 ]; then echo "  ✅ $CHECK_MSG"; return; fi
    echo "  ❌ $(t "沒有通過：$CHECK_MSG" "Did not work: $CHECK_MSG")"
    if [ "$rc" = 2 ]; then
      read -r -p "  $(t "可能是網路暫時的問題。先存起來、之後再驗證？" "This may be a temporary network problem. Save it anyway and check later?") [y/N] " yn </dev/tty || yn=""
      case "$yn" in [Yy]*) return ;; esac
    fi
    echo "  $(t "請再輸入一次（直接 Enter = 不用 AI）" "Please try again (press Enter to skip AI)")"
  done
}

# 把金鑰（或不用 AI）送進容器的 worker；金鑰走 stdin，不出現在指令參數
push_worker() {
  local id="$1" src=/opt/snappipe/src
  if [ -n "$META_KEY" ]; then
    printf '%s\n' "$META_KEY" | pct exec "$id" -- env SNAPPIPE_LANG="${SNAPPIPE_LANG:-}" \
      bash "$src/deploy/install-worker.sh" --key-stdin --no-check
  else
    pct exec "$id" -- env SNAPPIPE_LANG="${SNAPPIPE_LANG:-}" bash "$src/deploy/install-worker.sh" --no-ai </dev/null
  fi
}

# 整段包在 main 裡：用 ssh … bash -s 從 stdin 讀腳本時，bash 會先讀完整個函式再執行，
# 中間的指令就不會把剩下的腳本當成自己的輸入吃掉
main() {
CTID="" HOST=snappipe DISK="" CORES=2 MEM=1024 STORAGE="" BRIDGE=vmbr0 SSH_KEY=""
INSTALL="" SITE_NAME="" PUBLIC_URL="" REF="main"
META_KEY="${META_API_KEY:-}" NO_AI="" NO_WORKER="" SET_KEY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --install) INSTALL=1; shift ;;
    --site-name) SITE_NAME="$2"; shift 2 ;;
    --ref) REF="$2"; shift 2 ;;
    --public-url) PUBLIC_URL="$2"; shift 2 ;;
    --id) CTID="$2"; shift 2 ;;
    --hostname) HOST="$2"; shift 2 ;;
    --disk) DISK="$2"; shift 2 ;;
    --cores) CORES="$2"; shift 2 ;;
    --memory) MEM="$2"; shift 2 ;;
    --storage) STORAGE="$2"; shift 2 ;;
    --bridge) BRIDGE="$2"; shift 2 ;;
    --ssh-key) SSH_KEY="$2"; shift 2 ;;
    --meta-key) META_KEY="$2"; shift 2 ;;
    --no-ai) NO_AI=1; shift ;;
    --no-worker) NO_WORKER=1; shift ;;
    --set-key) SET_KEY=1; shift ;;
    --lang) export SNAPPIPE_LANG="$2"; shift 2 ;;
    *) die "$(t "不認得的參數：$1" "Unknown option: $1")" ;;
  esac
done

command -v pct >/dev/null || die "$(t "請在 Proxmox 主機上執行（找不到 pct）" "Run this on the Proxmox host (pct not found)")"
[ "$(id -u)" = 0 ] || die "$(t "請用 root 執行" "Run as root")"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT

# --set-key：只換已建好容器的 Meta API 金鑰
if [ -n "$SET_KEY" ]; then
  [ -n "$CTID" ] || die "$(t "要指定容器編號：--set-key --id <編號>" "Give the container ID: --set-key --id <ID>")"
  pct status "$CTID" </dev/null 2>/dev/null | grep -q running || die "$(t "容器 $CTID 不存在或沒有在執行" "Container $CTID does not exist or is not running")"
  [ -n "$NO_AI" ] && META_KEY="" || ask_meta_key
  push_worker "$CTID" || die "$(t "worker 設定失敗，看記錄：" "Worker setup failed. Logs: ")pct exec $CTID -- journalctl -u snappipe-worker -n 50"
  return
fi

# --install：先把問題問完，接下來就不用守在旁邊
if [ -n "$INSTALL" ]; then
  echo
  echo "$(t "SnapPipe 安裝設定（直接 Enter 用預設值）" "SnapPipe setup (press Enter for the default)")"
  ask SITE_NAME "$(t "拍攝計劃名稱：這台返圖站只放這個拍攝計劃，也是唯一那本相簿的名稱，例「Saki 外拍 10/30」（之後可以用 snappipe-live album 改）" "Shoot plan name: this album site holds just this one shoot, and it is also the name of its only album, e.g. \"Saki shoot Oct 30\" (rename later with snappipe-live album)")" "$(t 返圖 SnapPipe)"
  ask DISK "$(t "LXC 磁碟大小 GB（這個拍攝計劃的 JPG + RAW 都存這裡，一場活動可能就數十 GB）" "LXC disk size in GB (all JPG + RAW files of this shoot live here; one event can take tens of GB)")" "64"
  ask PUBLIC_URL "$(t "對外網址：Pi 在外面上傳、分享連結用的 https 網域，例 https://photos.example.com（沒有就留空）" "Public URL: the https domain for uploads from outside and for share links, e.g. https://photos.example.com (leave blank if none)")" ""
  if [ -z "$NO_WORKER" ]; then
    if [ -n "$NO_AI" ]; then META_KEY=""; else ask_meta_key; fi
  fi
  echo
fi
DISK=${DISK:-64}
if [ -n "$PUBLIC_URL" ]; then                  # 只打網域也行：補上 https://、去掉結尾的 /
  case "$PUBLIC_URL" in http://*|https://*) ;; *) PUBLIC_URL="https://$PUBLIC_URL" ;; esac
  PUBLIC_URL="${PUBLIC_URL%/}"
fi
[[ "$DISK" =~ ^[0-9]+$ ]] || die "$(t "磁碟大小要是數字（GB）：$DISK" "Disk size must be a number (GB): $DISK")"

CTID=${CTID:-$(pvesh get /cluster/nextid </dev/null)}
pct status "$CTID" </dev/null &>/dev/null && die "$(t "容器編號 $CTID 已被使用，請用 --id 指定其他編號" "Container ID $CTID is taken; pick another with --id")"
ip link show "$BRIDGE" &>/dev/null || die "$(t "找不到網路橋接 ${BRIDGE}，請用 --bridge 指定" "Network bridge ${BRIDGE} not found; set one with --bridge")"

# 找存放模板的 storage 與放容器根磁碟的 storage（第一個啟用中的）
TPL_STORE=$(pvesm status -content vztmpl </dev/null | awk 'NR>1 && $3=="active" && !f {print $1; f=1}')
[ -n "$TPL_STORE" ] || die "$(t "沒有可放 LXC 模板（vztmpl）的 storage" "No storage that can hold LXC templates (vztmpl)")"
STORAGE=${STORAGE:-$(pvesm status -content rootdir </dev/null | awk 'NR>1 && $3=="active" && !f {print $1; f=1}')}
[ -n "$STORAGE" ] || die "$(t "沒有可放容器（rootdir）的 storage，請用 --storage 指定" "No storage for containers (rootdir); set one with --storage")"

say "$(t 更新模板清單 "Updating the template list")"
pveam update </dev/null >/dev/null
TPL=$(pveam available --section system </dev/null | awk '{print $2}' | grep '^debian-12-standard_.*_amd64\.tar\.zst$' | sort -V | tail -1)
[ -n "$TPL" ] || die "$(t "找不到 Debian 12 模板" "Debian 12 template not found")"
if ! pveam list "$TPL_STORE" </dev/null | grep -F "$TPL" >/dev/null; then
  say "$(t "下載模板 $TPL" "Downloading template $TPL")"
  pveam download "$TPL_STORE" "$TPL" </dev/null >/dev/null
fi

KEY_ARGS=()
if [ -n "$SSH_KEY" ]; then
  printf '%s\n' "$SSH_KEY" > "$TMP/key.pub"
  KEY_ARGS=(--ssh-public-keys "$TMP/key.pub")
fi

say "$(t "建立容器 ${CTID}（${HOST}，${CORES} 核 / ${MEM}MB / ${DISK}GB @ ${STORAGE}）" "Creating container ${CTID} (${HOST}, ${CORES} cores / ${MEM}MB / ${DISK}GB @ ${STORAGE})")"
pct create "$CTID" "$TPL_STORE:vztmpl/$TPL" \
  --hostname "$HOST" \
  --cores "$CORES" --memory "$MEM" --swap 512 \
  --rootfs "$STORAGE:$DISK" \
  --net0 "name=eth0,bridge=$BRIDGE,ip=dhcp" \
  --unprivileged 1 --features nesting=1 \
  --onboot 1 --start 1 \
  ${KEY_ARGS[@]+"${KEY_ARGS[@]}"} </dev/null >/dev/null

say "$(t "等待取得 IP" "Waiting for an IP address")"
IP=""
for _ in $(seq 1 60); do
  IP=$(pct exec "$CTID" -- ip -4 -o addr show eth0 </dev/null 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -1 || true)
  [ -n "$IP" ] && break
  sleep 1
done
[ -n "$IP" ] || die "$(t "容器已建立但 60 秒內沒拿到 IP，請檢查 DHCP（pct enter ${CTID}）" "Container created but got no IP within 60 seconds; check DHCP (pct enter ${CTID})")"

if [ -n "$INSTALL" ]; then
  # DHCP 拿到 IP 後 DNS 可能還沒好，等到能解析再裝
  for _ in $(seq 1 30); do
    pct exec "$CTID" -- getent hosts deb.debian.org </dev/null >/dev/null 2>&1 && break
    sleep 1
  done
  say "$(t "在容器 ${CTID} 裡安裝返圖站（從 ${GIT} 抓 ${REPO}@${REF}）" "Installing the album site in container ${CTID} (${REPO}@${REF} from ${GIT})")"
  pct exec "$CTID" -- bash -c 'apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null' </dev/null \
    || die "$(t "容器裡裝 curl 失敗，請檢查容器網路（pct enter ${CTID}）" "Could not install curl in the container; check its network (pct enter ${CTID})")"
  # 參數用 "$@" 傳進去，網站名稱有空白或中文也不會被拆開
  pct exec "$CTID" -- env SNAPPIPE_REPO="$GIT/$REPO.git" SNAPPIPE_REF="$REF" SNAPPIPE_LANG="${SNAPPIPE_LANG:-}" \
    bash -c 'curl -fsSL "'"$(raw_url "$REF" bootstrap.sh)"'" | bash -s -- "$@"' _ \
    --no-prompt --site-name "$SITE_NAME" ${PUBLIC_URL:+--public-url "$PUBLIC_URL"} </dev/null \
    || die "$(t "安裝失敗，可進容器看看：pct enter ${CTID}" "Install failed. Look inside the container: pct enter ${CTID}")"
  if [ -z "$NO_WORKER" ]; then
    push_worker "$CTID" || die "$(t "worker 安裝失敗，看記錄：" "Worker install failed. Logs: ")pct exec $CTID -- journalctl -u snappipe-worker -n 50"
  fi
  # 記下容器編號：snappipe-cmd 印指令時才知道要加 pct exec <編號>（重跑安裝會保留這行）
  pct exec "$CTID" -- bash -c "grep -q '^SNAPPIPE_CTID=' /etc/snappipe.env || echo 'SNAPPIPE_CTID=$CTID' >> /etc/snappipe.env" </dev/null || true
  # 對外網址有沒有通（反向代理設好了沒）
  PUB_OK=""
  if [ -n "$PUBLIC_URL" ]; then
    curl -fsS --max-time 10 "$PUBLIC_URL/healthz" </dev/null >/dev/null 2>&1 && PUB_OK=1
  fi
  # 「下一步」清單放在最後印，才不會被上面的安裝輸出蓋過
  echo
  echo "════════════════════ ✅ $(t "SnapPipe 安裝完成" "SnapPipe is installed") ════════════════════"
  echo "  $(t "容器編號：$CTID   主機名稱：$HOST   區網 IP：$IP" "Container: $CTID   Hostname: $HOST   LAN IP: $IP")"
  if [ -n "$PUBLIC_URL" ]; then
    if [ -n "$PUB_OK" ]; then echo "  $(t "對外網址：$PUBLIC_URL ✅ 連得到" "Public URL: $PUBLIC_URL ✅ reachable")"
    else echo "  $(t "對外網址：$PUBLIC_URL ⚠ 現在連不到：反向代理請轉到 http://$IP:8080（設好後 Pi 才能在外面上傳）" "Public URL: $PUBLIC_URL ⚠ not reachable yet: point your reverse proxy to http://$IP:8080 (the Pi can upload from outside once it works)")"; fi
  fi
  echo
  pct exec "$CTID" -- /usr/local/bin/snappipe-cmd </dev/null || true
  echo "═════════════════════════════════════════════════════════════════"
  return
fi

echo
echo "════════════════ ✅ $(t "LXC 建立完成" "LXC created") ════════════════"
echo "  $(t "容器編號：$CTID   主機名稱：$HOST   IP：$IP" "Container: $CTID   Hostname: $HOST   IP: $IP")"
if [ -n "$SSH_KEY" ]; then
  echo
  echo "  $(t "接著在 Mac 的 SnapPipe 資料夾安裝返圖站：" "Next, install the album site from the SnapPipe folder on your Mac:")"
  echo "    ./deploy/build-installer.sh && scp dist/snappipe-install.sh root@$IP:/tmp/ && ssh -t root@$IP bash /tmp/snappipe-install.sh"
else
  echo "  $(t "沒有放 SSH 公鑰：可在 Proxmox 用 pct enter $CTID 進入，或加 --install 直接安裝（見 README）" "No SSH key added: enter with pct enter $CTID on Proxmox, or rerun with --install (see README)")"
fi
echo "═════════════════════════════════════════════════"
}

main "$@"
