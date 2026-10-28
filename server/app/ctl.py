"""
伺服器上的管理指令（安裝後有 snappipe-live 捷徑）：

  snappipe-live status     目前狀態、裝置、佇列、各相簿的返圖 / 即時監看網址
  snappipe-live links      固定連結（永遠導到最新相簿）與各相簿的返圖 / 即時監看網址
  snappipe-live album <名稱>          所有 Pi 之後拍的照片都進這本相簿（不設 = 拍攝日期，例 2026_10_30）
  snappipe-live album <裝置> <名稱>   只指定一台，例 snappipe-live album pi-1 Saki外拍
  snappipe-live album -              清除指定，改回 Pi 自己的設定 / 拍攝日期（也可以 album pi-1 -）
  snappipe-live album                列出每台 Pi 目前的相簿
  snappipe-live off        關掉即時上傳：Pi 暫停上傳（照片留在卡上）、即時監看頁關閉；返圖頁與插卡上傳照常
  snappipe-live on         重新開啟

直接寫資料庫，所有 uvicorn worker 下一個請求就生效，不用重啟服務。
"""

import json
import os
import sys
import time

from . import main as core  # 先載 main（它最後才掛 live），避免循環引用
from . import live  # noqa: E402


def full(url: str) -> str:
    """沒設對外網址時 share_url 是相對路徑：補上伺服器的區網網址，複製就能開。"""
    if url.startswith("/"):
        return (os.environ.get("SNAPPIPE_HINT_SERVER") or "").rstrip("/") + url
    return url


def site_links(con):
    """固定連結：安裝完就有、永遠導到最新的相簿。"""
    s = live.site_links(con)
    print(f"  返圖（給客人，永遠是最新的相簿）：{full(core.PUBLIC_URL + s['album'])}")
    print(f"  即時監看（攝影師 / 編輯，不要給客人）：{full(core.PUBLIC_URL + s['live'])}")


def links(con, limit=10) -> int:
    n = 0
    for a in con.execute("SELECT * FROM albums ORDER BY created_at DESC LIMIT ?", (limit,)):
        print(f"  相簿 {a['slug']}")
        print(f"    返圖（給客人）：{full(core.share_url(a['share_key']))}")
        print(f"    即時監看（攝影師 / 編輯）：{full(core.live_url(a['live_key']))}")
        n += 1
    return n


def device_names(con) -> list:
    """已經連過的 Pi + 設定裡登記的 Pi（還沒開機的也算）。"""
    names = {r["name"] for r in con.execute("SELECT name FROM devices")}
    for d in (os.environ.get("SNAPPIPE_DEVICE_TOKENS") or "").split(","):
        d = d.strip()
        if ":" in d:
            names.add(d.split(":", 1)[0].strip())
    return sorted(n for n in names if n)


def show_albums(con):
    names = device_names(con)
    if not names:
        print("  還沒有登記任何 Pi（/etc/snappipe.env 的 SNAPPIPE_DEVICE_TOKENS）")
    for n in names:
        r = con.execute("SELECT active_album FROM devices WHERE name=?", (n,)).fetchone()
        print(f"  {n:<12} → {(r and r['active_album']) or '拍攝日期（沒有指定）'}")


def album(args) -> int:
    with core.db() as con:
        if not args:
            show_albums(con)
            return 0
        if len(args) == 1:
            if args[0] in device_names(con):
                print(f"{args[0]} 是裝置名稱：要指定相簿請用 snappipe-live album {args[0]} <相簿名稱>", file=sys.stderr)
                return 2
            targets, name = device_names(con), args[0]
        elif len(args) == 2:
            targets, name = [args[0]], args[1]
        else:
            print("用法：snappipe-live album [裝置] <相簿名稱 | ->", file=sys.stderr)
            return 2
        if not targets:
            print("還沒有登記任何 Pi：先在 /etc/snappipe.env 的 SNAPPIPE_DEVICE_TOKENS 加一組 名稱:token", file=sys.stderr)
            return 1
        clear = name in ("-", "")
        if not clear and not core.SLUG_RE.match(name):
            print(f"相簿名稱不合法：{name}（可以用中英文、數字與 . _ -，不能有空白，最多 100 字）", file=sys.stderr)
            return 1
        for n in targets:
            if not live.NAME_RE.match(n):
                print(f"裝置名稱不合法：{n}", file=sys.stderr)
                return 1
            con.execute("INSERT INTO devices (name, active_album) VALUES (?,?) "
                        "ON CONFLICT(name) DO UPDATE SET active_album=excluded.active_album", (n, None if clear else name))
        show_albums(con)
    print("Pi 下次回報狀態（幾秒內）生效；已經在 Pi 上排隊的照片仍進原本的相簿。"
          + ("" if clear else "相簿在第一張照片進來時建立，固定連結會自動導過去。"))
    return 0


def status():
    with core.db() as con:
        on = live.uploads_enabled(con)
        print(f"即時上傳：{'開啟' if on else '關閉（Pi 暫停、監看頁關閉）'}")
        jobs = {r["status"]: r["n"] for r in con.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status")}
        print(f"佇列：{jobs or '空'}")
        for d in con.execute("SELECT * FROM devices ORDER BY name"):
            st = json.loads(d["stats"])
            ago = f"{int(time.time() - d['last_seen'])} 秒前" if d["last_seen"] else "從未"
            print(f"  裝置 {d['name']:<12} 心跳 {ago:<10} 已傳 {d['uploads']:<5} 待傳 {st.get('pending', '?'):<4}"
                  f" 相簿 {d['active_album'] or '（沒有指定：Pi 的設定或拍攝日期）'}")
        site_links(con)
        links(con)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "status"
    if cmd in ("on", "off"):
        with core.db() as con:
            live.set_setting(con, "uploads_enabled", "1" if cmd == "on" else "0")
        print("即時上傳已" + ("開啟" if cmd == "on" else "關閉：Pi 會暫停上傳、即時監看頁已關閉；返圖頁照常"))
    elif cmd == "status":
        status()
    elif cmd == "album":
        sys.exit(album(argv[1:]))
    elif cmd == "links":
        with core.db() as con:
            site_links(con)
            if links(con):
                print("  （上面兩個固定連結會自動導到最新的相簿；要給客人某一本，就用那本自己的返圖連結）")
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
