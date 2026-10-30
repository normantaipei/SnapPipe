#!/usr/bin/env bash
# 在樹莓派（Raspberry Pi OS Bookworm / Debian 12，以 root 執行）安裝 snap-agent
#
#   sudo bash agent/install.sh                 # 從這個 repo 的 agent/ 安裝
#   sudo bash agent/install.sh --gphoto2       # 連 libgphoto2 一起裝（相機 USB 直連模式）
#   sudo bash agent/install.sh --lang en       # 訊息用英文（也可以設環境變數 SNAPPIPE_LANG=en；bootstrap.sh 會帶進來）
#
# 重跑即為更新；/etc/snap-agent.toml 與待傳清單都會保留。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
APP=/opt/snap-agent
STATE=/var/lib/snap-agent
CONF=/etc/snap-agent.toml
WITH_GPHOTO=""
[ "${1:-}" = "--gphoto2" ] && WITH_GPHOTO=1
# 訊息語言：--lang 優先，否則看環境變數 SNAPPIPE_LANG（en = English，其他 = 中文）
for ((i = 1; i <= $#; i++)); do
  case "${!i}" in
    --lang) j=$((i + 1)); export SNAPPIPE_LANG="${!j:-}" ;;
    --lang=*) a="${!i}"; export SNAPPIPE_LANG="${a#*=}" ;;
  esac
done
t() { if [ "${SNAPPIPE_LANG:-}" = en ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }

say() { echo -e "\033[1;36m▸\033[0m $*"; }
[ "$(id -u)" = 0 ] || { echo "$(t '請用 sudo 執行' 'Please run with sudo')"; exit 1; }

say "$(t '系統套件' 'System packages')"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv >/dev/null
if [ -n "$WITH_GPHOTO" ]; then
  apt-get install -y -qq libgphoto2-6 python3-gphoto2 >/dev/null
  # gvfs 會搶相機的 USB；桌面版 Pi OS 才有，有的話停掉
  systemctl --global disable gvfs-gphoto2-volume-monitor 2>/dev/null || true
fi

id snap &>/dev/null || useradd --system --home "$STATE" --shell /usr/sbin/nologin --groups plugdev snap
for g in i2c spi gpio; do getent group "$g" >/dev/null && usermod -aG "$g" snap; done   # 螢幕與按鍵（選用）
mkdir -p "$APP" "$STATE/inbox"
cp "$HERE/snap_agent.py" "$HERE/display.py" "$HERE/display_lcd.py" "$HERE/requirements.txt" "$HERE/requirements-display.txt" "$APP/"
chown -R snap:snap "$STATE"

say "$(t 'Python 環境' 'Python environment')"
[ -x "$APP/.venv/bin/python" ] || python3 -m venv --system-site-packages "$APP/.venv"
"$APP/.venv/bin/pip" install -q --upgrade pip
"$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
# 螢幕（選用）：裝不起來也不影響上傳；I2C / SPI 沒開就打開（要重開機才生效）
# OLED 用 I2C + luma.oled；1.44 吋 LCD HAT 用 SPI + spidev；UPS HAT (C) 電量用 I2C + smbus2
say "$(t '螢幕套件（選用）' 'Display packages (optional)')"
apt-get install -y -qq python3-pil python3-gpiozero python3-lgpio python3-spidev python3-numpy python3-smbus2 \
  fonts-dejavu-core i2c-tools >/dev/null 2>&1 || true
"$APP/.venv/bin/pip" install -q -r "$APP/requirements-display.txt" 2>/dev/null || echo "$(t '  （OLED 套件沒裝成，沒接螢幕可忽略）' "  (OLED packages didn't install; safe to ignore if no screen is attached)")"
CFG=/boot/firmware/config.txt; [ -f "$CFG" ] || CFG=/boot/config.txt
if [ -f "$CFG" ] && ! grep -q '^dtparam=i2c_arm=on' "$CFG"; then
  echo 'dtparam=i2c_arm=on' >> "$CFG"; grep -q '^i2c-dev' /etc/modules || echo i2c-dev >> /etc/modules
  echo "$(t '  已開啟 I2C（重開機後生效）' '  Turned on I2C (takes effect after a reboot)')"
fi
if [ -f "$CFG" ] && ! grep -q '^dtparam=spi=on' "$CFG"; then
  echo 'dtparam=spi=on' >> "$CFG"
  echo "$(t '  已開啟 SPI（重開機後生效）' '  Turned on SPI (takes effect after a reboot)')"
fi
# 按鍵長按關機：snap 使用者只允許這一個指令
echo 'snap ALL=(root) NOPASSWD: /sbin/poweroff' > /etc/sudoers.d/snap-agent && chmod 440 /etc/sudoers.d/snap-agent

if [ ! -f "$CONF" ]; then
  cp "$HERE/config.example.toml" "$CONF"
  chmod 640 "$CONF"; chown root:snap "$CONF"
  say "$(t "已建立 $CONF，請填入 [server] 的 url 與 token（裝置 token 在伺服器的 /etc/snappipe.env）" "Created $CONF. Please fill in url and token under [server] (the device token is in /etc/snappipe.env on the server).")"
fi

cp "$HERE/snap-agent.service" /etc/systemd/system/snap-agent.service
systemctl daemon-reload
systemctl enable snap-agent >/dev/null 2>&1
systemctl restart snap-agent
echo
echo "$(t '✅ snap-agent 已安裝並啟動' '✅ snap-agent is installed and running')"
echo "$(t "  設定：$CONF        狀態：journalctl -u snap-agent -f" "  Config: $CONF        Status: journalctl -u snap-agent -f")"
echo "$(t "  待傳：sudo -u snap $APP/.venv/bin/python $APP/snap_agent.py status   （用 snap 身分，待傳清單才不會變成 root 的）" "  Queue: sudo -u snap $APP/.venv/bin/python $APP/snap_agent.py status   (run as snap so the queue isn't owned by root)")"
echo "$(t "  測試：sudo -u snap $APP/.venv/bin/python $APP/snap_agent.py test" "  Test: sudo -u snap $APP/.venv/bin/python $APP/snap_agent.py test")"
