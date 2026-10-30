"""
snap-agent 的狀態畫面。[display] type 選螢幕：
  oled    0.96 吋 SSD1306 128×64 I2C（這個檔案）
  lcd144  Waveshare 1.44 吋 LCD HAT，ST7735S 128×128 SPI（display_lcd.py，含背光省電）

以下是 OLED（黃藍雙色：上 16 列黃、下 48 列藍）。

沒有螢幕、沒裝 luma.oled、I2C 沒開、沒接按鍵——都照常跑，只在日誌印一行。
agent 每秒給一份狀態快照（dict），這裡只負責畫；按鍵短按切頁、長按 3 秒安全關機。

接線：VCC→3.3V（pin 1）  GND→pin 6  SDA→GPIO2（pin 3）  SCL→GPIO3（pin 5）；按鍵接 GPIO17（pin 11）與 GND。
"""

import subprocess
import threading
import time

PAGES = 2
HOLD_SEC = 3.0


def wifi_dbm():
    """目前 Wi-Fi 訊號（dBm），讀 /proc/net/wireless；沒有就 None。"""
    try:
        for line in open("/proc/net/wireless"):
            parts = line.split()
            if len(parts) > 3 and parts[0].endswith(":"):
                return int(float(parts[3].rstrip(".")))
    except (OSError, ValueError):
        pass
    return None


def bars(dbm):
    if dbm is None:
        return "----"
    n = 4 if dbm >= -55 else 3 if dbm >= -65 else 2 if dbm >= -75 else 1 if dbm >= -85 else 0
    return "#" * n + "-" * (4 - n)


def fmt_mb(b):
    return f"{b / 1e6:.1f}M" if b < 1e9 else f"{b / 1e9:.2f}G"


def make_display(cfg: dict, log=print):
    """依 [display] type 建立螢幕；enabled = false 或型號不認得時回傳不畫任何東西的 Display。"""
    kind = str(cfg.get("type", "oled")).lower()
    if kind in ("lcd144", "lcd", "st7735") and str(cfg.get("enabled", "auto")).lower() not in ("false", "0", "off", "no"):
        from display_lcd import LcdDisplay
        return LcdDisplay(cfg, log)
    if kind not in ("oled", "ssd1306", "lcd144", "lcd", "st7735"):
        log(f"⚠ 不認得的 display.type：{kind}（oled / lcd144），不啟用螢幕")
        return Display({"enabled": False}, log)
    return Display(cfg, log)


class Display:
    def __init__(self, cfg: dict, log=print):
        self.cfg = cfg
        self.log = log
        self.device = None
        self.page = 0
        self.snapshot = {}
        self._stop = False
        self._button = None
        self._pressed_at = None
        mode = str(cfg.get("enabled", "auto")).lower()
        if mode in ("false", "0", "off", "no"):
            return
        try:
            from luma.core.interface.serial import i2c
            from luma.oled.device import ssd1306
            serial = i2c(port=int(cfg.get("i2c_port", 1)), address=int(str(cfg.get("address", "0x3c")), 16))
            self.device = ssd1306(serial, rotate=int(cfg.get("rotate", 0)))
        except Exception as e:   # 沒裝套件、I2C 沒開、沒接螢幕：都走這裡
            if mode == "auto":
                self.log(f"OLED 未啟用（{type(e).__name__}: {str(e)[:60]}）；沒接螢幕可忽略")
            else:
                self.log(f"⚠ OLED 啟用失敗：{e}")
            return
        self._setup_button()
        threading.Thread(target=self._loop, daemon=True, name="oled").start()
        self.log("OLED 已啟用")

    # ---- 按鍵（選用）----

    def _setup_button(self):
        pin = int(self.cfg.get("button_gpio", 0) or 0)
        if not pin:
            return
        try:
            from gpiozero import Button
            self._button = Button(pin, pull_up=True, hold_time=HOLD_SEC)
            self._button.when_released = self._on_release
            self._button.when_held = self._on_hold
        except Exception as e:
            self.log(f"OLED 按鍵未啟用（{e}）")

    def _on_release(self):
        if self._button.is_held:   # 剛剛是長按，不當成切頁
            return
        self.page = (self.page + 1) % PAGES

    def _on_hold(self):
        self.log("按鍵長按：安全關機")
        self._draw_text(["", "  Shutting down", "  ...", ""])
        subprocess.run(["sudo", "-n", "/sbin/poweroff"])

    # ---- 畫面 ----

    def update(self, snapshot: dict):
        self.snapshot = snapshot

    def interval(self) -> float:
        return 1.0

    def _loop(self):
        while not self._stop:
            try:
                self._draw()
            except Exception as e:
                self.log(f"OLED 繪圖錯誤：{e}")
                time.sleep(5)
            time.sleep(1.0)

    def _draw_text(self, lines):
        from luma.core.render import canvas
        with canvas(self.device) as d:
            for i, t in enumerate(lines[:4]):
                d.text((0, i * 16), t, fill="white")

    def _draw(self):
        from luma.core.render import canvas
        s = self.snapshot
        with canvas(self.device) as d:
            if self.page == 0:
                self._page_main(d, s)
            else:
                self._page_info(d, s)

    def _page_main(self, d, s):
        # 第 1 列（黃）：裝置  相機  Wi-Fi
        cam = "CAM" if s.get("camera_connected") else ("cam" if s.get("mode") == "gphoto2" else s.get("mode", "")[:4].upper())
        d.text((0, 0), f"{s.get('name', '')[:7]:<7} {cam:<4} {bars(s.get('wifi'))}", fill="white")
        # 第 2 列：待傳 / 已傳 / 失敗
        q = s.get("pending", 0)
        d.text((0, 16), f"Q:{q:<3} UP:{s.get('done', 0):<4} ERR:{s.get('failed', 0)}", fill="white")
        # 第 3 列：目前這張的進度條
        cur = s.get("current")
        if s.get("paused"):
            d.text((0, 32), "PAUSED by server", fill="white")
        elif cur:
            name, off, total, mbps = cur
            frac = off / total if total else 0
            d.text((0, 32), name[:12], fill="white")
            d.rectangle((78, 34, 127, 44), outline="white", fill="black")
            d.rectangle((79, 35, 79 + int(47 * frac), 43), fill="white")
            d.text((0, 48), f"{fmt_mb(off)}/{fmt_mb(total)} {mbps:.0f}Mb", fill="white")
            return
        elif not s.get("server_ok", True):
            d.text((0, 32), "SERVER OFFLINE", fill="white")
        else:
            d.text((0, 32), f"idle  last {s.get('last_done', '--')}", fill="white")
        # 第 4 列：最後錯誤 / 電量 / 暫存
        err = s.get("last_error") or ""
        if err:
            d.text((0, 48), ("! " + err)[:21], fill="white")
        else:
            bat = s.get("battery")
            spool = s.get("spool_files", 0)
            d.text((0, 48), (f"BAT {bat:.0f}%  " if bat is not None else "") + (f"spool {spool}" if spool else ""), fill="white")

    def _page_info(self, d, s):
        d.text((0, 0), f"{s.get('name', '')}  v{s.get('version', '')}", fill="white")
        d.text((0, 16), (s.get("server", "") or "")[:21], fill="white")
        d.text((0, 32), f"album {s.get('album', '') or 'by date'}"[:21], fill="white")
        d.text((0, 48), f"{s.get('ip', '')}  up {s.get('uptime', 0) // 60}m", fill="white")

    def close(self):
        self._stop = True
        if self.device:
            try:
                self.device.clear()
            except Exception:
                pass
