#!/usr/bin/env python3
"""
snap-agent — 相機旁的樹莓派：照片一拍完就送到 SnapPipe 伺服器

Pi 只負責轉送、不運算、不篩選：
  1. 發現新照片（三種來源擇一）
       gphoto2  相機 USB 接 Pi，監聽 PTP 的 FILE_ADDED 事件，當下把檔案讀進 Pi 的暫存區（相機推來的是暫時物件，
                相機關機或拔線就拿不到），之後從暫存區上傳、傳完刪掉；相機設 PC 遙控、照片存記憶卡（PC+相機）
       watch    看一個資料夾：相機用自己的 FTP / Wi-Fi 傳進來、或任何方式丟進來的 JPG
       ftp      Pi 自己開一個 FTP 伺服器給相機連（純 FTP 只在相機和 Pi 之間），收到就轉送
  2. 待傳清單記在 SQLite（幾 KB），重開機接著傳；最新的先傳
  3. 以 1MB 分塊 PUT 到 /api/uploads/{id}，可續傳、冪等：斷線後從伺服器回報的 offset 接著送
  4. 每隔幾秒送心跳（待傳張數、電量…），並拿回管理端指定的相簿

用法：
  snap_agent.py run  [-c /etc/snap-agent.toml]     常駐（systemd 用這個）
  snap_agent.py status                             待傳 / 已傳 / 失敗
  snap_agent.py album 2026_10_30_CWT  |  --clear   本機指定相簿（伺服器指定的優先）
  snap_agent.py send /path/a.jpg                   手動排進待傳（測試用）
  snap_agent.py test                               測連線與 token
  snap_agent.py retry                              失敗的重新排入
"""

import argparse
import datetime as dt
import hashlib
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

VERSION = "0.2.0"
JPEG_EXT = {".jpg", ".jpeg"}
RAW_EXT = {".arw", ".cr2", ".cr3", ".nef", ".nrw", ".raf", ".orf", ".rw2", ".dng", ".pef"}

DEFAULTS = {
    "server": {"url": "", "token": "", "chunk_mb": 1, "heartbeat_sec": 15, "timeout_sec": 30},
    "device": {"name": socket.gethostname(), "album": "", "newest_first": True, "state_dir": "/var/lib/snap-agent",
               "battery_cmd": ""},
    "source": {"mode": "watch", "dir": "/var/lib/snap-agent/inbox", "delete_after": False, "send_raw": False,
               "raw_idle_sec": 30, "settle_sec": 1.0, "spool_min_free_mb": 500},
    "ftp": {"port": 2121, "user": "camera", "password": "", "listen": "0.0.0.0"},
    "display": {"enabled": "auto", "i2c_port": 1, "address": "0x3c", "rotate": 0, "button_gpio": 0},
}


def log(msg):
    print(f"{dt.datetime.now():%H:%M:%S} {msg}", flush=True)


# ---------- 設定 ----------

def load_config(path: Path) -> dict:
    cfg = {k: dict(v) for k, v in DEFAULTS.items()}
    if path.exists():
        with open(path, "rb") as f:
            for k, v in tomllib.load(f).items():
                cfg.setdefault(k, {}).update(v)
    for k in ("SNAP_SERVER_URL", "SNAP_DEVICE_TOKEN"):   # 環境變數可覆寫（測試方便）
        if os.environ.get(k):
            cfg["server"]["url" if k.endswith("URL") else "token"] = os.environ[k]
    if "only_jpeg" in cfg["source"]:   # 舊設定名
        cfg["source"]["send_raw"] = not cfg["source"].pop("only_jpeg")
    cfg["server"]["url"] = cfg["server"]["url"].rstrip("/")
    return cfg


# ---------- 待傳清單 ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    upload_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,        -- watch/ftp：檔案路徑；gphoto2：相機上的 folder/name
    filename TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    album TEXT,                  -- 入列當下決定的相簿（之後改指定不影響已入列的）
    kind TEXT NOT NULL DEFAULT 'jpeg',        -- jpeg / raw：JPG 全部傳完才輪到 RAW
    status TEXT NOT NULL DEFAULT 'pending',   -- pending / done / failed
    offset INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_try REAL NOT NULL DEFAULT 0,
    error TEXT,
    added REAL NOT NULL,
    done REAL
);
CREATE INDEX IF NOT EXISTS items_status ON items(status, next_try);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
"""


class Queue:
    def __init__(self, state_dir: Path):
        state_dir.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(state_dir / "queue.db", isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)
        if "kind" not in {r["name"] for r in self.con.execute("PRAGMA table_info(items)")}:
            self.con.execute("ALTER TABLE items ADD COLUMN kind TEXT NOT NULL DEFAULT 'jpeg'")

    def get(self, k, default=None):
        r = self.con.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default

    def set(self, k, v):
        if v is None:
            self.con.execute("DELETE FROM kv WHERE k=?", (k,))
        else:
            self.con.execute("INSERT OR REPLACE INTO kv (k, v) VALUES (?,?)", (k, str(v)))

    def known(self, upload_id) -> bool:
        return bool(self.con.execute("SELECT 1 FROM items WHERE upload_id=?", (upload_id,)).fetchone())

    def add(self, upload_id, source, filename, size, mtime, album):
        kind = "raw" if Path(filename).suffix.lower() in RAW_EXT else "jpeg"
        self.con.execute("INSERT OR IGNORE INTO items (upload_id, source, filename, size, mtime, album, kind, added) "
                         "VALUES (?,?,?,?,?,?,?,?)", (upload_id, source, filename, size, mtime, album, kind, time.time()))

    def next(self, newest_first: bool, raw_ok: bool = True):
        # JPG 永遠先於 RAW：現場要先看到照片，RAW 是附件，趁安靜期或賽後慢慢補；
        # RAW 之中，傳到一半（曾讓路給 JPG）的先接著傳完，不要同時掛著好幾個半成品
        order = "mtime DESC" if newest_first else "mtime"
        kinds = "" if raw_ok else "AND kind='jpeg'"
        return self.con.execute(f"SELECT * FROM items WHERE status='pending' AND next_try<=? {kinds} "
                                f"ORDER BY kind='raw', (kind='raw' AND offset>0) DESC, {order} LIMIT 1",
                                (time.time(),)).fetchone()

    def last_jpeg_added(self) -> float:
        r = self.con.execute("SELECT MAX(added) FROM items WHERE kind='jpeg'").fetchone()
        return r[0] or 0.0

    def jpeg_waiting(self) -> bool:
        return bool(self.con.execute("SELECT 1 FROM items WHERE status='pending' AND kind='jpeg' AND next_try<=? LIMIT 1",
                                     (time.time(),)).fetchone())

    def counts(self) -> dict:
        out = {"pending": 0, "done": 0, "failed": 0}
        for r in self.con.execute("SELECT status, COUNT(*) n FROM items GROUP BY status"):
            out[r["status"]] = r["n"]
        return out

    def progress(self, upload_id, offset):
        self.con.execute("UPDATE items SET offset=? WHERE upload_id=?", (offset, upload_id))

    def finish(self, upload_id):
        self.con.execute("UPDATE items SET status='done', done=?, error=NULL, offset=size WHERE upload_id=?",
                         (time.time(), upload_id))

    def retry_later(self, upload_id, error: str, attempts: int, give_up: bool = False):
        backoff = min(5 * 2 ** attempts, 300)   # 5s, 10s, 20s … 最多 5 分鐘；照片在卡上不會丟，慢慢重試
        self.con.execute("UPDATE items SET attempts=?, next_try=?, error=?, status=? WHERE upload_id=?",
                         (attempts + 1, time.time() + backoff, error[:500], "failed" if give_up else "pending",
                          upload_id))

    def prune(self, keep_days=7):
        self.con.execute("DELETE FROM items WHERE status='done' AND done < ?", (time.time() - keep_days * 86400,))


# ---------- 照片來源 ----------

class Item:
    def __init__(self, source: str, filename: str, size: int, mtime: float):
        self.source, self.filename, self.size, self.mtime = source, filename, size, mtime


class FolderSource:
    """看一個資料夾：檔案大小連續兩次相同、且修改時間過了 settle_sec 才算寫完。"""

    def __init__(self, cfg: dict):
        self.dir = Path(cfg["dir"]).expanduser()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.exts = JPEG_EXT | (RAW_EXT if cfg["send_raw"] else set())
        self.settle = float(cfg["settle_sec"])
        self.delete_after = cfg["delete_after"]
        self._last = {}   # path → size（上一次看到的大小）
        self._seen = set()

    def poll(self, timeout_ms: int = 300):
        out = []
        now = time.time()
        for p in self.dir.rglob("*"):
            if not p.is_file() or p.name.startswith(".") or p.suffix.lower() not in self.exts or str(p) in self._seen:
                continue
            try:
                st = p.stat()
            except FileNotFoundError:
                continue
            stable = self._last.get(str(p)) == st.st_size and now - st.st_mtime >= self.settle
            self._last[str(p)] = st.st_size
            if stable and st.st_size > 0:
                self._seen.add(str(p))
                self._last.pop(str(p), None)
                out.append(Item(str(p), p.name, st.st_size, st.st_mtime))
        return out

    def read(self, item) -> bytes:
        return Path(item["source"]).read_bytes()

    def done(self, item):
        if self.delete_after:
            Path(item["source"]).unlink(missing_ok=True)

    def stats(self) -> dict:
        return {}

    def close(self):
        pass


class FtpSource(FolderSource):
    """Pi 自己當 FTP 伺服器給相機連（相機的 FTP 設定指向 Pi），收到的檔案放進 inbox 再轉送。
    相機 ↔ Pi 之間是純 FTP，只走相機熱點 / 區網；Pi → 伺服器才走外網。"""

    def __init__(self, cfg: dict, ftp: dict):
        cfg = {**cfg, "delete_after": cfg.get("delete_after", True)}
        super().__init__(cfg)
        from pyftpdlib.authorizers import DummyAuthorizer
        from pyftpdlib.handlers import FTPHandler
        from pyftpdlib.servers import FTPServer
        if not ftp["password"]:
            sys.exit("ftp 模式需要在設定檔 [ftp] 填 password")
        auth = DummyAuthorizer()
        auth.add_user(ftp["user"], ftp["password"], str(self.dir), perm="elmwM")   # 只能上傳、建目錄，不能下載刪除
        src = self
        self.ftp = {"clients": 0, "received": 0, "incomplete": 0, "last_file": "", "last_at": 0.0}

        class Handler(FTPHandler):
            def on_connect(self):
                src.ftp["clients"] += 1

            def on_disconnect(self):
                src.ftp["clients"] = max(0, src.ftp["clients"] - 1)

            def on_file_received(self, file):
                src.ftp["received"] += 1
                src.ftp["last_file"] = Path(file).name
                src.ftp["last_at"] = time.time()

            def on_incomplete_file_received(self, file):   # 相機斷線傳到一半：丟掉，等相機重送
                src.ftp["incomplete"] += 1
                Path(file).unlink(missing_ok=True)

        handler = Handler
        handler.authorizer = auth
        handler.banner = "snap-agent"
        self.server = FTPServer((ftp["listen"], int(ftp["port"])), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        log(f"FTP 伺服器：{ftp['listen']}:{ftp['port']}（帳號 {ftp['user']}）→ {self.dir}")

    def stats(self) -> dict:
        return {"ftp_clients": self.ftp["clients"], "ftp_received": self.ftp["received"],
                "ftp_incomplete": self.ftp["incomplete"], "ftp_last_file": self.ftp["last_file"],
                "ftp_last_at": self.ftp["last_at"]}

    def close(self):
        self.server.close_all()


class CameraSource:
    """相機 USB 接 Pi：監聽 FILE_ADDED，事件一來就把檔案從相機讀下來存進 Pi 的暫存區（SD 卡），之後從暫存區上傳、傳完刪掉。
    為什麼要落地：Sony 等機身在遙控拍攝（PC Remote）模式推過來的影像是暫時物件，不是記憶卡上可瀏覽的檔案，
    事件當下沒抓走、相機一關機或拔線就拿不到了。先存進 SD 卡，相機隨時關機、拔線、Pi 重開機都不會掉。
    需要 libgphoto2 + python3-gphoto2（apt），相機設成 PC 遙控 / PTP、照片存到記憶卡（PC+相機）。"""

    RETRY_SEC = 5

    def __init__(self, cfg: dict, state_dir: Path):
        import gphoto2 as gp
        self.gp = gp
        self.exts = JPEG_EXT | (RAW_EXT if cfg["send_raw"] else set())
        self.spool = state_dir / "spool"
        self.spool.mkdir(parents=True, exist_ok=True)
        self.min_free = int(cfg.get("spool_min_free_mb", 500)) << 20
        self.camera = None
        self.serial = ""
        self.model = ""
        self._next_try = 0.0
        self._last_err = ""
        self.connect()

    def connect(self) -> bool:
        """試一次，不阻塞：相機關機、拔線時主迴圈照常心跳、照常上傳暫存區裡的檔。"""
        gp = self.gp
        if time.time() < self._next_try:
            return False
        self._next_try = time.time() + self.RETRY_SEC
        try:
            cam = gp.Camera()
            cam.init()
            try:   # 照片要留在記憶卡上
                tgt = cam.get_single_config("capturetarget")
                choices = [tgt.get_choice(i) for i in range(tgt.count_choices())]
                card = next((c for c in choices if "card" in c.lower() or "記憶" in c), None)
                if card and tgt.get_value() != card:
                    tgt.set_value(card)
                    cam.set_single_config("capturetarget", tgt)
            except gp.GPhoto2Error:
                pass
            try:
                self.serial = str(cam.get_single_config("serialnumber").get_value()).strip()
            except gp.GPhoto2Error:
                self.serial = ""
            self.camera = cam
            self.model = str(cam.get_abilities().model)
            self._last_err = ""
            log(f"相機已連線：{self.model}（序號 {self.serial or '?'}）")
            return True
        except gp.GPhoto2Error as e:
            if str(e) != self._last_err:   # 同樣的錯只印一次，不洗日誌
                log(f"等待相機（{e}）…")
                self._last_err = str(e)
            return False

    def free_bytes(self) -> int:
        st = os.statvfs(self.spool)
        return st.f_bavail * st.f_frsize

    def fetch(self, folder: str, name: str) -> Item | None:
        """把相機推來的檔案讀進暫存區（原子寫入）。"""
        gp = self.gp
        kind_raw = Path(name).suffix.lower() in RAW_EXT
        if kind_raw and self.free_bytes() < self.min_free:
            log(f"  ⚠ Pi 暫存區剩不到 {self.min_free >> 20} MB，略過 RAW {name}（回家插卡補）")
            return None
        info = self.camera.file_get_info(folder, name)
        mtime = float(info.file.mtime or time.time())
        cf = self.camera.file_get(folder, name, gp.GP_FILE_TYPE_NORMAL)
        data = bytes(cf.get_data_and_size())
        dst = self.spool / f"{int(mtime)}_{name}"
        if dst.exists() and dst.stat().st_size == len(data):
            return Item(str(dst), name, len(data), mtime)
        tmp = dst.with_name(dst.name + ".part")
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.utime(tmp, (mtime, mtime))
        tmp.replace(dst)
        return Item(str(dst), name, len(data), mtime)

    def poll(self, timeout_ms: int = 300):
        gp = self.gp
        if self.camera is None and not self.connect():
            return []
        out = []
        try:
            while True:
                evt, data = self.camera.wait_for_event(timeout_ms)
                if evt == gp.GP_EVENT_TIMEOUT:
                    break
                if evt == gp.GP_EVENT_FILE_ADDED:
                    name = data.name
                    if Path(name).suffix.lower() not in self.exts:
                        continue
                    item = self.fetch(data.folder, name)
                    if item:
                        out.append(item)
        except gp.GPhoto2Error as e:
            log(f"相機斷線（{e}）；暫存區裡的照片照常上傳，相機回來會自動重連")
            self.close()
        return out

    def read(self, item) -> bytes:
        return Path(item["source"]).read_bytes()

    def done(self, item):
        Path(item["source"]).unlink(missing_ok=True)

    def stats(self) -> dict:
        files = [f for f in self.spool.glob("*") if f.is_file() and not f.name.endswith(".part")]
        return {"camera_model": self.model, "camera_connected": self.camera is not None,
                "spool_files": len(files), "spool_mb": round(sum(f.stat().st_size for f in files) / 1e6, 1),
                "spool_free_mb": self.free_bytes() >> 20}

    def close(self):
        try:
            if self.camera:
                self.camera.exit()
        except Exception:
            pass
        self.camera = None


# ---------- 上傳 ----------

class Agent:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        s, d = cfg["server"], cfg["device"]
        if not s["url"] or not s["token"]:
            sys.exit("設定檔的 [server] 需要 url 與 token")
        self.q = Queue(Path(d["state_dir"]).expanduser())
        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {s['token']}"
        self.http.headers["User-Agent"] = f"snap-agent/{VERSION}"
        self.chunk = int(float(s["chunk_mb"]) * (1 << 20))
        self.timeout = float(s["timeout_sec"])
        self.remote_album = None   # 伺服器（管理端）指定的相簿
        self.paused = False        # 伺服器關掉即時上傳：暫停，照片留在卡上
        self.last_beat = 0.0
        self.last_error = ""
        self.started = time.time()
        self.server_ok = True
        self.current = None        # (檔名, 已傳 bytes, 總 bytes, Mbps)：OLED 進度條
        self.last_done = ""
        self.source = self.make_source()
        from display import Display
        self.display = Display(self.cfg["display"], log)

    def make_source(self):
        mode = self.cfg["source"]["mode"]
        if mode == "gphoto2":
            return CameraSource(self.cfg["source"], Path(self.cfg["device"]["state_dir"]).expanduser())
        if mode == "ftp":
            return FtpSource(self.cfg["source"], self.cfg["ftp"])
        if mode == "watch":
            return FolderSource(self.cfg["source"])
        sys.exit(f"不認得的 source.mode：{mode}（gphoto2 / watch / ftp）")

    # 相簿：伺服器指定 > 本機 album 指令 > 設定檔 > 拍攝日期（先用檔案時間，伺服器讀到 EXIF 會改用拍攝日）
    def album_for(self, mtime: float) -> str:
        return (self.remote_album or self.q.get("album") or self.cfg["device"]["album"]
                or "auto:" + dt.date.fromtimestamp(mtime).strftime("%Y_%m_%d"))

    def upload_id(self, item: Item) -> str:
        serial = getattr(self.source, "serial", "")
        key = f"{self.cfg['device']['name']}|{serial}|{item.source}|{item.size}|{int(item.mtime)}"
        return hashlib.sha256(key.encode()).hexdigest()[:40]

    def battery(self):
        cmd = self.cfg["device"]["battery_cmd"]
        if not cmd:
            return None
        try:
            out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5).stdout
            digits = "".join(c for c in out if c.isdigit() or c == ".")
            return float(digits) if digits else None
        except Exception:
            return None

    def heartbeat(self, force=False):
        s = self.cfg["server"]
        if not force and time.time() - self.last_beat < float(s["heartbeat_sec"]):
            return
        self.last_beat = time.time()
        c = self.q.counts()
        body = {"version": VERSION, "mode": self.cfg["source"]["mode"], "uptime": int(time.time() - self.started),
                "pending": c["pending"], "done": c["done"], "failed": c["failed"], "last_error": self.last_error[:200],
                "camera": getattr(self.source, "serial", ""), "local_album": self.q.get("album") or self.cfg["device"]["album"]}
        b = self.battery()
        if b is not None:
            body["battery"] = b
        if self.source is not None:
            body.update(self.source.stats())
        try:
            r = self.http.post(f"{s['url']}/api/devices/heartbeat", json=body, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            self.server_ok = True
            if self.last_error.startswith("heartbeat:"):
                self.last_error = ""
            if data.get("album") != self.remote_album:
                self.remote_album = data.get("album")
                log(f"伺服器指定相簿：{self.remote_album or '（無，用本機設定）'}")
            if data.get("chunk_bytes"):
                self.chunk = int(data["chunk_bytes"])
            paused = data.get("enabled") is False
            if paused != self.paused:
                self.paused = paused
                log("伺服器已關閉即時上傳：暫停，照片留在記憶卡上" if paused else "伺服器已開啟即時上傳：繼續傳")
            return data
        except requests.RequestException as e:
            self.last_error = f"heartbeat: {e}"
            self.server_ok = False
            log(f"心跳失敗：{e}")
            return None

    def server_offset(self, upload_id: str):
        r = self.http.head(f"{self.cfg['server']['url']}/api/uploads/{upload_id}", timeout=self.timeout)
        if r.status_code == 404:
            return 0, False
        r.raise_for_status()
        return int(r.headers.get("Upload-Offset", "0")), r.headers.get("Upload-Complete") == "1"

    def discover(self, quick: bool = False):
        """看來源有沒有新照片，排進待傳清單。quick：RAW 分段之間的檢查，相機事件只等 10ms，不拖慢上傳。"""
        for item in self.source.poll(10 if quick else 300):
            uid = self.upload_id(item)
            if not self.q.known(uid):
                album = self.album_for(item.mtime)
                self.q.add(uid, item.source, item.filename, item.size, item.mtime, album)
                log(f"＋ {item.filename}（{item.size / 1e6:.1f} MB）→ {album.removeprefix('auto:')}")

    def upload(self, row) -> bool:
        """把一張傳完；回傳是否成功（失敗會排進重試）。
        RAW 傳到一半有新 JPG 進來就先讓路（offset 已記下，之後從伺服器回報的位置接著傳）。"""
        url = f"{self.cfg['server']['url']}/api/uploads/{row['upload_id']}"
        try:
            offset = row["offset"]
            if row["attempts"] or row["offset"]:   # 重試或續傳時先問伺服器收到哪裡
                offset, complete = self.server_offset(row["upload_id"])
                if complete:
                    self.q.finish(row["upload_id"])
                    return True
            data = self.source.read(row)
            total = len(data)
            if total != row["size"]:
                log(f"  ⚠ {row['filename']} 大小變了（{row['size']} → {total}），重新入列")
                self.q.con.execute("UPDATE items SET size=?, offset=0 WHERE upload_id=?", (total, row["upload_id"]))
                offset = 0
            album, auto = row["album"], False
            if album.startswith("auto:"):
                album, auto = album[5:], True
            headers = {"X-SnapPipe-Album": album, "X-SnapPipe-Album-Auto": "1" if auto else "0",
                       "X-SnapPipe-Filename": row["filename"],
                       "X-SnapPipe-Camera": getattr(self.source, "serial", ""),
                       "X-SnapPipe-Taken-At": dt.datetime.fromtimestamp(row["mtime"]).isoformat(timespec="seconds")}
            t0 = time.time()
            self.current = (row["filename"], offset, total, 0.0)
            while offset < total:
                end = min(offset + self.chunk, total) - 1
                r = self.http.put(url, data=data[offset:end + 1],
                                  headers={**headers, "Content-Range": f"bytes {offset}-{end}/{total}",
                                           "Content-Type": "application/octet-stream"}, timeout=self.timeout)
                if r.status_code == 409:   # 伺服器的 offset 和我們以為的不同：照它的
                    offset = int(r.headers.get("Upload-Offset", "0"))
                    continue
                if r.status_code == 415:   # 不是 JPEG / RAW：不用再試
                    self.q.retry_later(row["upload_id"], r.text[:200], row["attempts"], give_up=True)
                    log(f"  ✗ {row['filename']} 被拒：{r.text[:120]}")
                    return False
                r.raise_for_status()
                body = r.json()
                offset = end + 1
                self.q.progress(row["upload_id"], offset)
                self.current = (row["filename"], offset, total, offset * 8 / max(time.time() - t0, 1e-3) / 1e6)
                self.refresh_display()
                self.heartbeat()   # 大檔分很多段時，中間也讓伺服器知道我們還活著
                if body.get("complete"):
                    break
                if row["kind"] == "raw" and offset < total:
                    self.discover(quick=True)
                    if self.q.jpeg_waiting():   # JPG 永遠優先：RAW 先讓路，等 JPG 傳完再接著
                        log(f"  ‖ {row['filename']} 暫停於 {offset / 1e6:.1f}/{total / 1e6:.1f} MB，先傳 JPG")
                        return False
            self.q.finish(row["upload_id"])
            self.source.done(row)
            self.last_error = ""
            self.current = None
            self.last_done = row["filename"][-8:]
            mbps = total * 8 / max(time.time() - t0, 1e-3) / 1e6
            log(f"  ✓ {row['filename']} → {body.get('album') or album}  {total / 1e6:.1f} MB  {mbps:.1f} Mbps"
                + ("（伺服器已有）" if body.get("duplicate") else "")
                + ("（RAW，等 JPG 到再配對）" if body.get("raw") and not body.get("paired") else ""))
            return True
        except FileNotFoundError:
            self.current = None
            self.q.retry_later(row["upload_id"], "來源檔案不見了", row["attempts"], give_up=True)
            log(f"  ✗ {row['filename']} 來源檔案不見了，放棄（記憶卡上還有，回家插卡補）")
            return False
        except (requests.RequestException, OSError, ValueError) as e:
            self.current = None
            self.last_error = str(e)
            self.q.retry_later(row["upload_id"], str(e), row["attempts"])
            log(f"  ⚠ {row['filename']} 失敗（第 {row['attempts'] + 1} 次）：{e}")
            return False
        except Exception as e:   # 相機讀檔之類的錯
            self.current = None
            self.last_error = str(e)
            self.q.retry_later(row["upload_id"], str(e), row["attempts"])
            log(f"  ⚠ {row['filename']} 讀取失敗：{e}")
            return False

    def snapshot(self) -> dict:
        """給 OLED 的狀態（每秒一次，便宜就好）。"""
        from display import wifi_dbm
        c = self.q.counts()
        st = self.source.stats() if self.source else {}
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except OSError:
            ip = ""
        return {"name": self.cfg["device"]["name"], "version": VERSION, "mode": self.cfg["source"]["mode"],
                "server": self.cfg["server"]["url"].split("://", 1)[-1], "server_ok": self.server_ok,
                "paused": self.paused, "ip": ip, "uptime": int(time.time() - self.started),
                "wifi": wifi_dbm(), "camera_connected": st.get("camera_connected"), "spool_files": st.get("spool_files", 0),
                "pending": c["pending"], "done": c["done"], "failed": c["failed"],
                "current": self.current, "last_done": self.last_done, "last_error": self.last_error.split(":")[-1].strip()[:40],
                "battery": self.battery_cached(), "album": self.remote_album or self.q.get("album") or self.cfg["device"]["album"]}

    def battery_cached(self):
        """電量指令可能慢（幾百 ms），最多每 30 秒讀一次。"""
        now = time.time()
        if now - getattr(self, "_bat_at", 0) > 30:
            self._bat, self._bat_at = self.battery(), now
        return getattr(self, "_bat", None)

    def refresh_display(self):
        if self.display.device and time.time() - getattr(self, "_disp_at", 0) >= 1.0:
            self._disp_at = time.time()
            self.display.update(self.snapshot())

    def run(self):
        d = self.cfg["device"]
        log(f"snap-agent {VERSION}  裝置 {d['name']}  模式 {self.cfg['source']['mode']}  → {self.cfg['server']['url']}")
        c = self.q.counts()
        if c["pending"]:
            log(f"上次還有 {c['pending']} 張沒傳完，接著傳")
        self.heartbeat(force=True)
        last_prune = 0
        while True:
            self.discover()
            # RAW 只在安靜期傳：最近 raw_idle_sec 秒沒有新 JPG 進來才輪到它（連拍空檔留給下一張 JPG）
            idle = float(self.cfg["source"]["raw_idle_sec"])
            raw_ok = idle <= 0 or time.time() - self.q.last_jpeg_added() >= idle
            row = None if self.paused else self.q.next(d["newest_first"], raw_ok)
            if row:
                self.upload(row)
            else:
                time.sleep(0.3)
            self.heartbeat()
            self.refresh_display()
            if time.time() - last_prune > 3600:
                self.q.prune()
                last_prune = time.time()


# ---------- 指令 ----------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", default=os.environ.get("SNAP_AGENT_CONFIG", "/etc/snap-agent.toml"))
    common = argparse.ArgumentParser(add_help=False)   # 讓 -c 放在子指令後面也接受（run -c …）
    common.add_argument("-c", "--config", dest="config2", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="常駐轉送", parents=[common])
    sub.add_parser("status", help="待傳清單", parents=[common])
    a = sub.add_parser("album", help="本機指定相簿（伺服器指定的優先）", parents=[common])
    a.add_argument("name", nargs="?")
    a.add_argument("--clear", action="store_true")
    s = sub.add_parser("send", help="手動把檔案排進待傳（測試）", parents=[common])
    s.add_argument("files", nargs="+")
    sub.add_parser("test", help="測連線與 token", parents=[common])
    sub.add_parser("retry", help="把失敗的重新排進待傳", parents=[common])
    args = ap.parse_args()
    cfg = load_config(Path(args.config2 or args.config))

    if args.cmd == "run":
        try:
            Agent(cfg).run()
        except KeyboardInterrupt:
            pass
        return
    q = Queue(Path(cfg["device"]["state_dir"]).expanduser())
    if args.cmd == "status":
        c = q.counts()
        log(f"待傳 {c['pending']}  已傳 {c['done']}  失敗 {c['failed']}  本機相簿 {q.get('album') or cfg['device']['album'] or '（拍攝日期）'}")
        for r in q.con.execute("SELECT * FROM items WHERE status!='done' ORDER BY mtime DESC LIMIT 20"):
            log(f"  {r['status']:<8} {r['filename']:<24} {r['offset']}/{r['size']}  第 {r['attempts']} 次  {r['error'] or ''}")
    elif args.cmd == "album":
        if args.clear:
            q.set("album", None)
            log("已清除本機相簿設定")
        elif args.name:
            q.set("album", args.name)
            log(f"之後的照片進相簿：{args.name}")
        else:
            log(q.get("album") or cfg["device"]["album"] or "（用拍攝日期）")
    elif args.cmd == "retry":
        n = q.con.execute("UPDATE items SET status='pending', next_try=0, attempts=0 WHERE status='failed'").rowcount
        log(f"已重新排入 {n} 張")
    elif args.cmd == "send":
        for f in args.files:
            p = Path(f).resolve()
            st = p.stat()
            key = f"{cfg['device']['name']}||{p}|{st.st_size}|{int(st.st_mtime)}"
            uid = hashlib.sha256(key.encode()).hexdigest()[:40]
            album = q.get("album") or cfg["device"]["album"] or dt.date.fromtimestamp(st.st_mtime).strftime("%Y_%m_%d")
            q.add(uid, str(p), p.name, st.st_size, st.st_mtime, album)
            log(f"＋ {p.name} → {album}（agent 跑起來就會傳）")
    elif args.cmd == "test":
        a = Agent.__new__(Agent)
        a.cfg, a.q, a.http = cfg, q, requests.Session()
        a.http.headers["Authorization"] = f"Bearer {cfg['server']['token']}"
        a.timeout, a.last_beat, a.last_error, a.started, a.remote_album, a.chunk, a.source = 30, 0, "", time.time(), None, 1 << 20, None
        a.paused = False
        data = a.heartbeat(force=True)
        log("OK：" + str(data) if data else "失敗")


if __name__ == "__main__":
    main()
