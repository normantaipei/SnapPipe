"""
NAS（SMB）掛載：ingest 與 worker 共用。

NAS_SMB 寫成 smb://帳號@NAS_IP/共用資料夾/子資料夾；已經被 Finder 掛載就直接用，
沒有才 mount_smbfs 到 NAS_MOUNT。密碼放 ~/Library/Preferences/nsmb.conf 就不會每次問。
也可以直接寫本機路徑（例如已掛載的 /Volumes/xxx），方便測試。
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit


def parse_smb(url: str):
    """smb://帳號@主機/共用資料夾/子資料夾 → (帳號, 主機, 共用資料夾, [子資料夾...])"""
    u = urlsplit(url)
    parts = [unquote(p) for p in u.path.split("/") if p]
    if u.scheme != "smb" or not u.hostname or not parts:
        raise RuntimeError(f"NAS 位址格式應為 smb://帳號@NAS_IP/共用資料夾/子資料夾，收到：{url}")
    return u.username, u.hostname, parts[0], parts[1:]


def find_smb_mount(host: str, parts):
    """這個位置已經掛載（可能掛的是子資料夾）就直接用，不重複掛。"""
    norm = lambda h: h.lower().removesuffix(".local")
    want = [p.lower() for p in parts]
    for line in subprocess.run(["mount"], capture_output=True, text=True).stdout.splitlines():
        if "(smbfs" not in line:
            continue
        src, _, rest = line.partition(" on ")
        mp = rest.rsplit(" (", 1)[0]
        h, _, path = unquote(src.lstrip("/").rpartition("@")[2]).partition("/")
        have = [p.lower() for p in path.split("/") if p]
        if norm(h) == norm(host) and have and want[:len(have)] == have:
            return Path(mp).joinpath(*parts[len(have):])
    return None


def nas_root(nas: str, mount_point) -> Path | None:
    """回傳 NAS 備份根目錄（需要時自動 mount_smbfs）；nas 為空則回傳 None。"""
    if not nas:
        return None
    if not nas.startswith("smb://"):
        return Path(os.path.expandvars(nas)).expanduser()
    user, host, share, sub = parse_smb(nas)
    found = find_smb_mount(host, [share] + sub)
    if not found and sys.platform != "darwin":
        raise RuntimeError("Linux 不會自動掛 SMB：請先 mount -t cifs 掛好（或寫進 /etc/fstab），NAS_SMB 改填掛載後的路徑")
    if found:
        return found
    mp = Path(os.path.expandvars(str(mount_point))).expanduser()
    mp.mkdir(parents=True, exist_ok=True)
    src = f"//{quote(user) + '@' if user else ''}{host}/{quote(share)}"
    r = subprocess.run(["mount_smbfs", src, str(mp)], stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"NAS 掛載失敗（{src}）：{r.stderr.strip()}")
    return mp.joinpath(*sub)
