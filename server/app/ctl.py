"""
伺服器上的管理指令（安裝後有 snappipe-live 捷徑）：

  snappipe-live status     目前狀態、裝置、佇列、各相簿的返圖 / 即時監看網址
  snappipe-live links      固定連結（永遠導到最新相簿）與各相簿的返圖 / 即時監看網址
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
                  f" 相簿 {d['active_album'] or '（Pi 自己決定）'}")
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
