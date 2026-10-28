"""
SnapPipe 即時路徑 — 伺服器端

相機拍完 → 樹莓派 snap-agent 立刻上傳 → 這裡入庫、排進工作佇列 → 處理端（worker 呼叫 Meta Model API）
認領工作、下載原圖、分析完回寫 → 返圖頁即時更新。

三種身分、三組 token：
  裝置（Pi）        SNAPPIPE_DEVICE_TOKENS   只能上傳與心跳；每台一組，遺失可個別撤銷；不限來源網段（伺服器本身在哪裡才是重點）
  處理端（worker）  SNAPPIPE_WORKER_TOKEN    認領工作、下載原圖、回寫結果、人物分組、管理 API。
                                           留空 = 區網信任模式：區網直連免 token（家裡一個 worker 服務所有返圖站）；
                                           設了 = 要 token（讓外面的 worker 經 VPN / 反向代理連回來）
  管理（插卡 ingest）SNAPPIPE_UPLOAD_TOKEN    插卡上傳（限區網 + token）；也可用來叫管理 API

總開關：伺服器上 `snappipe-live off`（或 PUT /api/live/switch）關掉即時上傳，Pi 會暫停、即時監看頁關閉，
返圖頁與插卡上傳照常；狀態存在資料庫，所有 uvicorn worker 立即生效，不用重啟。

上傳協定（可續傳、冪等；Pi 端只記「哪些還沒傳完」，不需要落地存檔）：
  HEAD /api/uploads/{id}                    → Upload-Offset: 已收到的 byte 數（沒看過這個 id 就 404）
  PUT  /api/uploads/{id}  Content-Range: bytes S-E/T   body = 這一段的內容
       第一段要帶 X-SnapPipe-Album / X-SnapPipe-Filename；S 必須等於已收到的 byte 數，否則回 409 + Upload-Offset
       收滿 T 個 byte 就入庫：SHA-256 去重、產生縮圖、排進佇列，回 {"complete": true, "photo_id": …}
  上傳 id 由 Pi 自己決定（機身序號 + 卡上路徑 + 大小 + 時間的 hash），重開機、斷線後重送都接得上。

工作協定（處理端主動來拉，不用對外開 port；任何能講 HTTP 的程式都能當處理端）：
  POST /api/jobs/claim {"worker": "...", "max": 4}  → 租用幾件工作（租約到期沒回報就會自動釋放給別人）
  GET  /api/jobs/{id}/file                           → 原始 JPG
  PUT  /api/jobs/{id}/file  (multipart file + meta)   → 選用：把寫好 IPTC/XMP 的 JPG 換上去（photo_id 不變）
  POST /api/jobs/{id}/result {"stars", "aesthetic", "tags", …}  → 完成
  POST /api/jobs/{id}/fail   {"error", "retry": true}            → 失敗（退避後重排；超過次數就標 dead）
  POST /api/jobs/{id}/heartbeat                                  → 延長租約
  PUT  /api/worker/albums/{slug}/people                           → 整本相簿的人物分組（同返圖站的格式）
"""

import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from PIL import Image
from pydantic import BaseModel

from . import main as core

router = APIRouter()

WORKER_TOKEN = os.environ.get("SNAPPIPE_WORKER_TOKEN", "")
LEASE_SEC = int(os.environ.get("SNAPPIPE_JOB_LEASE", "600"))
MAX_ATTEMPTS = int(os.environ.get("SNAPPIPE_JOB_MAX_ATTEMPTS", "5"))
UPLOAD_MAX = int(os.environ.get("SNAPPIPE_UPLOAD_MAX_MB", "256")) << 20   # RAW（例 α1 無損壓縮 ~100MB）也走這個端口
CHUNK_MAX = 16 << 20   # 單一 PUT 最多收這麼多（Pi 端預設 1MB 一段）
MIN_FREE = int(os.environ.get("SNAPPIPE_MIN_FREE_GB", "2")) * (1 << 30)   # 磁碟剩不到這麼多就拒收（507）
MAX_INFLIGHT = int(os.environ.get("SNAPPIPE_MAX_INFLIGHT", "16"))         # 每台裝置同時進行中的上傳數
STALE_UPLOAD_SEC = 48 * 3600                                               # 沒傳完超過這麼久：清掉暫存
AUTH_FAILS, AUTH_BAN_SEC = 20, 600                                         # 同一 IP 連續錯 token 幾次後封多久

# 只收相機會產生的檔案：副檔名白名單 + 檔頭特徵（不信任副檔名）
JPEG_EXT = {".jpg", ".jpeg"}
RAW_EXT = {".arw", ".cr2", ".cr3", ".nef", ".nrw", ".raf", ".orf", ".rw2", ".dng", ".pef"}
TIFF_MAGIC = (b"II*\x00", b"MM\x00*")
RAW_MAGIC = {
    ".arw": TIFF_MAGIC, ".nef": TIFF_MAGIC, ".nrw": TIFF_MAGIC, ".dng": TIFF_MAGIC, ".cr2": TIFF_MAGIC,
    ".pef": TIFF_MAGIC, ".orf": (b"IIRO", b"MMOR", b"IIRS"), ".rw2": (b"IIU\x00",), ".raf": (b"FUJIFILMCCD-RAW",),
    ".cr3": None,   # ISO BMFF：第 4 byte 起是 "ftypcrx "
}
SAFE_NAME_RE = re.compile(r"[^\w.\-]+")

UPLOAD_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")
NAME_RE = re.compile(r"^[\w.\-]{1,40}$")
RANGE_RE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")
JOB_KINDS = ("analyze", "backup_raw")   # backup_raw：RAW 到了，worker 抄一份到 NAS


def safe_filename(name: str) -> str:
    """只留文字、數字、. _ -（相機檔名本來就是這樣）；其他字元換成 _，避免奇怪字元進到檔名與 NAS。"""
    name = SAFE_NAME_RE.sub("_", Path(name).name).strip("._")
    return name[:120] if name else ""


def file_kind(name: str) -> Optional[str]:
    ext = Path(name).suffix.lower()
    return "jpeg" if ext in JPEG_EXT else "raw" if ext in RAW_EXT else None


def check_raw(tmp: Path, name: str) -> str:
    """RAW 不解碼（伺服器不裝 rawpy），只核對檔頭特徵；回傳副檔名。"""
    ext = Path(name).suffix.lower()
    with open(tmp, "rb") as f:
        head = f.read(16)
    magic = RAW_MAGIC.get(ext)
    ok = (head[4:12] == b"ftypcrx ") if ext == ".cr3" else any(head.startswith(m) for m in magic)
    if not ok:
        raise ValueError(f"{ext} 檔頭不符")
    return ext


_auth_fails: dict = {}   # ip → [次數, 最後一次時間]（每個 uvicorn worker 各自一份，已足夠擋亂試）


def _auth_check_ban(ip: str):
    rec = _auth_fails.get(ip)
    if rec and rec[0] >= AUTH_FAILS and time.time() - rec[1] < AUTH_BAN_SEC:
        raise HTTPException(429, "token 錯太多次，暫時封鎖", headers={"Retry-After": str(AUTH_BAN_SEC)})


def _auth_failed(ip: str):
    rec = _auth_fails.setdefault(ip, [0, 0.0])
    if time.time() - rec[1] > AUTH_BAN_SEC:
        rec[0] = 0
    rec[0] += 1
    rec[1] = time.time()
    if len(_auth_fails) > 10000:   # 不讓這張表無限長大
        _auth_fails.clear()


def _nets(env: str):
    v = os.environ.get(env, "").strip()
    return [ipaddress.ip_network(n.strip(), strict=False) for n in v.split(",") if n.strip()] if v else None


# 裝置與處理端通常從 WireGuard / Tailscale 或反向代理進來，預設不限網段，只靠 token；要限就設這兩個
DEVICE_NETS = _nets("SNAPPIPE_DEVICE_NETS")
WORKER_NETS = _nets("SNAPPIPE_WORKER_NETS")


def _device_tokens() -> dict:
    """SNAPPIPE_DEVICE_TOKENS="cage-a:token1,cage-b:token2"（逗號、空白或換行分隔）→ {token: 裝置名}"""
    out = {}
    for item in re.split(r"[,\s]+", os.environ.get("SNAPPIPE_DEVICE_TOKENS", "").strip()):
        if ":" in item:
            name, tok = item.split(":", 1)
            if NAME_RE.match(name) and tok:
                out[tok] = name
    return out


DEVICE_TOKENS = _device_tokens()


# ---------- 資料表 ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    name TEXT PRIMARY KEY,
    active_album TEXT,            -- 管理端指定：這台 Pi 現在拍的要進哪本相簿（Pi 心跳時會拿到）
    last_seen REAL,
    last_ip TEXT,
    stats TEXT NOT NULL DEFAULT '{}',   -- Pi 回報的狀態（待傳張數、電量…），只拿來顯示
    uploads INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    device TEXT NOT NULL,
    album TEXT NOT NULL,
    filename TEXT NOT NULL,
    total INTEGER NOT NULL,
    received INTEGER NOT NULL DEFAULT 0,
    camera TEXT,
    taken_at TEXT,
    album_auto INTEGER NOT NULL DEFAULT 0,   -- Pi 沒指定相簿：入庫時改用 EXIF 拍攝日期當相簿名
    kind TEXT NOT NULL DEFAULT 'jpeg',       -- jpeg / raw
    started_at REAL NOT NULL,
    finished_at REAL,
    photo_id TEXT
);
CREATE TABLE IF NOT EXISTS raw_pending (     -- RAW 比 JPG 先到：先收著，JPG 入庫時再配對
    id INTEGER PRIMARY KEY, device TEXT NOT NULL, album TEXT, stem TEXT NOT NULL,
    sha256 TEXT NOT NULL, filename TEXT NOT NULL, bytes INTEGER NOT NULL, created_at REAL NOT NULL,
    taken_at TEXT, camera TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'analyze',
    photo INTEGER NOT NULL REFERENCES photos(id),
    album_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued / leased / done / dead
    priority INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    worker TEXT,
    lease_until REAL,
    not_before REAL,              -- 失敗退避：這個時間之前不派
    error TEXT,
    result TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE (photo, kind)
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, priority DESC, created_at);
CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""

with core.db() as _con:
    _con.executescript(SCHEMA)
    _rp = {r["name"] for r in _con.execute("PRAGMA table_info(raw_pending)")}
    if "taken_at" not in _rp:
        _con.execute("ALTER TABLE raw_pending ADD COLUMN taken_at TEXT")
    if "camera" not in _rp:
        _con.execute("ALTER TABLE raw_pending ADD COLUMN camera TEXT")
(core.DATA_DIR / "tmp" / "uploads").mkdir(parents=True, exist_ok=True)


def repair_pending_raws():
    """啟動時把還沒配對的 RAW 再配一次（補讀拍攝時間；舊版只會比檔名）。"""
    with core.db() as con:
        for r in con.execute("SELECT * FROM raw_pending").fetchall():
            taken_at = r["taken_at"] or tiff_taken_at(core.raw_path(r["sha256"], r["filename"]))
            if taken_at and not r["taken_at"]:
                con.execute("UPDATE raw_pending SET taken_at=? WHERE id=?", (taken_at, r["id"]))
            p = find_jpg_for_raw(con, r["device"], r["filename"], r["album"], taken_at, r["camera"])
            if p:
                attach_raw(con, p["id"], p["album_id"], r["sha256"], r["filename"], r["bytes"])
                con.execute("UPDATE albums SET updated_at=? WHERE id=?", (time.time(), p["album_id"]))
                con.execute("DELETE FROM raw_pending WHERE id=?", (r["id"],))


# ---------- 總開關 ----------

def setting(con, k: str, default: str = "") -> str:
    r = con.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def set_setting(con, k: str, v: str):
    con.execute("INSERT INTO settings (k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


# ---------- 固定連結：永遠導到最新的相簿（安裝完就能先給，不用等第一張照片）----------
# 返圖與即時監看各一組隨機碼：把返圖連結給客人，也推不出即時監看的網址

SITE_KEYS = {"album": "site_album_key", "live": "site_live_key"}


def site_key(con, kind: str) -> str:
    k = setting(con, SITE_KEYS[kind])
    if not k:
        k = secrets.token_urlsafe(12)
        set_setting(con, SITE_KEYS[kind], k)
    return k


def site_links(con) -> dict:
    return {kind: f"/go/{kind}/{site_key(con, kind)}" for kind in SITE_KEYS}


WAIT_PAGE = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="10">
<meta name="robots" content="noindex"><title>{site}</title>
<style>body{{font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:90vh;margin:0;
color:#333;background:#fafafa}}@media(prefers-color-scheme:dark){{body{{color:#ddd;background:#111}}}}
div{{text-align:center;padding:24px}}p{{opacity:.7}}</style></head>
<body><div><h2>{site}</h2><p>還沒有相簿：第一張照片傳進來就會出現在這裡（每 10 秒自動重新整理）</p>
<p>No album yet — this page refreshes automatically.</p></div></body></html>"""


@router.api_route("/go/{kind}/{key}", methods=["GET", "HEAD"])
def go_latest(kind: str, key: str):
    """/go/album/<碼> → 最新相簿的返圖頁；/go/live/<碼> → 正在進照片的相簿的即時監看頁。"""
    if kind not in SITE_KEYS:
        raise HTTPException(404)
    with core.db() as con:
        if not hmac.compare_digest(key.encode(), site_key(con, kind).encode()):
            raise HTTPException(404)
        order = "created_at DESC" if kind == "album" else "COALESCE(updated_at, created_at) DESC"
        a = con.execute(f"SELECT share_key, live_key FROM albums ORDER BY {order} LIMIT 1").fetchone()
    if not a:
        site = core.SITE_NAME.replace("&", "&amp;").replace("<", "&lt;")
        return HTMLResponse(WAIT_PAGE.format(site=site), headers={"Cache-Control": "no-store"})
    url = core.share_url(a["share_key"]) if kind == "album" else core.live_url(a["live_key"])
    return RedirectResponse(url, status_code=302, headers={"Cache-Control": "no-store"})


def uploads_enabled(con=None) -> bool:
    if con is not None:
        return setting(con, "uploads_enabled", "1") == "1"
    with core.db() as c:
        return setting(c, "uploads_enabled", "1") == "1"


def require_live_enabled(con=None):
    if not uploads_enabled(con):
        raise HTTPException(403, "即時上傳與監看已關閉（伺服器 snappipe-live on 可重新開啟）")


# ---------- 權限 ----------

def _check_net(request: Request, nets):
    if nets is None:
        return
    try:
        ip = ipaddress.ip_address(request.client.host if request.client else "")
        ip = getattr(ip, "ipv4_mapped", None) or ip
    except ValueError:
        raise HTTPException(403, "無法辨識來源 IP")
    if not any(ip in n for n in nets):
        raise HTTPException(403, f"來源 {ip} 不在允許的網段")


def _bearer(authorization: Optional[str]) -> str:
    return (authorization or "").removeprefix("Bearer ").strip()


def require_device(request: Request, authorization: Optional[str]) -> str:
    """回傳裝置名稱。"""
    _check_net(request, DEVICE_NETS)
    if not DEVICE_TOKENS:
        raise HTTPException(500, "伺服器未設定 SNAPPIPE_DEVICE_TOKENS")
    ip = client_ip(request)
    _auth_check_ban(ip)
    given = _bearer(authorization).encode()
    for tok, name in DEVICE_TOKENS.items():
        if hmac.compare_digest(given, tok.encode()):
            _auth_fails.pop(ip, None)
            return name
    _auth_failed(ip)
    raise HTTPException(401, "裝置 token 錯誤")


def require_worker(request: Request, authorization: Optional[str]):
    """處理端身分。沒設 SNAPPIPE_WORKER_TOKEN = 區網信任模式：只接受區網直連（不經代理），不用 token。"""
    if not WORKER_TOKEN:
        if any(h in request.headers for h in core.PROXY_HEADERS):
            raise HTTPException(403, "worker 未設 token 時只接受區網直連（不經反向代理）")
        _check_net(request, WORKER_NETS or core.UPLOAD_NETS)
        return
    _check_net(request, WORKER_NETS)
    ip = client_ip(request)
    _auth_check_ban(ip)
    if not hmac.compare_digest(_bearer(authorization).encode(), WORKER_TOKEN.encode()):
        _auth_failed(ip)
        raise HTTPException(401, "worker token 錯誤")
    _auth_fails.pop(ip, None)


def require_admin(request: Request, authorization: Optional[str]):
    """管理 API（狀態、指定相簿、總開關）：返圖站的上傳 token，或 worker 的身分（區網信任模式下就是區網免 token）。"""
    try:
        core.require_uploader(request, authorization)
        return
    except HTTPException as first:
        try:
            require_worker(request, authorization)
        except HTTPException:
            raise first


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


# ---------- 裝置：心跳 ----------

@router.post("/api/devices/heartbeat")
def heartbeat(body: dict, request: Request, authorization: Optional[str] = Header(None)):
    """Pi 每隔幾秒送一次目前狀態；回傳管理端指定的相簿（沒指定就 null，Pi 用自己的設定）。"""
    name = require_device(request, authorization)
    stats = {k: v for k, v in body.items() if isinstance(v, (str, int, float, bool)) and len(str(v)) <= 200}
    with core.db() as con:
        cleanup_stale_uploads(con)
        con.execute("""INSERT INTO devices (name, last_seen, last_ip, stats) VALUES (?,?,?,?)
                       ON CONFLICT(name) DO UPDATE SET last_seen=excluded.last_seen, last_ip=excluded.last_ip,
                       stats=excluded.stats""", (name, time.time(), client_ip(request), json.dumps(stats)))
        row = con.execute("SELECT active_album FROM devices WHERE name=?", (name,)).fetchone()
        enabled = uploads_enabled(con)
    album = core.ALBUM_SLUG if core.SINGLE_ALBUM else row["active_album"]   # 一台一本：Pi 的照片都進這本
    return {"device": name, "album": album, "server_time": time.time(),
            "chunk_bytes": 1 << 20, "max_bytes": UPLOAD_MAX, "enabled": enabled}


# ---------- 裝置：可續傳上傳 ----------

def upload_tmp(upload_id: str) -> Path:
    return core.DATA_DIR / "tmp" / "uploads" / f"{upload_id}.part"


def _offset_headers(row) -> dict:
    return {"Upload-Offset": str(row["received"]), "Upload-Length": str(row["total"]),
            "Upload-Complete": "1" if row["finished_at"] else "0"}


@router.api_route("/api/uploads/{upload_id}", methods=["HEAD"])
def upload_status(upload_id: str, request: Request, authorization: Optional[str] = Header(None)):
    name = require_device(request, authorization)
    with core.db() as con:
        require_live_enabled(con)
        row = con.execute("SELECT * FROM uploads WHERE id=? AND device=?", (upload_id, name)).fetchone()
    if not row:
        raise HTTPException(404)
    return Response(status_code=200, headers=_offset_headers(row))


def exif_info(path: Path) -> dict:
    """從 JPEG 讀拍攝時間（含毫秒）與機身序號；Pi 端不用懂 EXIF。"""
    out = {}
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            ifd = ex.get_ifd(0x8769)
            v = ifd.get(0x9003) or ex.get(0x0132)
            if v and not str(v).startswith("0000"):
                t = str(v)[:19].replace(":", "-", 2).replace(" ", "T")
                sub = str(ifd.get(0x9291, "") or "")
                out["taken_at"] = t + (f".{sub[:3].ljust(3, '0')}" if sub.isdigit() else "")
            serial = ifd.get(0xA431)
            if serial:
                out["camera"] = str(serial).strip()[:40]
    except Exception:
        pass
    return out


def enqueue(con, photo_pk: int, album_id: int, kind: str = "analyze", priority: int = 0):
    now = time.time()
    con.execute("""INSERT INTO jobs (kind, photo, album_id, status, priority, created_at, updated_at)
                   VALUES (?,?,?,'queued',?,?,?)
                   ON CONFLICT(photo, kind) DO UPDATE SET status='queued', attempts=0, worker=NULL,
                     lease_until=NULL, not_before=NULL, error=NULL, priority=excluded.priority, updated_at=excluded.updated_at""",
                (kind, photo_pk, album_id, priority, now, now))


def cleanup_stale_uploads(con):
    """傳到一半、太久沒續傳的上傳：刪暫存檔與紀錄（Pi 重送時會從 0 開始）。"""
    cutoff = time.time() - STALE_UPLOAD_SEC
    for r in con.execute("SELECT id FROM uploads WHERE finished_at IS NULL AND started_at < ?", (cutoff,)).fetchall():
        upload_tmp(r["id"]).unlink(missing_ok=True)
    con.execute("DELETE FROM uploads WHERE finished_at IS NULL AND started_at < ?", (cutoff,))
    con.execute("DELETE FROM raw_pending WHERE created_at < ?", (time.time() - 7 * 86400,))


def _reject(row, tmp: Path, status: int, msg: str):
    tmp.unlink(missing_ok=True)
    with core.db() as con:
        con.execute("DELETE FROM uploads WHERE id=?", (row["id"],))
    raise HTTPException(status, msg)


def finalize_upload(row, tmp: Path) -> dict:
    """收滿了：驗證檔案類型（JPEG 解碼、RAW 檔頭）、SHA-256 去重、存檔、建相簿、入庫、排工作。"""
    if row["kind"] == "raw":
        try:
            check_raw(tmp, row["filename"])
        except Exception as e:
            _reject(row, tmp, 415, f"不是可接受的 RAW（{e}）")
        return finalize_raw(row, tmp)
    try:
        with Image.open(tmp) as im:
            if im.format not in ("JPEG", "MPO"):   # Sony 等機身的 JPG 帶多圖段，Pillow 認成 MPO
                raise ValueError(im.format)
            im.verify()
    except Exception as e:
        _reject(row, tmp, 415, f"只接受 JPEG（{e}）")

    sha = core.sha256_path(tmp)
    size = tmp.stat().st_size
    info = exif_info(tmp)
    taken_at = info.get("taken_at") or row["taken_at"]
    camera = info.get("camera") or row["camera"]
    album_slug = row["album"]
    if row["album_auto"] and info.get("taken_at"):
        album_slug = info["taken_at"][:10].replace("-", "_")
    row = dict(row) | {"album": album_slug}
    dest = core.original_path(sha)
    core.store(tmp, dest)
    try:
        w, h = core.make_derivatives(dest, sha)
    except Exception as e:
        raise HTTPException(400, f"無法讀取圖片：{e}")

    now = time.time()
    with core.db() as con:
        album = core.the_album(con) if core.SINGLE_ALBUM else \
            con.execute("SELECT * FROM albums WHERE slug=?", (row["album"],)).fetchone()
        if not album:
            shoot_date = (taken_at or time.strftime("%Y-%m-%dT"))[:10]
            con.execute("INSERT INTO albums (slug, title, shoot_date, share_key, live_key, created_at, updated_at) "
                        "VALUES (?,?,?,?,?,?,?)",
                        (row["album"], row["album"], shoot_date, core.new_key(), core.new_key(), now, now))
            album = con.execute("SELECT * FROM albums WHERE slug=?", (row["album"],)).fetchone()
        existing = con.execute("SELECT id, status FROM photos WHERE album_id=? AND photo_id=?",
                               (album["id"], sha)).fetchone()
        if existing:
            duplicate = True   # Pi 重開機後重送同一張：不動已有的分析結果
            photo_pk = existing["id"]
        else:
            duplicate = False
            cur = con.execute(
                """INSERT INTO photos (album_id, photo_id, sha256, filename, stars, aesthetic, tags, taken_at,
                                       width, height, bytes, uploaded_at, share_key, status, source, device, camera,
                                       updated_at)
                   VALUES (?,?,?,?,NULL,NULL,'[]',?,?,?,?,?,?,'pending','live',?,?,?)""",
                (album["id"], sha, sha, row["filename"], taken_at, w, h, size, now, core.new_key(),
                 row["device"], camera, now))
            photo_pk = cur.lastrowid
            enqueue(con, photo_pk, album["id"])
            attach_pending_raw(con, photo_pk, album["id"], row["device"], row["filename"], taken_at, camera)
            con.execute("UPDATE albums SET updated_at=? WHERE id=?", (now, album["id"]))
            con.execute("INSERT INTO devices (name, uploads) VALUES (?,1) "
                        "ON CONFLICT(name) DO UPDATE SET uploads=uploads+1", (row["device"],))
        con.execute("UPDATE uploads SET received=total, finished_at=?, photo_id=?, taken_at=?, camera=?, album=? "
                    "WHERE id=?", (now, sha, taken_at, camera, row["album"], row["id"]))
        share_key, live_key = album["share_key"], album["live_key"]
    return {"complete": True, "photo_id": sha, "duplicate": duplicate, "album": row["album"],
            "share_url": core.share_url(share_key), "live_url": core.live_url(live_key)}


def stem_of(name: str) -> str:
    return Path(name).stem.lower()


def tiff_taken_at(path: Path) -> Optional[str]:
    """從 TIFF 結構的 RAW（ARW / NEF / NRW / DNG / CR2 / PEF / ORF / RW2）讀 EXIF DateTimeOriginal，不解碼影像。
    CR3（ISO BMFF）與 RAF 讀不到，回 None。"""
    import struct
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            if head[:2] == b"II":
                e = "<"
            elif head[:2] == b"MM":
                e = ">"
            else:
                return None
            ifd0 = struct.unpack(e + "I", head[4:8])[0]

            def read_ifd(off):
                f.seek(off)
                n = struct.unpack(e + "H", f.read(2))[0]
                if n > 1000:
                    return {}
                raw = f.read(12 * n)
                out = {}
                for i in range(n):
                    tag, typ, cnt = struct.unpack(e + "HHI", raw[12 * i: 12 * i + 8])
                    out[tag] = (typ, cnt, raw[12 * i + 8: 12 * i + 12])
                return out

            def ascii_value(entry):
                typ, cnt, val = entry
                if typ != 2:
                    return None
                if cnt <= 4:
                    return val[:cnt].rstrip(b"\x00").decode("ascii", "ignore")
                f.seek(struct.unpack(e + "I", val)[0])
                return f.read(cnt).rstrip(b"\x00").decode("ascii", "ignore")

            tags = read_ifd(ifd0)
            exif = tags.get(0x8769)
            if not exif:
                return None
            ex = read_ifd(struct.unpack(e + "I", exif[2])[0])
            v = ascii_value(ex[0x9003]) if 0x9003 in ex else None
            if not v or v.startswith("0000"):
                return None
            t = v[:19].replace(":", "-", 2).replace(" ", "T")
            sub = ascii_value(ex[0x9291]) if 0x9291 in ex else ""
            return t + (f".{sub[:3].ljust(3, '0')}" if sub and sub.isdigit() else "")
    except Exception:
        return None


def _ts(iso: Optional[str]) -> Optional[float]:
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(iso).timestamp() if iso else None
    except ValueError:
        return None


PAIR_TOLERANCE = 2.0     # RAW 與 JPG 的拍攝時間差在這之內視為同一張（連拍每張至少差 0.05 秒以上，取最接近的）
PAIR_RECENT = 120.0      # 讀不到 RAW 的拍攝時間時：配同一台裝置最近 2 分鐘內、還沒有 RAW 的那張


def find_jpg_for_raw(con, device: str, filename: str, album: Optional[str], taken_at: Optional[str],
                     camera: Optional[str] = None):
    """RAW 要配哪張 JPG：同檔名 → 拍攝時間最接近（±2 秒）→ 最近一張沒 RAW 的。回傳 photos 的列或 None。
    兩邊都知道機身序號時，序號不同絕不配（兩台同型號相機接同一台 Pi 也不會配錯）。"""
    scope = "AND a.slug=?" if album else ""
    args = [device] + ([album] if album else [])
    if camera:
        scope += " AND (p.camera IS NULL OR p.camera=?)"
        args.append(camera)
    base = ("SELECT p.id, p.album_id, p.taken_at, p.uploaded_at, a.slug FROM photos p JOIN albums a ON a.id=p.album_id "
            f"WHERE p.device=? {scope} ")
    like = stem_of(filename) + ".%"
    row = con.execute(base + "AND lower(p.filename) LIKE ? ORDER BY p.uploaded_at DESC LIMIT 1", args + [like]).fetchone()
    if row:
        return row
    t = _ts(taken_at)
    cands = con.execute(base + "AND p.raw_sha IS NULL ORDER BY p.uploaded_at DESC LIMIT 200", args).fetchall()
    if t is not None:
        best = min(((abs((_ts(c["taken_at"]) or -1e12) - t), c) for c in cands), key=lambda x: x[0], default=None)
        if best and best[0] <= PAIR_TOLERANCE:
            return best[1]
        return None
    recent = [c for c in cands if time.time() - c["uploaded_at"] <= PAIR_RECENT]
    return recent[0] if recent else None


def find_pending_raw_for_jpg(con, device: str, jpg_name: str, taken_at: Optional[str], camera: Optional[str] = None):
    """JPG 剛入庫：有沒有先到的 RAW 可以配（同檔名 → 時間 ±2 秒 → 最近 2 分鐘內沒時間資訊的那個）。"""
    cam = " AND (camera IS NULL OR camera=?)" if camera else ""
    args = [device] + ([camera] if camera else [])
    r = con.execute(f"SELECT * FROM raw_pending WHERE device=?{cam} AND stem=? ORDER BY created_at DESC LIMIT 1",
                    args + [stem_of(jpg_name)]).fetchone()
    if r:
        return r
    t = _ts(taken_at)
    cands = con.execute(f"SELECT * FROM raw_pending WHERE device=?{cam} ORDER BY created_at DESC LIMIT 200", args).fetchall()
    if t is not None:
        timed = [(abs(_ts(c["taken_at"]) - t), c) for c in cands if _ts(c["taken_at"]) is not None]
        best = min(timed, key=lambda x: x[0], default=None)
        if best and best[0] <= PAIR_TOLERANCE:
            return best[1]
    recent = [c for c in cands if c["taken_at"] is None and time.time() - c["created_at"] <= PAIR_RECENT]
    return recent[0] if recent else None


def attach_raw(con, photo_pk: int, album_id: int, sha: str, name: str, size: int):
    con.execute("UPDATE photos SET raw_sha=?, raw_name=?, raw_bytes=?, updated_at=? WHERE id=?",
                (sha, name, size, time.time(), photo_pk))
    enqueue(con, photo_pk, album_id, kind="backup_raw", priority=-1)   # RAW 是附件：排在所有分析工作之後


def attach_pending_raw(con, photo_pk: int, album_id: int, device: str, jpg_name: str, taken_at: Optional[str] = None,
                       camera: Optional[str] = None):
    """JPG 剛入庫：有沒有同一台相機先到的 RAW（同檔名，或拍攝時間對得上）。"""
    r = find_pending_raw_for_jpg(con, device, jpg_name, taken_at, camera)
    if r:
        attach_raw(con, photo_pk, album_id, r["sha256"], r["filename"], r["bytes"])
        con.execute("DELETE FROM raw_pending WHERE id=?", (r["id"],))


def finalize_raw(row, tmp: Path) -> dict:
    """RAW：存檔後配到同一台相機、同檔名的 JPG（找不到就先收著，等 JPG 來）。不產生縮圖、不分析。"""
    sha = core.sha256_path(tmp)
    size = tmp.stat().st_size
    taken_at = tiff_taken_at(tmp) or row["taken_at"]
    core.store(tmp, core.raw_path(sha, row["filename"]))
    now = time.time()
    with core.db() as con:
        # 相簿由 JPG 決定（Pi 用日期猜的相簿可能和 JPG 依 EXIF 入的不同），配對以裝置為準：
        # 同檔名 → 拍攝時間（相機經 PTP 推來的檔名是 capt0000.jpg / capt0001.arw 之類的流水號，只能靠時間）→ 最近一張
        p = find_jpg_for_raw(con, row["device"], row["filename"], None if row["album_auto"] else row["album"], taken_at,
                             row["camera"])
        if p:
            attach_raw(con, p["id"], p["album_id"], sha, row["filename"], size)
            con.execute("UPDATE albums SET updated_at=? WHERE id=?", (now, p["album_id"]))
            album = p["slug"]
        else:
            con.execute("INSERT INTO raw_pending (device, album, stem, sha256, filename, bytes, created_at, taken_at, camera) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (row["device"], None if row["album_auto"] else row["album"], stem_of(row["filename"]), sha,
                         row["filename"], size, now, taken_at, row["camera"]))
            album = None
        con.execute("UPDATE uploads SET received=total, finished_at=?, photo_id=? WHERE id=?", (now, sha, row["id"]))
    return {"complete": True, "photo_id": sha, "duplicate": False, "album": album, "raw": True,
            "paired": bool(p)}


@router.put("/api/uploads/{upload_id}")
async def upload_chunk(upload_id: str, request: Request, authorization: Optional[str] = Header(None),
                       content_range: Optional[str] = Header(None)):
    device = require_device(request, authorization)
    if not UPLOAD_ID_RE.match(upload_id):
        raise HTTPException(400, "upload id 格式不對")
    m = RANGE_RE.match(content_range or "")
    if not m:
        raise HTTPException(400, "需要 Content-Range: bytes S-E/T")
    start, end, total = (int(x) for x in m.groups())
    if total <= 0 or total > UPLOAD_MAX or end < start or end >= total or end - start + 1 > CHUNK_MAX:
        raise HTTPException(400, f"Content-Range 不合理（上限 {UPLOAD_MAX >> 20} MB）")

    h = request.headers
    with core.db() as con:
        if not uploads_enabled(con):   # 503 + Retry-After：Pi 不會把這張標成失敗，等開關打開再傳
            raise HTTPException(503, "即時上傳已關閉", headers={"Retry-After": "60"})
        row = con.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
        if row and row["device"] != device:
            raise HTTPException(403, "這個上傳屬於別的裝置")
        if not row:
            album = (h.get("x-snappipe-album") or "").strip()
            filename = safe_filename(h.get("x-snappipe-filename") or "")
            kind = file_kind(filename)
            if not core.SLUG_RE.match(album):
                raise HTTPException(400, "第一段要帶 X-SnapPipe-Album（相簿名稱：文字、數字、. _ -）")
            if core.SINGLE_ALBUM:              # 一台一本：Pi 給的相簿名稱（日期）不用，也不依拍攝日期分
                album = core.ALBUM_SLUG
                h = {**h, "x-snappipe-album-auto": "0"}
            if not filename:
                raise HTTPException(400, "第一段要帶 X-SnapPipe-Filename")
            if not kind:
                raise HTTPException(415, f"只收 JPG 與 RAW（{', '.join(sorted(RAW_EXT))}）")
            if start != 0:
                raise HTTPException(409, "沒看過這個上傳，請從 0 開始", headers={"Upload-Offset": "0"})
            if shutil.disk_usage(core.DATA_DIR).free - total < MIN_FREE:
                raise HTTPException(507, "伺服器磁碟空間不足", headers={"Retry-After": "300"})
            inflight = con.execute("SELECT COUNT(*) FROM uploads WHERE device=? AND finished_at IS NULL",
                                   (device,)).fetchone()[0]
            if inflight >= MAX_INFLIGHT:
                cleanup_stale_uploads(con)
                raise HTTPException(429, f"同時進行中的上傳太多（{inflight}），先把手上的傳完", headers={"Retry-After": "10"})
            con.execute("""INSERT INTO uploads (id, device, album, filename, total, received, camera, taken_at,
                                                album_auto, kind, started_at)
                           VALUES (?,?,?,?,?,0,?,?,?,?,?)""",
                        (upload_id, device, album, filename, total,
                         (h.get("x-snappipe-camera") or "").strip()[:40] or None,
                         (h.get("x-snappipe-taken-at") or "").strip()[:32] or None,
                         1 if h.get("x-snappipe-album-auto") == "1" else 0, kind, time.time()))
            row = con.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
            upload_tmp(upload_id).touch()
    if row["finished_at"]:
        with core.db() as con:
            a = con.execute("SELECT share_key FROM albums WHERE slug=?", (row["album"],)).fetchone()
        return {"complete": True, "photo_id": row["photo_id"], "duplicate": True, "album": row["album"],
                "share_url": core.share_url(a["share_key"]) if a else None}
    if total != row["total"]:
        raise HTTPException(400, "檔案大小和一開始的不一樣")
    tmp = upload_tmp(upload_id)
    have = tmp.stat().st_size if tmp.exists() else 0
    if have != row["received"]:   # 暫存檔和紀錄對不上（上次寫到一半）：以檔案為準
        with core.db() as con:
            con.execute("UPDATE uploads SET received=? WHERE id=?", (have, upload_id))
    if start != have:
        return JSONResponse({"detail": "請從 Upload-Offset 繼續", "offset": have}, status_code=409,
                            headers={"Upload-Offset": str(have)})

    want = end - start + 1
    got = 0
    with open(tmp, "ab") as f:
        async for chunk in request.stream():
            if got + len(chunk) > want:
                chunk = chunk[: want - got]
            f.write(chunk)
            got += len(chunk)
            if got >= want:
                break
        f.flush()
        os.fsync(f.fileno())
    if got != want:   # 連線中途斷了：砍掉這一段，下次從原本的位置重來
        with open(tmp, "r+b") as f:
            f.truncate(have)
        raise HTTPException(400, f"這一段只收到 {got}/{want} bytes", headers={"Upload-Offset": str(have)})
    received = have + got
    with core.db() as con:
        con.execute("UPDATE uploads SET received=? WHERE id=?", (received, upload_id))
        row = con.execute("SELECT * FROM uploads WHERE id=?", (upload_id,)).fetchone()
    if received < total:
        return JSONResponse({"complete": False, "offset": received}, headers=_offset_headers(row))
    return finalize_upload(row, tmp)


# ---------- 處理端：工作佇列 ----------

def release_expired(con):
    now = time.time()
    con.execute("UPDATE jobs SET status='queued', worker=NULL, lease_until=NULL, updated_at=? "
                "WHERE status='leased' AND lease_until < ?", (now, now))


def job_json(con, j) -> dict:
    p = con.execute("SELECT p.*, a.slug AS album FROM photos p JOIN albums a ON a.id=p.album_id WHERE p.id=?",
                    (j["photo"],)).fetchone()
    return {"id": j["id"], "kind": j["kind"], "attempts": j["attempts"], "lease_until": j["lease_until"],
            "album": p["album"], "photo_id": p["photo_id"], "sha256": p["sha256"], "filename": p["filename"],
            "taken_at": p["taken_at"], "camera": p["camera"], "device": p["device"], "bytes": p["bytes"],
            "width": p["width"], "height": p["height"], "file_url": f"/api/jobs/{j['id']}/file",
            "raw_name": p["raw_name"] if p["raw_sha"] else None, "raw_sha256": p["raw_sha"],
            "raw_bytes": p["raw_bytes"] if p["raw_sha"] else None,
            "raw_url": f"/api/jobs/{j['id']}/raw" if p["raw_sha"] else None}


class ClaimIn(BaseModel):
    worker: str
    max: int = 1
    kinds: list[str] = ["analyze"]


@router.post("/api/jobs/claim")
def claim_jobs(body: ClaimIn, request: Request, authorization: Optional[str] = Header(None)):
    require_worker(request, authorization)
    if not NAME_RE.match(body.worker):
        raise HTTPException(400, "worker 名稱只能用文字、數字、. _ -")
    kinds = [k for k in body.kinds if k in JOB_KINDS] or list(JOB_KINDS)
    n = max(1, min(body.max, 32))
    now = time.time()
    out = []
    with core.db() as con:
        release_expired(con)   # 這個 UPDATE 已經開了寫入交易（RESERVED 鎖）：兩個 worker 同時認領也不會拿到同一件
        q = ",".join("?" * len(kinds))
        rows = con.execute(f"""SELECT * FROM jobs WHERE status='queued' AND kind IN ({q})
                               AND (not_before IS NULL OR not_before <= ?)
                               ORDER BY priority DESC, created_at LIMIT ?""", (*kinds, now, n)).fetchall()
        for j in rows:
            con.execute("UPDATE jobs SET status='leased', worker=?, lease_until=?, attempts=attempts+1, updated_at=? "
                        "WHERE id=?", (body.worker, now + LEASE_SEC, now, j["id"]))
            j = con.execute("SELECT * FROM jobs WHERE id=?", (j["id"],)).fetchone()
            out.append(job_json(con, j))
    return {"jobs": out, "lease_sec": LEASE_SEC}


def leased_job(con, job_id: int, worker: Optional[str] = None):
    j = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not j:
        raise HTTPException(404, "沒有這件工作")
    if j["status"] != "leased":
        raise HTTPException(409, f"這件工作目前是 {j['status']}，不是你租用中的（租約可能已過期，請重新認領）")
    return j


@router.api_route("/api/jobs/{job_id}/file", methods=["GET", "HEAD"])
def job_file(job_id: int, request: Request, authorization: Optional[str] = Header(None)):
    require_worker(request, authorization)
    with core.db() as con:
        j = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not j:
            raise HTTPException(404)
        p = con.execute("SELECT * FROM photos WHERE id=?", (j["photo"],)).fetchone()
    return FileResponse(core.original_path(p["sha256"]), media_type="image/jpeg", filename=p["filename"])


@router.api_route("/api/jobs/{job_id}/raw", methods=["GET", "HEAD"])
def job_raw(job_id: int, request: Request, authorization: Optional[str] = Header(None)):
    require_worker(request, authorization)
    with core.db() as con:
        j = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not j:
            raise HTTPException(404)
        p = con.execute("SELECT * FROM photos WHERE id=?", (j["photo"],)).fetchone()
    if not p["raw_sha"]:
        raise HTTPException(404, "這張沒有 RAW")
    return FileResponse(core.raw_path(p["raw_sha"], p["raw_name"]), media_type="application/octet-stream",
                        filename=p["raw_name"])


@router.put("/api/jobs/{job_id}/file")
def job_replace_file(job_id: int, request: Request, file: UploadFile = File(...), meta: str = Form("{}"),
                     authorization: Optional[str] = Header(None)):
    """處理端把寫好標籤 / 星等（IPTC、XMP）的 JPG 換上去：下載原 JPG 的人會拿到帶 metadata 的版本。
    photo_id（Pi 送來那份的 SHA-256）不變，所以賽後插卡匯入時仍能去重。"""
    require_worker(request, authorization)
    m = core.parse_meta(meta)
    with core.db() as con:
        j = leased_job(con, job_id)
        p = con.execute("SELECT * FROM photos WHERE id=?", (j["photo"],)).fetchone()
    sha, size, tmp = core.receive_file(file, m.get("sha256"))
    if sha == p["sha256"]:
        tmp.unlink(missing_ok=True)
        return {"sha256": sha, "changed": False}
    dest = core.original_path(sha)
    core.store(tmp, dest)
    try:
        w, h = core.make_derivatives(dest, p["photo_id"])   # 縮圖以 photo_id 命名、畫面沒變：已存在就直接沿用
    except Exception as e:
        raise HTTPException(400, f"無法讀取圖片：{e}")
    old = p["sha256"]
    with core.db() as con:
        con.execute("UPDATE photos SET sha256=?, width=?, height=?, bytes=?, updated_at=? WHERE id=?",
                    (sha, w, h, size, time.time(), p["id"]))
        still_used = con.execute("SELECT 1 FROM photos WHERE sha256=? OR photo_id=? LIMIT 1", (old, old)).fetchone()
    if not still_used:
        core.original_path(old).unlink(missing_ok=True)
    return {"sha256": sha, "changed": True, "width": w, "height": h}


class ResultIn(BaseModel):
    stars: Optional[int] = None
    aesthetic: Optional[float] = None
    tags: list[str] = []
    taken_at: Optional[str] = None
    camera: Optional[str] = None
    headline: Optional[str] = None
    caption: Optional[str] = None
    ai: Optional[dict] = None         # 精選、moment、連拍、球員、需確認…（網頁顯示用）
    processor: Optional[str] = None   # 例 "meta-ai:muse-spark-1.3"：記在工作上，之後比較不同模型用
    extra: dict = {}


@router.post("/api/jobs/{job_id}/result")
def job_result(job_id: int, body: ResultIn, request: Request, authorization: Optional[str] = Header(None)):
    require_worker(request, authorization)
    stars = None if body.stars is None else max(0, min(int(body.stars), 5)) or None
    tags = [str(t)[:60] for t in body.tags][:50]
    now = time.time()
    with core.db() as con:
        j = leased_job(con, job_id)
        if j["kind"] == "analyze":   # backup_raw 之類的工作只標完成，不碰照片的分析結果
            sets, vals = ["stars=?", "aesthetic=?", "tags=?", "status='done'"], [stars, body.aesthetic,
                                                                                json.dumps(tags, ensure_ascii=False)]
            if body.taken_at:
                sets.append("taken_at=?"); vals.append(body.taken_at[:32])
            if body.camera:
                sets.append("camera=?"); vals.append(body.camera[:40])
            if body.headline is not None:
                sets.append("headline=?"); vals.append(body.headline[:300])
            if body.caption is not None:
                sets.append("caption=?"); vals.append(body.caption[:2000])
            if body.ai is not None:
                sets.append("ai=?"); vals.append(json.dumps(body.ai, ensure_ascii=False)[:8000])
            sets.append("updated_at=?"); vals.append(now)
            con.execute(f"UPDATE photos SET {', '.join(sets)} WHERE id=?", (*vals, j["photo"]))
        con.execute("UPDATE jobs SET status='done', result=?, error=NULL, updated_at=? WHERE id=?",
                    (json.dumps({"processor": body.processor, **body.extra}, ensure_ascii=False)[:4000], now, j["id"]))
        con.execute("UPDATE albums SET updated_at=? WHERE id=?", (now, j["album_id"]))
    return {"ok": True}


class FailIn(BaseModel):
    error: str = ""
    retry: bool = True


@router.post("/api/jobs/{job_id}/fail")
def job_fail(job_id: int, body: FailIn, request: Request, authorization: Optional[str] = Header(None)):
    require_worker(request, authorization)
    now = time.time()
    with core.db() as con:
        j = leased_job(con, job_id)
        dead = not body.retry or j["attempts"] >= MAX_ATTEMPTS
        if dead:
            con.execute("UPDATE jobs SET status='dead', error=?, worker=NULL, lease_until=NULL, updated_at=? WHERE id=?",
                        (body.error[:1000], now, j["id"]))
            if j["kind"] == "analyze":
                con.execute("UPDATE photos SET status='failed', updated_at=? WHERE id=?", (now, j["photo"]))
        else:
            backoff = min(30 * 2 ** j["attempts"], 900)
            con.execute("UPDATE jobs SET status='queued', error=?, worker=NULL, lease_until=NULL, not_before=?, "
                        "updated_at=? WHERE id=?", (body.error[:1000], now + backoff, now, j["id"]))
    return {"ok": True, "dead": dead}


@router.post("/api/jobs/{job_id}/heartbeat")
def job_heartbeat(job_id: int, request: Request, authorization: Optional[str] = Header(None)):
    require_worker(request, authorization)
    now = time.time()
    with core.db() as con:
        j = leased_job(con, job_id)
        con.execute("UPDATE jobs SET lease_until=?, updated_at=? WHERE id=?", (now + LEASE_SEC, now, j["id"]))
    return {"lease_until": now + LEASE_SEC}


@router.put("/api/worker/albums/{slug}/people")
def worker_people(slug: str, body: core.PeopleIn, request: Request, authorization: Optional[str] = Header(None)):
    """處理端的人物分組（格式同返圖站 /api/albums/{slug}/people，但用 worker token、不限區網）。"""
    require_worker(request, authorization)
    with core.db() as con:
        album = core.album_by_slug(con, slug)
        n = core.apply_people(con, album, body.people)
        con.execute("UPDATE albums SET updated_at=? WHERE id=?", (time.time(), album["id"]))
    return {"people": n}


# ---------- 管理端（返圖站的上傳 token，限區網） ----------

@router.get("/api/live/status")
def live_status(request: Request, authorization: Optional[str] = Header(None)):
    require_admin(request, authorization)
    with core.db() as con:
        release_expired(con)
        devices = [dict(r) | {"stats": json.loads(r["stats"])} for r in
                   con.execute("SELECT * FROM devices ORDER BY name")]
        counts = {r["status"]: r["n"] for r in con.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status")}
        pending_uploads = con.execute("SELECT COUNT(*) FROM uploads WHERE finished_at IS NULL").fetchone()[0]
        workers = [dict(r) for r in con.execute(
            "SELECT worker, COUNT(*) n, MAX(updated_at) last FROM jobs WHERE worker IS NOT NULL GROUP BY worker")]
        dead = [dict(r) for r in con.execute(
            "SELECT j.id, j.error, j.attempts, p.filename, a.slug album FROM jobs j JOIN photos p ON p.id=j.photo "
            "JOIN albums a ON a.id=j.album_id WHERE j.status='dead' ORDER BY j.updated_at DESC LIMIT 20")]
        albums = [dict(r) for r in con.execute(
            """SELECT a.slug, a.title, a.updated_at, a.share_key, a.live_key,
                      SUM(p.source='live') live, SUM(p.status='pending') pending, COUNT(*) n
               FROM albums a JOIN photos p ON p.album_id=a.id GROUP BY a.id ORDER BY a.updated_at DESC LIMIT 10""")]
        enabled = uploads_enabled(con)
    return {"enabled": enabled, "devices": devices, "jobs": counts, "uploads_in_progress": pending_uploads,
            "workers": workers, "dead": dead, "albums": albums,
            "tokens": {"devices": sorted(DEVICE_TOKENS.values()),
                       "worker": "token" if WORKER_TOKEN else "區網免 token"}}


class SwitchIn(BaseModel):
    enabled: bool


@router.put("/api/live/switch")
def live_switch(body: SwitchIn, request: Request, authorization: Optional[str] = Header(None)):
    """即時上傳總開關（等同伺服器上的 snappipe-live on/off）。"""
    require_admin(request, authorization)
    with core.db() as con:
        set_setting(con, "uploads_enabled", "1" if body.enabled else "0")
    return {"enabled": body.enabled}


class DeviceIn(BaseModel):
    album: Optional[str] = None


@router.put("/api/live/devices/{name}")
def set_device(name: str, body: DeviceIn, request: Request, authorization: Optional[str] = Header(None)):
    """指定這台 Pi 之後上傳的照片進哪本相簿（null = 用 Pi 自己的設定）。"""
    require_admin(request, authorization)
    if not NAME_RE.match(name):
        raise HTTPException(400, "裝置名稱不合法")
    if body.album and not core.SLUG_RE.match(body.album):
        raise HTTPException(400, "相簿名稱只能用文字、數字、. _ -")
    with core.db() as con:
        con.execute("INSERT INTO devices (name, active_album) VALUES (?,?) "
                    "ON CONFLICT(name) DO UPDATE SET active_album=excluded.active_album", (name, body.album))
    return {"device": name, "album": body.album}


@router.post("/api/live/albums/{slug}/reprocess")
def reprocess_album(slug: str, request: Request, authorization: Optional[str] = Header(None),
                    only_failed: bool = False):
    """整本相簿重新排進佇列（換了模型、調了門檻之後用）。"""
    require_admin(request, authorization)
    with core.db() as con:
        album = core.album_by_slug(con, slug)
        where = "AND status='failed'" if only_failed else ""
        rows = con.execute(f"SELECT id FROM photos WHERE album_id=? {where}", (album["id"],)).fetchall()
        for r in rows:
            enqueue(con, r["id"], album["id"])
        con.execute("UPDATE photos SET status='pending' WHERE id IN (%s)" % ",".join("?" * len(rows)),
                    [r["id"] for r in rows]) if rows else None
    return {"queued": len(rows)}


@router.post("/api/live/jobs/{job_id}/retry")
def retry_job(job_id: int, request: Request, authorization: Optional[str] = Header(None)):
    require_admin(request, authorization)
    with core.db() as con:
        j = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not j:
            raise HTTPException(404)
        enqueue(con, j["photo"], j["album_id"], j["kind"], priority=1)
        con.execute("UPDATE photos SET status='pending' WHERE id=?", (j["photo"],))
    return {"ok": True}


# ---------- 即時監看頁（/live/<即時碼>：給攝影師與編輯；照片不分星等、依時間流出 + 相機傳輸狀態） ----------

ONLINE_SEC = 45          # 心跳在這之內 = 連線中
STALE_SEC = 180          # 連線中但這麼久沒新照片 → 提示（可能沒電、相機沒在傳）


def album_by_live_key(con, key: str):
    row = con.execute("SELECT * FROM albums WHERE live_key=?", (key,)).fetchone()
    if not row:
        raise HTTPException(404, "相簿不存在")
    return row


def feed_photo(r) -> dict:
    return {"id": r["photo_id"], "sha": r["sha256"], "pk": r["share_key"], "name": r["filename"], "stars": r["stars"],
            "status": r["status"], "source": r["source"], "taken_at": r["taken_at"], "uploaded_at": r["uploaded_at"],
            "updated_at": r["updated_at"], "device": r["device"], "camera": r["camera"],
            "w": r["width"], "h": r["height"], "bytes": r["bytes"], "tags": json.loads(r["tags"]),
            "raw_name": r["raw_name"] if r["raw_sha"] else None, "raw_bytes": r["raw_bytes"] if r["raw_sha"] else None,
            **core.ai_json(r)}


@router.get("/api/live/feed/{key}")
def live_feed(key: str, since: float = 0):
    """since = 上次拿到的 server_time：只回這之後有新增或更新的照片；裝置與統計每次都回。"""
    now = time.time()
    with core.db() as con:
        require_live_enabled(con)
        album = album_by_live_key(con, key)
        aid = album["id"]
        release_expired(con)
        where = "AND updated_at > ?" if since else ""
        rows = con.execute(f"""SELECT * FROM photos WHERE album_id=? {where}
                               ORDER BY taken_at DESC, uploaded_at DESC LIMIT 2000""",
                           (aid, since) if since else (aid,)).fetchall()
        counts = dict(con.execute("""SELECT COUNT(*) total, SUM(status='pending') pending, SUM(status='done') done,
                                            SUM(status='failed') failed, SUM(source='live') live
                                     FROM photos WHERE album_id=?""", (aid,)).fetchone())
        # 每台 Pi：這本相簿的張數、最後一張、最近一分鐘的張數、進行中的上傳
        per_dev = {r["device"]: dict(r) for r in con.execute(
            """SELECT device, COUNT(*) n, MAX(uploaded_at) last_at, SUM(uploaded_at > ?) last_min
               FROM photos WHERE album_id=? AND device IS NOT NULL GROUP BY device""", (now - 60, aid))}
        in_prog = {}
        for u in con.execute("SELECT device, filename, received, total, started_at FROM uploads "
                             "WHERE finished_at IS NULL AND started_at > ? ORDER BY started_at", (now - 600,)):
            in_prog.setdefault(u["device"], []).append(
                {"filename": u["filename"], "received": u["received"], "total": u["total"]})
        devices = []
        for d in con.execute("SELECT * FROM devices ORDER BY name"):
            s = per_dev.get(d["name"], {})
            seen = d["last_seen"] or 0
            online = now - seen < ONLINE_SEC
            last_at = s.get("last_at")
            devices.append({
                "name": d["name"], "online": online, "last_seen": seen, "active_album": d["active_album"],
                "stats": json.loads(d["stats"]), "uploads_total": d["uploads"],
                "album_count": s.get("n", 0), "last_photo_at": last_at, "per_min": s.get("last_min", 0),
                "in_progress": in_prog.get(d["name"], []),
                "stale": bool(online and last_at and now - last_at > STALE_SEC),
            })
        cameras = [dict(r) for r in con.execute(
            """SELECT camera, device, COUNT(*) n, MAX(uploaded_at) last_at FROM photos
               WHERE album_id=? AND camera IS NOT NULL GROUP BY camera, device ORDER BY n DESC""", (aid,))]
        jobs = {r["status"]: r["n"] for r in con.execute(
            "SELECT status, COUNT(*) n FROM jobs WHERE album_id=? GROUP BY status", (aid,))}
        workers = [dict(r) for r in con.execute(
            "SELECT worker, MAX(updated_at) last, SUM(status='leased') busy FROM jobs "
            "WHERE worker IS NOT NULL AND updated_at > ? GROUP BY worker", (now - 900,))]
    return {"title": album["title"], "slug": album["slug"], "shoot_date": album["shoot_date"],
            "share_url": core.share_url(album["share_key"]), "server_time": now,
            "photos": [feed_photo(r) for r in rows], "counts": counts, "devices": devices, "cameras": cameras,
            "jobs": jobs, "workers": workers, "full": not since}


@router.api_route("/lm/{key}/{kind}/{sha}", methods=["GET", "HEAD"])
def live_media(key: str, kind: str, sha: str):
    """即時頁的圖片：只給這本相簿的照片。"""
    if not core.SHA_RE.match(sha):
        raise HTTPException(404)
    with core.db() as con:
        require_live_enabled(con)
        row = con.execute(
            "SELECT p.* FROM photos p JOIN albums a ON a.id=p.album_id WHERE a.live_key=? "
            "AND (p.photo_id=? OR p.sha256=?)", (key, sha, sha)).fetchone()
    if not row:
        raise HTTPException(404)
    return core.serve(row, kind)


repair_pending_raws()
