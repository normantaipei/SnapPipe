"""端到端結果檢查：連拍分組、精選、圖說（名單填名、範本、署名）、需確認、球員分組、JPG 內的 IPTC、對 API 的請求格式。"""
import json, subprocess, sys, tempfile
import requests
server, tok, album, meta_log = sys.argv[1:5]
H = {"Authorization": f"Bearer {tok}"}
st = requests.get(f"{server}/api/live/status", headers=H, timeout=10).json()
a = next(x for x in st["albums"] if x["slug"] == album)
feed = requests.get(f"{server}/api/live/feed/{a['live_key']}", timeout=10).json()
share = requests.get(f"{server}/api/share/{a['share_key']}", timeout=10).json()
ph = {p["name"]: p for p in feed["photos"]}
fails = []
def check(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond: fails.append(msg)

print("=== 照片")
for n in sorted(ph):
    p = ph[n]; ai = p.get("ai") or {}
    print(f"  {n} {p['status']} ★{p['stars']} pick={ai.get('pick')} burst={ai.get('burst')} review={ai.get('needs_review')}")
    if p.get("caption"): print(f"     標題：{p['headline']}\n     圖說：{p['caption']}")
check(len(ph) == 7 and all(p["status"] == "done" for p in ph.values()), "7 張都分析完成")
if "--plain" in sys.argv[5:]:      # PLAIN=1：不用 AI（ANALYZER=none），當普通相簿
    import os
    check(all(not p.get("caption") and not (p.get("ai") or {}).get("pick") for p in ph.values()), "沒有 AI：不選片、不寫圖說")
    check(len(share["photos"]) == 7, "7 張都在返圖頁")
    sp = share["photos"][0]
    r = requests.get(f"{server}/media/{a['share_key']}/o/{sp['sha']}", timeout=30)
    check(r.ok and r.content[:2] == b"\xff\xd8", "原圖可以下載")
    check(not os.path.exists(meta_log) or os.path.getsize(meta_log) == 0, "沒有呼叫 Meta API")
    print("\n結果：", "全部通過" if not fails else f"{len(fails)} 項失敗")
    sys.exit(1 if fails else 0)
bursts = {p["ai"]["burst"]["id"] for n, p in ph.items() if n.startswith("A")}
check(len(bursts) == 1 and ph["A0000.JPG"]["ai"]["burst"]["n"] == 5, "相機 A 的 5 張連拍湊成同一組")
check(ph["B0001.JPG"]["ai"]["burst"]["n"] == 1 and ph["B0002.JPG"]["ai"]["burst"]["n"] == 1, "相機 B 的兩張各自一組（間隔大）")
picks = sorted(n for n, p in ph.items() if p["ai"]["pick"])
check(picks == ["A0002.JPG", "A0004.JPG", "B0001.JPG", "B0002.JPG"], f"精選 = {picks}")
check(all(not ph[n].get("caption") for n in ph if n not in picks), "沒選中的不寫圖說")
c = ph["A0002.JPG"]["caption"] or ""
check("台北雄鷹隊王小明（#23）" in c and "新竹獵豹隊林志強（#11）" in c, "人名由名單填入（佔位符替換）")
check(c.startswith("台北，2026 年 10 月 30 日 — ") and "地點為台北體育館" in c, "日期、地點由範本填")
check("攝影：李攝影／SnapPipe" in c, "相機 A（…5530）署名李攝影")
check("攝影：預設攝影／SnapPipe" in (ph["B0001.JPG"]["caption"] or ""), "相機 B 用預設署名")
check(ph["A0002.JPG"]["headline"] == "王小明灌籃", "標題用短名、中文不留空格")
r = ph["A0002.JPG"]["ai"]
check(r["needs_review"] and any("#99" in x for x in r["review_reasons"]) and any("0.62" in x for x in r["review_reasons"]),
      f"需確認：{r['review_reasons']}")
check("AI 精選" in ph["A0002.JPG"]["tags"] and "王小明" in ph["A0002.JPG"]["tags"], f"標籤 {ph['A0002.JPG']['tags']}")
check(ph["A0000.JPG"]["ai"].get("issues") == ["motion_blur_subject"], "第一張帶問題標記")
check(ph["A0002.JPG"]["stars"] >= ph["A0000.JPG"]["stars"], "精選星等不低於失誤張")
people = share.get("people", [])
labels = [p["label"] for p in people]
check(labels == ["#23 王小明"], f"球員分組 {labels}（#11 信心 0.62 不分組、#99 不在名單）")
# IPTC
pk = share["photos"]
sp = next(p for p in pk if p["name"] == "A0002.JPG")
with tempfile.NamedTemporaryFile(suffix=".jpg") as f:
    f.write(requests.get(f"{server}/media/{a['share_key']}/o/{sp['sha']}", timeout=30).content); f.flush()
    m = json.loads(subprocess.run(["exiftool", "-json", "-Headline", "-Caption-Abstract", "-Description", "-PersonInImage",
                                   "-Rating", "-Label", "-By-line", "-Urgency", "-Event", "-City", "-Keywords", f.name],
                                  capture_output=True, text=True).stdout)[0]
print("=== 下載的 JPG 內的 IPTC/XMP"); [print(f"  {k}: {v}") for k, v in m.items() if k != "SourceFile"]
check(m.get("Caption-Abstract") == c and m.get("Description") == c, "IPTC 圖說 = 伺服器上的圖說")
check(m.get("Label") == "Select" and m.get("By-line") == "李攝影", "Label=Select、By-line=李攝影")
check("王小明" in str(m.get("PersonInImage")), "PersonInImage")
log = [json.loads(l) for l in open(meta_log)]
print("=== 對 Meta API 的請求", [(l["name"], l["images"], l["max_edge"]) for l in log])
check(log[0]["n"] == 1 and len([l for l in log if l["name"] == "burst_selection"]) == 4, "429 之後有重試（階段一 3 組 + 1 次重送）")
check(all(not l["problems"] for l in log), "請求格式都符合")
check(max(l["max_edge"] for l in log if l["name"] == "burst_selection") <= 512, "階段一縮圖 ≤ 512px")
check(all(l["max_edge"] <= 1536 for l in log if l["name"] == "photo_caption"), "階段二 ≤ 1536px")
check(sorted(l["images"] for l in log if l["name"] == "burst_selection")[-1] == 5, "連拍 5 張一次送")
print("\n結果：", "全部通過" if not fails else f"{len(fails)} 項失敗")
sys.exit(1 if fails else 0)
