"""
伺服器上的管理指令（安裝後有 snappipe-live 捷徑）：

  snappipe-live status     目前狀態、裝置、佇列、相簿的返圖 / 即時監看網址
  snappipe-live links      相簿的返圖 / 即時監看網址
  snappipe-live album              看相簿名稱（一台伺服器 = 一個拍攝計劃 = 一本相簿）
  snappipe-live album <新名稱>     改相簿名稱（可以有空白，例 snappipe-live album Saki 外拍 10/30）
  （SNAPPIPE_SINGLE_ALBUM=0 的舊模式：album [裝置] <名稱 | -> 指定 Pi 之後的照片進哪本）
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

# 訊息語言：/etc/snappipe.env 的 SNAPPIPE_LANG=en（snappipe-live 捷徑會載入）用英文，其他用中文
EN = os.environ.get("SNAPPIPE_LANG") == "en"


def t(zh, en):
    return en if EN else zh


USAGE_EN = """
Server admin commands (installed as the snappipe-live shortcut):

  snappipe-live status     Status, devices, queue, and the album's album site / live view links
  snappipe-live links      The album's album site / live view links
  snappipe-live album              Show the album name (one server = one shoot plan = one album)
  snappipe-live album <new name>   Rename the album (spaces are fine, e.g. snappipe-live album Saki shoot Oct 30)
  (Old mode with SNAPPIPE_SINGLE_ALBUM=0: album [device] <name | -> sets which album a Pi's new photos go to)
  snappipe-live off        Turn off live upload: Pis pause uploads (photos stay on the card) and live view closes;
                           the album site and card import keep working
  snappipe-live on         Turn it back on

Writes to the database directly. Every uvicorn worker picks it up on the next request; no restart needed.
"""


def full(url: str) -> str:
    """沒設對外網址時 share_url 是相對路徑：補上伺服器的區網網址，複製就能開。"""
    if url.startswith("/"):
        return (os.environ.get("SNAPPIPE_HINT_SERVER") or "").rstrip("/") + url
    return url


def site_links(con):
    """固定連結：安裝完就有、永遠導到最新的相簿。"""
    s = live.site_links(con)
    a, lv = full(core.PUBLIC_URL + s['album']), full(core.PUBLIC_URL + s['live'])
    print(t(f"  返圖（給客人，永遠是最新的相簿）：{a}", f"  Album site (for guests, always the newest album): {a}"))
    print(t(f"  即時監看（攝影師 / 編輯，不要給客人）：{lv}", f"  Live view (photographer / editor, not for guests): {lv}"))


def single_links(con):
    """一台一本：直接印這本相簿的連結。"""
    a = core.the_album(con)
    share, lv = full(core.share_url(a['share_key'])), full(core.live_url(a['live_key']))
    print(t(f"  相簿：{a['title']}", f"  Album: {a['title']}"))
    print(t(f"  返圖（給客人）：{share}", f"  Album site (for guests): {share}"))
    print(t(f"  即時監看（攝影師 / 編輯，不要給客人）：{lv}", f"  Live view (photographer / editor, not for guests): {lv}"))


def links(con, limit=10) -> int:
    n = 0
    for a in con.execute("SELECT * FROM albums ORDER BY created_at DESC LIMIT ?", (limit,)):
        share, lv = full(core.share_url(a['share_key'])), full(core.live_url(a['live_key']))
        print(t(f"  相簿 {a['slug']}", f"  Album {a['slug']}"))
        print(t(f"    返圖（給客人）：{share}", f"    Album site (for guests): {share}"))
        print(t(f"    即時監看（攝影師 / 編輯）：{lv}", f"    Live view (photographer / editor): {lv}"))
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
        print(t("  還沒有登記任何 Pi（/etc/snappipe.env 的 SNAPPIPE_DEVICE_TOKENS）",
                "  No Pi registered yet (SNAPPIPE_DEVICE_TOKENS in /etc/snappipe.env)"))
    for n in names:
        r = con.execute("SELECT active_album FROM devices WHERE name=?", (n,)).fetchone()
        print(f"  {n:<12} → {(r and r['active_album']) or t('拍攝日期（沒有指定）', 'shoot date (not set)')}")


def rename(args) -> int:
    """一台一本：看或改相簿名稱（標題）。網址不變。"""
    with core.db() as con:
        a = core.the_album(con)
        if not args:
            print(t(f"  相簿：{a['title']}", f"  Album: {a['title']}"))
            return 0
        title = " ".join(args).strip()
        title = "".join(c for c in title if c.isprintable())[:100]
        if not title:
            print(t("相簿名稱不能是空的", "The album name can't be empty"), file=sys.stderr)
            return 1
        con.execute("UPDATE albums SET title=? WHERE id=?", (title, a["id"]))
    print(t(f"  相簿名稱改成：{title}（連結不變）", f"  Album renamed to: {title} (links stay the same)"))
    return 0


def album(args) -> int:
    if core.SINGLE_ALBUM:
        return rename(args)
    with core.db() as con:
        if not args:
            show_albums(con)
            return 0
        if len(args) == 1:
            if args[0] in device_names(con):
                print(t(f"{args[0]} 是裝置名稱：要指定相簿請用 snappipe-live album {args[0]} <相簿名稱>",
                        f"{args[0]} is a device name. To set its album, use snappipe-live album {args[0]} <album name>"),
                      file=sys.stderr)
                return 2
            targets, name = device_names(con), args[0]
        elif len(args) == 2:
            targets, name = [args[0]], args[1]
        else:
            print(t("用法：snappipe-live album [裝置] <相簿名稱 | ->", "Usage: snappipe-live album [device] <album name | ->"), file=sys.stderr)
            return 2
        if not targets:
            print(t("還沒有登記任何 Pi：先在 /etc/snappipe.env 的 SNAPPIPE_DEVICE_TOKENS 加一組 名稱:token",
                    "No Pi registered yet. First add a name:token pair to SNAPPIPE_DEVICE_TOKENS in /etc/snappipe.env"),
                  file=sys.stderr)
            return 1
        clear = name in ("-", "")
        if not clear and not core.SLUG_RE.match(name):
            print(t(f"相簿名稱不合法：{name}（可以用中英文、數字與 . _ -，不能有空白，最多 100 字）",
                    f"Invalid album name: {name} (use letters, CJK characters, digits, and . _ -; no spaces; up to 100 characters)"),
                  file=sys.stderr)
            return 1
        for n in targets:
            if not live.NAME_RE.match(n):
                print(t(f"裝置名稱不合法：{n}", f"Invalid device name: {n}"), file=sys.stderr)
                return 1
            con.execute("INSERT INTO devices (name, active_album) VALUES (?,?) "
                        "ON CONFLICT(name) DO UPDATE SET active_album=excluded.active_album", (n, None if clear else name))
        show_albums(con)
    print(t("Pi 下次回報狀態（幾秒內）生效；已經在 Pi 上排隊的照片仍進原本的相簿。"
            + ("" if clear else "相簿在第一張照片進來時建立，固定連結會自動導過去。"),
            "Takes effect the next time the Pi reports in (within seconds). Photos already queued on the Pi still go to the old album."
            + ("" if clear else " The album is created when its first photo arrives, and the fixed links will point to it.")))
    return 0


def status():
    with core.db() as con:
        on = live.uploads_enabled(con)
        print(t(f"即時上傳：{'開啟' if on else '關閉（Pi 暫停、監看頁關閉）'}",
                f"Live upload: {'on' if on else 'off (Pis paused, live view closed)'}"))
        jobs = {r["status"]: r["n"] for r in con.execute("SELECT status, COUNT(*) n FROM jobs GROUP BY status")}
        print(t(f"佇列：{jobs or '空'}", f"Queue: {jobs or 'empty'}"))
        for d in con.execute("SELECT * FROM devices ORDER BY name"):
            st = json.loads(d["stats"])
            secs = int(time.time() - d['last_seen']) if d["last_seen"] else None
            ago = (t(f"{secs} 秒前", f"{secs}s ago") if secs is not None else t("從未", "never"))
            pending = st.get('pending', '?')
            where = "" if core.SINGLE_ALBUM else t(f" 相簿 {d['active_album'] or '（沒有指定：Pi 的設定或拍攝日期）'}",
                                                     f" album {d['active_album'] or '(not set: Pi setting or shoot date)'}")
            print(t(f"  裝置 {d['name']:<12} 心跳 {ago:<10} 已傳 {d['uploads']:<5} 待傳 {pending:<4}",
                    f"  Device {d['name']:<12} heartbeat {ago:<10} sent {d['uploads']:<5} queued {pending:<4}") + where)
        if core.SINGLE_ALBUM:
            single_links(con)
        else:
            site_links(con)
            links(con)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "status"
    if cmd in ("on", "off"):
        with core.db() as con:
            live.set_setting(con, "uploads_enabled", "1" if cmd == "on" else "0")
        print(t("即時上傳已" + ("開啟" if cmd == "on" else "關閉：Pi 會暫停上傳、即時監看頁已關閉；返圖頁照常"),
                "Live upload is " + ("on" if cmd == "on" else "off: Pis will pause uploads and live view is closed; the album site still works")))
    elif cmd == "status":
        status()
    elif cmd == "album":
        sys.exit(album(argv[1:]))
    elif cmd == "links":
        with core.db() as con:
            if core.SINGLE_ALBUM:
                single_links(con)
                return
            site_links(con)
            if links(con):
                print(t("  （上面兩個固定連結會自動導到最新的相簿；要給客人某一本，就用那本自己的返圖連結）",
                        "  (The two fixed links above always go to the newest album. To share one specific album with guests, use that album's own album site link.)"))
    else:
        print(t(__doc__, USAGE_EN))
        sys.exit(2)


if __name__ == "__main__":
    main()
