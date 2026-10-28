#!/usr/bin/env python3
"""
SnapPipe worker — 處理端（Meta AI 版：Mac、Linux、伺服器本機都能跑）

  伺服器佇列 ─認領─▶ 下載原圖 ─▶ 湊成連拍組 ─▶ 分析器（Meta Model API / 遠端 HTTP / none）
                                                   ─▶ 回寫星等、圖說、AI 精選（＋換上寫好 IPTC 的 JPG）
                                   └▶ 名單比對到的球員 ─▶ 整本相簿「依球員」分組
                                   └▶ 複製到 NAS

worker 主動向伺服器拉工作（HTTP），不用開 port、不用固定 IP，在家或經 VPN 都一樣。
同一台伺服器可以有好幾個 worker。分析在執行緒裡平行跑（META_CONCURRENCY），等 API 時不會卡住認領新照片。

用法（在 repo 的 worker/ 資料夾）：
  ./worker.sh                     常駐（Linux 可用 worker/snappipe-worker.service 開機自動跑）
  ./worker.sh --once              把目前佇列處理完就結束
  ./worker.sh --status            看伺服器的佇列與裝置狀態（需要 ADMIN_TOKEN）
  ./worker.sh --set-album cage-a 2026_10_30_CWT    指定某台 Pi 之後的照片進哪本相簿
  ./worker.sh --live off | on     即時上傳總開關（關掉：Pi 暫停、監看頁關閉；返圖頁照常）
  （SERVER_URL 填多台時，管理指令對每台各做一次；--server <URL> 只對其中一台）
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import socket
import sqlite3
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "shared"))

from analyzers import get_analyzer  # noqa: E402

VERSION = "0.2.0-meta"


# ---------- 設定 ----------

def load_env(path: Path) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    if os.environ.get("META_API_KEY"):            # 金鑰也可以用環境變數帶（和測試腳本同一個名稱）
        env["META_API_KEY"] = os.environ["META_API_KEY"]
    env.update({k[3:]: v for k, v in os.environ.items() if k.startswith("SP_")})   # SP_SERVER_URL 可覆寫
    return env


ENV = load_env(Path(os.environ.get("SP_ENV_FILE", HERE / ".env")))
cfg = lambda k, d="": ENV.get(k, d)


def log(msg=""):
    print(f"{dt.datetime.now():%H:%M:%S} {msg}", flush=True)


# ---------- 本機狀態 ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
    photo_id TEXT PRIMARY KEY,
    album TEXT NOT NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    taken_at TEXT,
    stars INTEGER,
    done_at REAL,
    nas_done INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS photos_album ON photos(album);
CREATE TABLE IF NOT EXISTS players (
    album TEXT NOT NULL, photo_id TEXT NOT NULL, key TEXT NOT NULL, label TEXT NOT NULL,
    x REAL, y REAL, w REAL, h REAL, confidence REAL,
    PRIMARY KEY (photo_id, key)
);
CREATE INDEX IF NOT EXISTS players_album ON players(album);
CREATE TABLE IF NOT EXISTS albums (
    name TEXT PRIMARY KEY, people_dirty INTEGER NOT NULL DEFAULT 0, last_people REAL
);
"""


def servers() -> list:
    """SERVER_URL 可以是多台（逗號分隔）：同一個 worker 服務所有返圖站。"""
    out = [u.strip().rstrip("/") for u in cfg("SERVER_URL").split(",") if u.strip()]
    if not out:
        sys.exit(f"請在 {HERE / '.env'} 設定 SERVER_URL（伺服器安裝完印出的網址，多台用逗號分隔）")
    return out


def server_tag(url: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", url.split("://", 1)[-1])


def session(token_key: str) -> requests.Session:
    """區網直連時伺服器不用 token；有設就帶上（外面經 VPN 連回來）。"""
    s = requests.Session()
    s.headers["User-Agent"] = f"snappipe-worker/{VERSION}"
    tok = cfg(token_key) or cfg("WORKER_TOKEN")
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"
    return s


class Worker:
    def __init__(self, server: str, analyzer, pool, multi: bool = False):
        self.server = server
        self.tag = f"[{server_tag(server)}] " if multi else ""
        self.name = cfg("WORKER_NAME") or socket.gethostname().split(".")[0]
        self.http = session("WORKER_TOKEN")
        base = Path(cfg("WORK_DIR", "~/SnapPipeWorker")).expanduser()
        self.work = base / server_tag(server) if multi else base   # 每台伺服器各自的狀態與下載目錄
        self.work.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.work / "state.db")
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        self.claim_max = int(cfg("CLAIM_MAX", "16"))
        self.upload_tagged = cfg("UPLOAD_TAGGED_JPG", "1") == "1"
        self.analyzer = analyzer
        self.pool = pool
        # 連拍組：同一本相簿、同一台相機，拍攝間隔 ≤ BURST_GAP_SEC 的照片湊成一組
        self.bursts_on = getattr(analyzer, "wants_bursts", False)
        self.gap = float(cfg("BURST_GAP_SEC", "0.5"))
        self.idle = float(cfg("BURST_IDLE_SEC", "1.5"))
        self.burst_max = max(1, min(int(cfg("BURST_MAX", "40")), 40))
        self.buffer = {}       # (album, 相機) → [(path, job, 收到的時間)]
        self.running = {}      # future → [(path, job)]
        self.groups_on = cfg("PLAYER_GROUPS", "1") == "1"
        self.nas = None
        self.nas_err = ""
        self.last_activity = time.time()

    # ---- 伺服器 ----

    def api(self, method, path, **kw):
        kw.setdefault("timeout", 120)
        r = self.http.request(method, f"{self.server}{path}", **kw)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text[:200]
            raise requests.HTTPError(f"{method} {path} → {r.status_code}：{detail}", response=r)
        return r

    def claim(self, n: int):
        return self.api("POST", "/api/jobs/claim", json={"worker": self.name, "max": n,
                                                          "kinds": ["analyze", "backup_raw"]}).json()["jobs"]

    def heartbeat(self, job):
        try:
            self.api("POST", f"/api/jobs/{job['id']}/heartbeat", timeout=30)
        except requests.RequestException:
            pass

    # ---- 依球員分組（取代人臉分組：身分來自球衣號碼 + 名單，不做人臉辨識） ----

    def store_players(self, job, players):
        album, pid = job["album"], job["photo_id"]
        self.con.execute("DELETE FROM players WHERE photo_id=?", (pid,))
        for p in players:
            box = tuple(p.box) if p.box else (None,) * 4
            self.con.execute("INSERT OR REPLACE INTO players (album, photo_id, key, label, x, y, w, h, confidence) "
                             "VALUES (?,?,?,?,?,?,?,?,?)", (album, pid, p.key, p.label, *box, p.confidence))
        self.con.execute("INSERT INTO albums (name, people_dirty) VALUES (?,1) ON CONFLICT(name) DO UPDATE SET people_dirty=1",
                         (album,))

    def push_people(self, album: str):
        """整本相簿：每位球員出現在哪幾張、代表照（信心高、框大的那張），送給返圖站的「依人物」。"""
        people = {}
        for r in self.con.execute("SELECT * FROM players WHERE album=?", (album,)):
            p = people.setdefault(r["key"], {"label": r["label"], "photos": [], "cover": None, "_q": -1.0})
            p["photos"].append(r["photo_id"])
            if r["x"] is not None:
                q = (r["confidence"] or 0) + min((r["w"] or 0) * (r["h"] or 0) * 4, 1.0)
                if q > p["_q"]:
                    p["_q"] = q
                    p["cover"] = {"photo_id": r["photo_id"], "box": [r["x"], r["y"], r["w"], r["h"]]}
        min_photos = int(cfg("PLAYER_MIN_PHOTOS", "1"))
        keep = sorted((p for p in people.values() if len(p["photos"]) >= min_photos), key=lambda p: -len(p["photos"]))
        payload = [{"photos": p["photos"], "cover": p["cover"] or {"photo_id": p["photos"][0], "box": [0, 0, 1, 1]},
                    "label": p["label"]} for p in keep]
        self.api("PUT", f"/api/worker/albums/{album}/people", json={"people": payload})
        self.con.execute("UPDATE albums SET people_dirty=0, last_people=? WHERE name=?", (time.time(), album))
        self.con.commit()
        log(f"  {self.tag}球員分組 {album}：{len(payload)} 位")

    def flush_people(self, force=False):
        if not self.groups_on:
            return
        idle = time.time() - self.last_activity
        for r in self.con.execute("SELECT * FROM albums WHERE people_dirty=1").fetchall():
            since = time.time() - (r["last_people"] or 0)
            if force or idle >= 10 or since >= 60:   # 連拍空檔、或每分鐘至少一次
                try:
                    self.push_people(r["name"])
                except Exception as e:
                    log(f"  ⚠ 球員分組 {r['name']}：{e}")

    # ---- NAS ----

    def nas_root(self):
        if self.nas is None and cfg("NAS_SMB"):
            from nas import nas_root
            try:
                self.nas = nas_root(cfg("NAS_SMB"), cfg("NAS_MOUNT", "~/mnt/SnapPipeNAS"))
            except RuntimeError as e:
                if str(e) != self.nas_err:
                    log(f"  ⚠ NAS：{e}")
                    self.nas_err = str(e)
        return self.nas

    def to_nas(self, job, path: Path):
        root = self.nas_root()
        if not root:
            return False
        sub = job.get("camera") or job.get("device") or "live"
        dst = root / job["album"] / "live" / sub / path.name
        if not (dst.exists() and dst.stat().st_size == path.stat().st_size):
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".part")
            shutil.copy2(path, tmp)
            tmp.replace(dst)
        update_manifest(dst.parent, path.name, {"photo_id": job["photo_id"], "kind": "jpeg"})
        return True

    # ---- 一件工作 ----

    def local_path(self, job) -> Path:
        sub = job.get("camera") or job.get("device") or "live"
        p = self.work / job["album"] / sub / job["filename"]
        row = self.con.execute("SELECT photo_id FROM photos WHERE path=?", (str(p),)).fetchone()
        if row and row["photo_id"] != job["photo_id"]:   # 同一台相機不同張同檔名（檔名編號繞回來了）
            p = p.with_name(f"{p.stem}_{job['photo_id'][:8]}{p.suffix}")
        return p

    def download(self, job, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and sha256_file(path) == job["sha256"]:
            return
        tmp = path.with_name(path.name + ".part")
        with self.api("GET", job["file_url"], stream=True, timeout=300) as r, open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        if sha256_file(tmp) != job["sha256"]:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("下載的檔案 SHA-256 不符")
        tmp.replace(path)

    def fail(self, job, err, retry=True):
        log(f"  {self.tag}⚠ {job['album']}/{job.get('filename') or job.get('raw_name')}：{err}")
        try:
            self.api("POST", f"/api/jobs/{job['id']}/fail", json={"error": str(err)[:500], "retry": retry})
        except requests.RequestException as e2:
            log(f"    （回報失敗也失敗：{e2}）")

    def backup_raw(self, job) -> bool:
        """RAW 到了：下載、抄到 NAS（和 JPG 同一個資料夾），本機不留。"""
        t0 = time.time()
        try:
            root = self.nas_root()
            if root:
                sub = job.get("camera") or job.get("device") or "live"
                dst = root / job["album"] / "live" / sub / job["raw_name"]
                if not (dst.exists() and dst.stat().st_size == job["raw_bytes"]):
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dst.with_name(dst.name + ".part")
                    with self.api("GET", job["raw_url"], stream=True, timeout=600) as r, open(tmp, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                    if sha256_file(tmp) != job["raw_sha256"]:
                        tmp.unlink(missing_ok=True)
                        raise RuntimeError("下載的 RAW SHA-256 不符")
                    tmp.replace(dst)
                update_manifest(dst.parent, job["raw_name"], {"photo_id": job["photo_id"], "kind": "raw", "sha": job["raw_sha256"]})
            self.api("POST", f"/api/jobs/{job['id']}/result", json={"processor": self.name, "extra": {"nas": bool(root)}})
            log(f"  {self.tag}✓ RAW {job['album']}/{job['raw_name']}  {(job['raw_bytes'] or 0) / 1e6:.0f} MB"
                + ("  NAS" if root else "  （沒設 NAS，只留在伺服器）") + f"  {time.time() - t0:.1f}s")
            return True
        except Exception as e:
            self.fail(job, e)
            return False

    def receive(self, job):
        """認領到的 analyze 工作：下載原圖，放進連拍緩衝區。"""
        path = self.local_path(job)
        try:
            self.download(job, path)
        except Exception as e:
            self.fail(job, e)
            return
        key = (job["album"], job.get("camera") or job.get("device") or "?")
        self.buffer.setdefault(key, []).append((path, job, time.time()))

    def ready_bursts(self, flush=False) -> list:
        """從緩衝區切出已經結束的連拍組。

        依拍攝時間排序後，間隔 > BURST_GAP_SEC 就斷成兩組。一組算「結束」的條件：
          後面已經有同一台相機更晚的照片（間隔夠大）、或 BURST_IDLE_SEC 秒沒有新照片進來、或滿 BURST_MAX 張。
        """
        out = []
        now = time.time()
        for key, items in list(self.buffer.items()):
            if not self.bursts_on:
                out += [[(p, j)] for p, j, _ in items]
                del self.buffer[key]
                continue
            items.sort(key=lambda x: (x[1].get("taken_at") or "", x[1]["filename"]))
            groups, cur, prev = [], [], None
            for it in items:
                t = parse_time(it[1].get("taken_at"))
                if cur and (t is None or prev is None or (t - prev).total_seconds() > self.gap or len(cur) >= self.burst_max):
                    groups.append(cur)
                    cur = []
                cur.append(it)
                prev = t
            groups.append(cur)
            idle = now - max(it[2] for it in items) >= self.idle
            keep = []
            for n, g in enumerate(groups):
                last = n == len(groups) - 1
                if flush or not last or idle or len(g) >= self.burst_max:
                    out.append([(p, j) for p, j, _ in g])
                else:
                    keep += g
            if keep:
                self.buffer[key] = keep
            else:
                del self.buffer[key]
        return out

    def dispatch(self, bursts):
        for b in bursts:
            fut = self.pool.submit(self.analyzer.analyze_burst, b)
            self.running[fut] = b

    def collect(self) -> int:
        """收回已經分析完的連拍組，回寫伺服器。"""
        done = [f for f in self.running if f.done()]
        for fut in done:
            items = self.running.pop(fut)
            try:
                results = fut.result()
            except Exception as e:
                retry = getattr(e, "retry", True)
                for _, job in items:
                    self.fail(job, e, retry)
                continue
            picks = []
            for (path, job), res in zip(items, results):
                if self.finish(job, path, res) and res.ai.get("pick"):
                    picks.append(job["filename"])
            if len(items) > 1 or picks:
                log(f"  {self.tag}連拍 {len(items)} 張 → 精選 {', '.join(picks) or '—'}"
                    f"  {results[0].ai.get('moment_label', '')}  {results[0].extra.get('burst_sec', '')}s")
            self.last_activity = time.time()
        return len(done)

    def finish(self, job, path: Path, res) -> bool:
        t0 = time.time()
        try:
            if res.file_modified and self.upload_tagged:
                with open(path, "rb") as f:
                    self.api("PUT", f"/api/jobs/{job['id']}/file", files={"file": (path.name, f, "image/jpeg")},
                             data={"meta": json.dumps({"sha256": sha256_file(path)})}, timeout=300)
            self.api("POST", f"/api/jobs/{job['id']}/result",
                     json={"stars": res.stars, "aesthetic": res.aesthetic, "tags": res.tags, "taken_at": res.taken_at,
                           "camera": res.camera, "headline": res.headline, "caption": res.caption, "ai": res.ai,
                           "processor": self.analyzer.name, "extra": res.extra})
            self.con.execute("""INSERT INTO photos (photo_id, album, filename, path, taken_at, stars, done_at)
                                VALUES (?,?,?,?,?,?,?) ON CONFLICT(photo_id) DO UPDATE SET
                                path=excluded.path, taken_at=excluded.taken_at, stars=excluded.stars, done_at=excluded.done_at""",
                             (job["photo_id"], job["album"], job["filename"], str(path),
                              res.taken_at or job.get("taken_at"), res.stars, time.time()))
            if self.groups_on:
                self.store_players(job, res.players)
            nas = self.to_nas(job, path)
            self.con.execute("UPDATE photos SET nas_done=? WHERE photo_id=?", (int(nas), job["photo_id"]))
            self.con.commit()
            mark = "◆" if res.ai.get("pick") else "·"
            log(f"  {self.tag}{mark} {job['album']}/{job['filename']}  ★{res.stars or '-'}"
                + (f"  {res.aesthetic:.1f}" if isinstance(res.aesthetic, (int, float)) else "")
                + (f"  「{res.caption[:40]}…」" if res.caption else "")
                + ("  ⚠需確認" if res.ai.get("needs_review") else "") + ("  NAS" if nas else "")
                + f"  {time.time() - t0:.1f}s")
            return True
        except Exception as e:
            self.fail(job, e)
            return False

    def step(self) -> int:
        """認領、湊組、送分析、收結果；回傳這一輪有動作的件數。連不上伺服器會退避，不會丟例外。"""
        n = self.collect()
        now = time.time()
        if now >= getattr(self, "_retry_at", 0):
            # 正在跑的組數有上限，避免一口氣認領太多、租約在排隊時就過期
            room = self.claim_max - sum(len(b) for b in self.running.values()) - sum(len(v) for v in self.buffer.values())
            if room > 0:
                try:
                    jobs = self.claim(min(room, 32))
                    self._backoff = 1
                except requests.RequestException as e:
                    b = getattr(self, "_backoff", 1)
                    log(f"{self.tag}{net_error(e)}（{b}s 後再試）")
                    self._retry_at, self._backoff = now + b, min(b * 2, 60)
                    jobs = []
                for j in jobs:
                    if j["kind"] == "backup_raw":
                        self.backup_raw(j)
                    else:
                        self.receive(j)
                n += len(jobs)
        bursts = self.ready_bursts()
        self.dispatch(bursts)
        for fut, items in self.running.items():   # 分析很久（API 慢）時延長租約
            if not fut.done() and time.time() - getattr(fut, "_hb", now) > 240:
                for _, j in items:
                    self.heartbeat(j)
                fut._hb = time.time()
            elif not hasattr(fut, "_hb"):
                fut._hb = now
        self.flush_people()
        return n + len(bursts)

    def busy(self) -> bool:
        return bool(self.buffer or self.running)


def run(once=False):
    import concurrent.futures as cf
    analyzer = get_analyzer(cfg("ANALYZER", "meta_ai"), ENV, log)
    pool = cf.ThreadPoolExecutor(max_workers=int(cfg("META_CONCURRENCY", "4")))
    urls = servers()
    workers = [Worker(u, analyzer, pool, multi=len(urls) > 1) for u in urls]
    w0 = workers[0]
    log(f"worker {w0.name}  分析器 {analyzer.name}  連拍分組 {'開' if w0.bursts_on else '關'}"
        f"  球員分組 {'開' if w0.groups_on else '關'}  → {', '.join(urls)}"
        + ("" if cfg("WORKER_TOKEN") else "（區網免 token）"))
    poll = float(cfg("POLL_SEC", "2"))
    while True:
        n = sum(w.step() for w in workers)
        if any(w.busy() for w in workers):
            time.sleep(0.2)          # 有照片在湊組或分析中：短間隔回來收結果
            continue
        if n:
            continue
        if once:
            for w in workers:
                w.flush_people(force=True)
            log("佇列已清空")
            pool.shutdown()
            return
        time.sleep(poll)


# ---------- 管理（用返圖站的上傳 token） ----------

LOCAL_NET_HINT = ("連不到伺服器（errno 65 No route to host）：在 Mac 上跑的話，很可能是 macOS 的「本機網路」權限擋住了。\n"
                  "  系統設定 → 隱私權與安全性 → 本機網路，打開你用來執行的 App（終端機 / iTerm…）與 Python；\n"
                  "  清單裡沒有的話，從該 App 再跑一次會跳出詢問。允許後 worker 會自己重連，不用重啟。")


def net_error(e) -> str:
    return LOCAL_NET_HINT if "Errno 65" in str(e) or "No route to host" in str(e) else f"連不到伺服器：{e}"


def admin_call(fn, only: str | None = None):
    """管理指令：對每一台伺服器（或 --server 指定的那台）各做一次；連線錯誤印提示而不是整串 traceback。"""
    urls = [u for u in servers() if not only or only.rstrip("/") in u]
    if not urls:
        sys.exit(f"SERVER_URL 裡沒有 {only}")
    for u in urls:
        if len(urls) > 1:
            log(f"── {u}")
        try:
            fn(session("ADMIN_TOKEN"), u)
        except requests.RequestException as e:
            log(net_error(e))


def show_status(s, server):
    d = s.get(f"{server}/api/live/status", timeout=30)
    if not d.ok:
        log(f"{d.status_code} {d.text[:200]}"); return
    d = d.json()
    log(f"即時上傳：{'開啟' if d.get('enabled', True) else '關閉（Pi 暫停、監看頁關閉）'}  worker 驗證：{d.get('tokens', {}).get('worker')}")
    log(f"佇列：{d['jobs']}  上傳中 {d['uploads_in_progress']}")
    for dev in d["devices"]:
        ago = f"{int(time.time() - dev['last_seen'])}s 前" if dev["last_seen"] else "沒出現過"
        st = dev["stats"]
        log(f"  裝置 {dev['name']:<12} 相簿 {dev['active_album'] or '（Pi 自己決定）':<24} {ago}  已傳 {dev['uploads']}"
            f"  待傳 {st.get('pending', '?')}  電量 {st.get('battery', '?')}  {st.get('last_error', '')[:60]}")
    for a in d["albums"]:
        log(f"  相簿 {a['slug']:<28} {a['n']} 張（即時 {a['live'] or 0}，待分析 {a['pending'] or 0}）"
            f"  返圖 /a/{a['share_key']}  即時監看 /live/{a['live_key']}")
    for j in d["dead"]:
        log(f"  ✗ 工作 {j['id']} {j['album']}/{j['filename']}：{j['error']}")


def set_live(on: bool):
    def go(s, server):
        r = s.put(f"{server}/api/live/switch", json={"enabled": on}, timeout=30)
        log(("即時上傳已開啟" if on else "即時上傳已關閉：Pi 暫停、監看頁關閉；返圖頁照常") if r.ok else f"{r.status_code} {r.text[:200]}")
    return go


def set_album(device: str, album: str | None):
    def go(s, server):
        r = s.put(f"{server}/api/live/devices/{device}", json={"album": album}, timeout=30)
        log(r.json() if r.ok else f"{r.status_code} {r.text[:200]}")
    return go


# ---------- 小工具 ----------

MANIFEST = ".snappipe-live.json"


def update_manifest(folder: Path, name: str, info: dict):
    """NAS 的 live/<相機>/ 資料夾放一份清單：檔名 → 原始檔 SHA-256。回家插卡 ingest 備份完會比對，
    記憶卡上已經有的現場副本就刪掉，群暉相簿才不會同一張出現兩次。"""
    mf = folder / MANIFEST
    try:
        data = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else {}
    except ValueError:
        data = {}
    data[name] = info
    tmp = mf.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(mf)

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_time(v):
    try:
        return dt.datetime.fromisoformat(v) if v else None
    except ValueError:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true", help="處理完目前佇列就結束")
    ap.add_argument("--status", action="store_true", help="伺服器佇列與裝置狀態")
    ap.add_argument("--set-album", nargs=2, metavar=("DEVICE", "ALBUM"), help="指定某台 Pi 之後的照片進哪本相簿（ALBUM 填 - 清除）")
    ap.add_argument("--live", choices=["on", "off"], help="即時上傳總開關（同伺服器的 snappipe-live）")
    ap.add_argument("--server", metavar="URL", help="管理指令只對 SERVER_URL 裡的這一台（預設全部）")
    args = ap.parse_args()
    if args.status:
        return admin_call(show_status, args.server)
    if args.live:
        return admin_call(set_live(args.live == "on"), args.server)
    if args.set_album:
        dev, album = args.set_album
        return admin_call(set_album(dev, None if album == "-" else album), args.server)
    try:
        run(once=args.once)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
