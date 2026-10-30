"""
snap-agent 的 1.44 吋 LCD 狀態畫面（Waveshare 1.44inch LCD HAT：ST7735S 128×128 SPI，搖桿 + 3 顆按鍵）

省電設計（TFT 的耗電幾乎都在背光，黑底不會比較省；所以重點是「背光亮多久」和「CPU 少做事」）：
  1. 背光三段：亮（on_sec）→ 暗（dim_sec，PWM 低亮度）→ 關。關的時候面板也進 Sleep In（只剩 µA），
     繪圖執行緒整個停下來，不畫、不送 SPI。
  2. 平常每拍一張、每傳一張都「不」叫醒螢幕——攝影師拍照時不會看它。只有需要注意的事才亮：
     伺服器斷線、被暫停、相機拔掉、新的錯誤、待傳堆積、電量掉到 20% / 10%。按任何鍵也會亮。
  3. 亮著的時候最多每秒一幀，畫面沒變就不送；有變也只送變動的那幾條（8 列一條），不整面重刷。
  4. 高對比、大字的版面，暗亮度（預設 10%）時也看得清楚，所以可以把暗段調得很低。
  5. 螢幕睡著時，agent 每 5 秒才給一次狀態（只用來判斷要不要叫醒），不是每秒。

接線：HAT 直接插 40pin。SPI0 CE0；DC=GPIO25、RST=GPIO27、背光=GPIO24。
按鍵：KEY1=21 下一頁、KEY2=20 立刻關螢幕、KEY3=16 長按 3 秒安全關機；搖桿 左=5 右=26 上=6 下=19 按=13。
螢幕睡著時按任何鍵只會叫醒，不會觸發動作。需要 /boot/firmware/config.txt 有 dtparam=spi=on（install.sh 會開）。
"""

import subprocess
import threading
import time

from display import fmt_mb

W = H = 128
BAND = 8                      # 局部更新的單位：8 列
HOLD_SEC = 3.0
PIN_DC, PIN_RST, PIN_BL = 25, 27, 24
KEYS = {"key1": 21, "key2": 20, "key3": 16, "left": 5, "right": 26, "up": 6, "down": 19, "press": 13}

# 方向：MADCTL（含 BGR 位元 0x08）與 RAM 偏移。0 = Waveshare 範例的預設方向（搖桿在左）
ROTATIONS = {0: (0x60, 1, 2), 1: (0xC0, 2, 3), 2: (0xA0, 3, 2), 3: (0x00, 2, 1)}

# 顏色（RGB）
BG, FG, DIM = (0, 0, 0), (235, 235, 235), (120, 120, 120)
HEAD = (28, 28, 28)
GREEN, CYAN, AMBER, RED = (40, 200, 90), (40, 170, 230), (245, 170, 30), (235, 50, 50)


# ---------- 面板驅動 ----------

class ST7735S:
    def __init__(self, rotate=0, spi_hz=16_000_000, offset_x=-1, offset_y=-1, bus=0, dev=0):
        import spidev
        from gpiozero import DigitalOutputDevice
        self.spi = spidev.SpiDev()
        self.spi.open(bus, dev)
        self.spi.max_speed_hz = int(spi_hz)
        self.spi.mode = 0
        self.dc = DigitalOutputDevice(PIN_DC)
        self.rst = DigitalOutputDevice(PIN_RST, initial_value=True)
        self.madctl, ox, oy = ROTATIONS[int(rotate) % 4]
        self.ox = ox if int(offset_x) < 0 else int(offset_x)
        self.oy = oy if int(offset_y) < 0 else int(offset_y)
        self.asleep = False
        self._slept_at = 0.0
        self._init()

    def _cmd(self, c, data=b""):
        self.dc.off()
        self.spi.writebytes([c])
        if data:
            self.dc.on()
            self.spi.writebytes2(bytes(data))

    def _init(self):
        self.rst.on(); time.sleep(0.05)
        self.rst.off(); time.sleep(0.05)
        self.rst.on(); time.sleep(0.12)
        for c, d in [
            (0xB1, [0x05, 0x3C, 0x3C]), (0xB2, [0x05, 0x3C, 0x3C]), (0xB3, [0x05, 0x3C, 0x3C, 0x05, 0x3C, 0x3C]),
            (0xB4, [0x03]), (0xC0, [0x28, 0x08, 0x04]), (0xC1, [0xC0]), (0xC2, [0x0D, 0x00]),
            (0xC3, [0x8D, 0x2A]), (0xC4, [0x8D, 0xEE]), (0xC5, [0x1A]),
            (0xE0, [0x04, 0x22, 0x07, 0x0A, 0x2E, 0x30, 0x25, 0x2A, 0x28, 0x26, 0x2E, 0x3A, 0x00, 0x01, 0x03, 0x13]),
            (0xE1, [0x04, 0x16, 0x06, 0x0D, 0x2D, 0x26, 0x23, 0x27, 0x27, 0x25, 0x2D, 0x3B, 0x00, 0x01, 0x04, 0x13]),
            (0x3A, [0x05]), (0x36, [self.madctl | 0x08]),
        ]:
            self._cmd(c, d)
        self._cmd(0x11); time.sleep(0.12)
        self.blit(0, bytes(W * H * 2))      # 先清成黑色再開顯示，避免開機雜訊
        self._cmd(0x29)

    def blit(self, y0, data: bytes):
        """從第 y0 列開始，寫入整列寬的 RGB565 資料。"""
        y1 = y0 + len(data) // (W * 2) - 1
        x0, x1 = self.ox, self.ox + W - 1
        self._cmd(0x2A, [0, x0, 0, x1])
        self._cmd(0x2B, [0, y0 + self.oy, 0, y1 + self.oy])
        self._cmd(0x2C, data)

    def sleep(self):
        if not self.asleep:
            self._cmd(0x28)
            self._cmd(0x10)           # Sleep In：面板電流降到 µA 等級，顯示 RAM 保留
            self.asleep, self._slept_at = True, time.time()

    def wake(self):
        if self.asleep:
            wait = 0.12 - (time.time() - self._slept_at)   # 規格：Sleep In 後 120ms 內不能 Sleep Out
            if wait > 0:
                time.sleep(wait)
            self._cmd(0x11); time.sleep(0.12)
            self._cmd(0x29)
            self.asleep = False

    def close(self):
        try:
            self.sleep()
            self.spi.close()
        except Exception:
            pass


class Backlight:
    """0 與 1 用一般 GPIO（不跑 PWM 執行緒）；中間亮度才切成 PWM。PWM 開不起來就退回全亮／全關。"""

    def __init__(self, pin=PIN_BL, log=print):
        self.pin, self.dev, self.pwm, self.level, self.log = pin, None, False, None, log
        self.pwm_ok = True

    def set(self, level: float):
        level = max(0.0, min(1.0, level))
        if level == self.level:
            return
        try:
            self._set(level)
        except Exception as e:
            if not (0.0 < level < 1.0) or not self.pwm_ok:
                raise
            self.pwm_ok = False
            self.log(f"⚠ 背光 PWM 無法使用（{type(e).__name__}: {e}），改成只有全亮／全關")
            self.dev = None
            self._set(1.0)
            self.level = level

    def _set(self, level: float):
        from gpiozero import DigitalOutputDevice, PWMOutputDevice
        want_pwm = 0.0 < level < 1.0 and self.pwm_ok
        if not self.pwm_ok and 0.0 < level < 1.0:
            level = 1.0
        if self.dev is None or want_pwm != self.pwm:
            if self.dev:
                try:
                    self.dev.close()
                except Exception:
                    pass
            self.dev = PWMOutputDevice(self.pin, frequency=500) if want_pwm else DigitalOutputDevice(self.pin)
            self.pwm = want_pwm
        if want_pwm:
            self.dev.value = level
        else:
            self.dev.on() if level >= 1.0 else self.dev.off()
        self.level = level

    def close(self):
        if self.dev:
            self.dev.off()
            self.dev.close()


def to_rgb565(img, y0, y1) -> bytes:
    """PIL RGB 影像第 y0..y1-1 列 → 大端序 RGB565。"""
    part = img.crop((0, y0, W, y1))
    try:
        import numpy as np
        a = np.asarray(part, dtype=np.uint16)
        v = ((a[..., 0] & 0xF8) << 8) | ((a[..., 1] & 0xFC) << 3) | (a[..., 2] >> 3)
        return v.astype(">u2").tobytes()
    except ImportError:
        out = bytearray()
        for r, g, b in part.getdata():
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out += bytes((v >> 8, v & 0xFF))
        return bytes(out)


# ---------- 字型 ----------

def _font(size, bold=False, mono=False):
    from PIL import ImageFont
    name = "DejaVuSansMono" if mono else "DejaVuSans"
    name += "-Bold" if bold else ""
    try:
        return ImageFont.truetype(f"/usr/share/fonts/truetype/dejavu/{name}.ttf", size)
    except OSError:
        try:
            return ImageFont.load_default(size)
        except TypeError:
            return ImageFont.load_default()


# ---------- 畫面 ----------

class Renderer:
    """純繪圖（不碰硬體），方便在電腦上產生預覽圖。"""
    PAGES = 2

    def __init__(self):
        self.f_big = _font(44, bold=True)
        self.f_mid = _font(13, bold=True)
        self.f_sm = _font(11)
        self.f_mono = _font(10, mono=True)

    def status(self, s):
        """(顏色, 文字)：一條狀態色帶 + 一句話，一眼知道現在好不好。"""
        bat = s.get("battery")
        if bat is not None and bat < 10 and not s.get("charging"):
            return RED, "BATTERY LOW"
        if not s.get("server_ok", True):
            return RED, "OFFLINE"
        if s.get("paused"):
            return AMBER, "PAUSED"
        if s.get("mode") == "gphoto2" and not s.get("camera_connected"):
            return AMBER, "NO CAMERA"
        if s.get("last_error"):
            return AMBER, "! " + s["last_error"]
        if s.get("current"):
            return CYAN, "UPLOADING"
        return GREEN, "READY"

    def render(self, s, page=0, overlay=None):
        from PIL import Image, ImageDraw
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        if overlay:
            self._overlay(d, overlay)
        elif page == 0:
            self._main(d, s)
        else:
            self._info(d, s)
        return img

    def _header(self, d, s):
        d.rectangle((0, 0, W - 1, 15), fill=HEAD)
        d.text((3, 2), (s.get("name") or "")[:9], font=self.f_sm, fill=FG)
        # Wi-Fi：4 格
        dbm = s.get("wifi")
        n = 0 if dbm is None else 4 if dbm >= -55 else 3 if dbm >= -65 else 2 if dbm >= -75 else 1 if dbm >= -85 else 0
        for i in range(4):
            x = 70 + i * 4
            d.rectangle((x, 12 - i * 3, x + 2, 12), fill=FG if i < n else (70, 70, 70))
        # 電池
        bat = s.get("battery")
        col = DIM if bat is None else RED if bat < 10 else AMBER if bat < 20 else FG
        d.rectangle((90, 4, 108, 11), outline=col)
        d.rectangle((109, 6, 110, 9), fill=col)
        if s.get("charging"):
            col = GREEN
            d.rectangle((90, 4, 108, 11), outline=col)
            d.rectangle((109, 6, 110, 9), fill=col)
        if bat is not None:
            d.rectangle((92, 6, 92 + int(14 * max(0, min(100, bat)) / 100), 9), fill=col)
            if s.get("charging"):          # 充電中：電池上畫一道閃電（黑色鏤空）
                d.polygon([(100, 4), (96, 8), (99, 8), (98, 11), (102, 7), (99, 7)], fill=BG)
            if bat < 99.5:                       # 100% 只畫滿格，空間放不下三位數
                d.text((113, 3), f"{bat:.0f}", font=self.f_mono, fill=col)

    def _main(self, d, s):
        self._header(d, s)
        color, text = self.status(s)
        d.rectangle((0, 16, W - 1, 18), fill=color)
        # 中央大數字：待傳張數（0 = 全部傳完）
        q = s.get("pending", 0)
        num = str(q) if q < 1000 else "999+"
        tw = d.textlength(num, font=self.f_big)
        d.text(((W - tw) / 2, 20), num, font=self.f_big, fill=FG if q else GREEN)
        lab = "to send" if q else "all sent"
        d.text(((W - d.textlength(lab, font=self.f_sm)) / 2, 68), lab, font=self.f_sm, fill=DIM)
        # 目前這張
        cur = s.get("current")
        if cur:
            name, off, total, mbps = cur
            frac = off / total if total else 0
            d.text((3, 84), name[:13], font=self.f_mono, fill=FG)
            d.text((W - 3 - d.textlength(f"{mbps:.0f}Mb", font=self.f_mono), 84), f"{mbps:.0f}Mb", font=self.f_mono, fill=DIM)
            d.rectangle((3, 97, W - 4, 102), outline=DIM)
            d.rectangle((4, 98, 4 + int((W - 9) * frac), 101), fill=CYAN)
        else:
            d.text((3, 88), f"last {s.get('last_done') or '--'}"[:20], font=self.f_mono, fill=DIM)
        # 底部：狀態句 + 已傳 / 失敗
        f = self.f_mid if d.textlength(text, font=self.f_mid) <= W - 6 else self.f_mono
        d.text((3, 102), text[:20], font=f, fill=color)
        foot = f"UP {s.get('done', 0)}"
        if s.get("failed"):
            foot += f"  ERR {s['failed']}"
        if s.get("spool_files"):
            foot += f"  SP {s['spool_files']}"
        d.text((3, 117), foot[:21], font=self.f_mono, fill=RED if s.get("failed") else DIM)

    def _info(self, d, s):
        self._header(d, s)
        d.rectangle((0, 16, W - 1, 18), fill=DIM)
        rows = [
            ("ver", s.get("version", "")),
            ("mode", s.get("mode", "")),
            ("srv", s.get("server", "")),
            ("ip", s.get("ip", "")),
            ("album", s.get("album") or "by date"),
            ("up", f"{s.get('uptime', 0) // 3600}h{s.get('uptime', 0) // 60 % 60:02d}m"),
            ("wifi", f"{s['wifi']} dBm" if s.get("wifi") is not None else "--"),
            ("bat", f"{s['battery']:.0f}%" if s.get("battery") is not None else "--"),
        ]
        for i, (k, v) in enumerate(rows):
            y = 22 + i * 13
            d.text((3, y), k, font=self.f_mono, fill=DIM)
            d.text((40, y), str(v)[:14], font=self.f_mono, fill=FG)

    def _overlay(self, d, lines):
        d.rectangle((0, 0, W - 1, H - 1), fill=BG)
        for i, t in enumerate(lines[:5]):
            d.text(((W - d.textlength(t, font=self.f_mid)) / 2, 30 + i * 18), t, font=self.f_mid, fill=FG)


# ---------- 狀態機 + 按鍵 ----------

AWAKE, DIMMED, ASLEEP = "awake", "dim", "asleep"


class LcdDisplay:
    def __init__(self, cfg: dict, log=print):
        self.cfg, self.log = cfg, log
        self.device = None
        self.on_sec = float(cfg.get("on_sec", 15))
        self.dim_sec = float(cfg.get("dim_sec", 15))
        self.bright = float(cfg.get("brightness", 100)) / 100
        self.dim_level = float(cfg.get("dim_brightness", 10)) / 100
        self.wake_on_photo = bool(cfg.get("wake_on_photo", False))
        self.backlog = int(cfg.get("backlog_alert", 20))
        self.page, self.snapshot, self.prev = 0, {}, None
        self.state, self.last_activity, self.overlay = AWAKE, time.time(), None
        self._want = None                    # 其他執行緒要求的狀態；只有繪圖執行緒會碰面板
        self._sent = None                    # 上一幀已送出的 RGB565（逐條比對）
        self._evt = threading.Event()
        self._lock = threading.Lock()
        self._stop = False
        self._buttons = []
        try:
            self.panel = ST7735S(cfg.get("rotate", 0), cfg.get("spi_hz", 16_000_000),
                                 cfg.get("offset_x", -1), cfg.get("offset_y", -1))
            self.bl = Backlight(log=self.log)
            self.renderer = Renderer()
        except Exception as e:
            mode = str(cfg.get("enabled", "auto")).lower()
            self.log(("LCD 未啟用" if mode == "auto" else "⚠ LCD 啟用失敗") + f"（{type(e).__name__}: {str(e)[:60]}）")
            return
        self.device = self.panel
        self._setup_buttons()
        self._set_state(AWAKE)
        threading.Thread(target=self._loop, daemon=True, name="lcd").start()
        self.log("LCD 1.44\" 已啟用")

    # agent 依這個決定多久給一次狀態：亮著每秒，睡著每 5 秒（只用來判斷要不要叫醒）
    def interval(self) -> float:
        return 1.0 if self.state != ASLEEP else 5.0

    # ---- 狀態 ----

    def update(self, snapshot: dict):
        with self._lock:
            prev, self.snapshot = self.snapshot, snapshot
        reason = self._alert(prev, snapshot)
        if reason:
            self.log(f"LCD 喚醒：{reason}")
            self._activity()
        elif self.state != ASLEEP:
            self._evt.set()

    def _alert(self, p, s):
        """只有「變成需要注意」的那一刻才叫醒（狀態持續不會一直亮）。"""
        if not p:
            return None
        if p.get("server_ok", True) and not s.get("server_ok", True):
            return "伺服器斷線"
        if not p.get("paused") and s.get("paused"):
            return "伺服器暫停上傳"
        if s.get("mode") == "gphoto2" and p.get("camera_connected") and not s.get("camera_connected"):
            return "相機斷開"
        if s.get("last_error") and s.get("last_error") != p.get("last_error"):
            return "新錯誤"
        if s.get("failed", 0) > p.get("failed", 0):
            return "上傳失敗"
        if p.get("pending", 0) < self.backlog <= s.get("pending", 0):
            return f"待傳堆到 {self.backlog} 張"
        pb, sb = p.get("battery"), s.get("battery")
        if pb is not None and sb is not None and not s.get("charging"):
            for th in (20, 10):
                if pb >= th > sb:
                    return f"電量低於 {th}%"
        if self.wake_on_photo and s.get("done", 0) > p.get("done", 0):
            return "新照片"
        return None

    def _activity(self):
        self.last_activity = time.time()
        if self.state != AWAKE:
            self._want = AWAKE
        self._evt.set()

    def _set_state(self, st):
        if st == AWAKE:
            if self.panel.asleep:
                self.panel.wake()
                self._sent = None            # 醒來整面重送一次
            self.bl.set(self.bright)
        elif st == DIMMED:
            self.bl.set(self.dim_level)
        else:
            self.bl.set(0)
            self.panel.sleep()
        self.state = st

    # ---- 按鍵 ----

    def _setup_buttons(self):
        if str(self.cfg.get("buttons", True)).lower() in ("false", "0", "off", "no"):
            return
        try:
            from gpiozero import Button
            for name, pin in KEYS.items():
                b = Button(pin, pull_up=True, bounce_time=0.03, hold_time=HOLD_SEC if name == "key3" else 1.0)
                b.when_pressed = lambda n=name: self._on_press(n)
                if name == "key3":
                    b.when_held = self._on_hold
                self._buttons.append(b)
        except Exception as e:
            self.log(f"LCD 按鍵未啟用（{e}）")

    def _on_press(self, name):
        if self.state != AWAKE:      # 睡著或變暗：第一下只叫醒
            self._activity()
            return
        self.last_activity = time.time()
        if name in ("key1", "right", "press", "down"):
            self.page = (self.page + 1) % Renderer.PAGES
        elif name in ("left", "up"):
            self.page = (self.page - 1) % Renderer.PAGES
        elif name == "key2":
            self._want = ASLEEP
        elif name == "key3":
            self.overlay = ["Hold 3s", "to power off"]
        self._evt.set()

    def _on_hold(self):
        self.log("KEY3 長按：安全關機")
        self.overlay = ["Shutting down", "...", "", "wait for green", "LED to stop"]
        self._activity()
        time.sleep(0.3)
        subprocess.run(["sudo", "-n", "/sbin/poweroff"])

    # ---- 繪圖迴圈 ----

    def _loop(self):
        """任何錯誤都不能讓這個執行緒結束（否則畫面會停在最後一幀）：記下來、等一下、繼續。"""
        import traceback
        while not self._stop:
            try:
                self._step()
            except Exception as e:
                self.log(f"LCD 錯誤：{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}")
                time.sleep(2)

    def _step(self):
        want, self._want = self._want, None
        if want and want != self.state:
            self._set_state(want)
        idle = time.time() - self.last_activity
        if want == ASLEEP:
            pass
        elif self.state == AWAKE and idle > self.on_sec:
            self._set_state(DIMMED if self.dim_level > 0 and self.dim_sec > 0 else ASLEEP)
        elif self.state == DIMMED and idle > self.on_sec + self.dim_sec:
            self._set_state(ASLEEP)
        if self.state == ASLEEP:
            self._evt.wait()         # 睡著：不畫、不送 SPI，等按鍵或警示叫醒
            self._evt.clear()
            return
        if self.overlay and idle > 2 and not self.overlay[0].startswith("Shutting"):
            self.overlay = None
        self._push()
        self._evt.wait(1.0)          # 最多每秒一幀；有事就提早醒
        self._evt.clear()

    def _push(self):
        with self._lock:
            s = dict(self.snapshot)
        img = self.renderer.render(s, self.page, self.overlay)
        bands = [to_rgb565(img, y, y + BAND) for y in range(0, H, BAND)]
        if self._sent is None:
            dirty = list(range(len(bands)))
        else:
            dirty = [i for i, b in enumerate(bands) if b != self._sent[i]]
        if not dirty:
            return
        # 變動的條合成一段連續範圍送出（一次設定視窗，SPI 次數最少）
        lo, hi = dirty[0], dirty[-1]
        self.panel.blit(lo * BAND, b"".join(bands[lo:hi + 1]))
        self._sent = bands

    def close(self):
        self._stop = True
        self._evt.set()
        for b in self._buttons:
            b.close()
        if self.device:
            self.bl.close()
            self.panel.close()
