#!/usr/bin/env python3
"""
Meta Model API 實測：用真的照片跑正式版的 meta_ai 分析器（同一套 prompt、schema、評分、圖說組裝），
量選片和人工 / 參考星等的一致性、延遲、token 與費用。

兩個步驟：

  1. prepare  從返圖站相簿挑幾組連拍下載，**抹掉所有 metadata** 後放進 sets/<名稱>/
               - 先依 EXIF 方向把畫素轉正（抹掉方向標記後直拍照才不會躺著），轉成 sRGB，重新存成不帶任何
                 EXIF / XMP / IPTC / ICC / 註解的 JPG（長邊 2048，送 API 時還會再縮到 512 / 1536）
               - 檔名改成 g01_01.jpg 這種流水號，原檔名也不透露
               - 用 exiftool 檢查，只要還剩任何 metadata 就停下來
               - 原本的星等、標籤只記在 manifest.json 當參考答案，絕不送出
  2. run      對每一組呼叫 Meta Model API（階段一選片；選中的再跑階段二寫描述），輸出 report.md 與原始回應
               送出前再檢查一次：每張圖重新編碼後的位元組裡不能有 Exif / XMP / IPTC 區塊

用法（在 repo 根目錄）：
  tests/meta_api/run.sh prepare --album "https://<返圖站>/a/<分享碼>" --set saki --auto 6
  tests/meta_api/run.sh prepare --album "…" --set saki --groups DSC08979-DSC08983 DSC08917-DSC08919
  tests/meta_api/run.sh run --set saki --dry-run          # 不呼叫 API：只檢查 metadata、印出會送什麼
  tests/meta_api/run.sh run --set saki                    # 真的呼叫（金鑰讀 META_API_KEY 或 worker/.env）
  tests/meta_api/run.sh run --set saki --reasoning medium --label medium

人工答案：在 sets/<名稱>/manifest.json 每組的 "human_pick" 填你會選的檔名（例 "g01_05.jpg"，可填多個），
報告會多一欄「AI 與你的一致率」。沒填就只和相簿原本的星等比（那是 Prism / 相機內評分，不是人工）。
"""

import argparse
import datetime as dt
import io
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests
from PIL import Image, ImageCms, ImageOps

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "worker"))

SETS = HERE / "sets"
# US$ / 百萬 token（輸入, 輸出），dev.meta.ai/docs/pricing-rate-limits 的公開牌價
PRICES = {"muse-wonder-1.0": (4.00, 20.00), "muse-spark-1.3": (1.25, 4.25), "muse-spark-1.2": (1.25, 4.25),
          "muse-spark-1.1": (1.25, 4.25), "muse-spark-1.3-contributor": (0.10, 0.20),
          "muse-spark-1.2-contributor": (0.10, 0.20)}


def price_of(model: str):
    return PRICES.get(model, PRICES["muse-spark-1.3"])
ALLOWED_GROUPS = {"ExifTool", "System", "File", "JFIF", "Composite"}   # 抹除後只能剩這些（檔案本身的屬性）
LEAK_MARKERS = [b"Exif\x00\x00", b"http://ns.adobe.com/xap", b"Photoshop 3.0", b"8BIM", b"ICC_PROFILE"]
EDGE = 2048


def log(msg=""):
    print(msg, flush=True)


# ---------- prepare：挑照片、下載、抹 metadata ----------

def album_api(url: str):
    """https://host/a/<key>?v=2 → (https://host, key)"""
    u = urlsplit(url)
    m = re.search(r"/a/([\w-]+)", u.path)
    if not m:
        sys.exit(f"看不懂的相簿網址：{url}（要像 https://host/a/<分享碼>）")
    return f"{u.scheme}://{u.netloc}", m.group(1)


def bursts(photos, gap: float):
    def ts(p):
        return dt.datetime.fromisoformat(p["taken_at"]).timestamp() if p.get("taken_at") else None
    ps = sorted((p for p in photos if p.get("taken_at")), key=lambda p: (p["taken_at"], p["name"]))
    groups = []
    for p in ps:
        if groups and ts(p) - ts(groups[-1][-1]) <= gap:
            groups[-1].append(p)
        else:
            groups.append([p])
    return groups


def auto_pick(groups, n: int):
    """挑 n 組 3~8 張的連拍，盡量涵蓋：有 5 星的、星等差距大的、整組都低分的、整組星等一樣的。"""
    cands = [g for g in groups if 3 <= len(g) <= 8]
    stars = lambda g: [p["stars"] or 0 for p in g]
    picked = []

    def take(key, reverse=True):
        for g in sorted(cands, key=key, reverse=reverse):
            if g not in picked:
                picked.append(g)
                return
    take(lambda g: max(stars(g)))                          # 有最高星的
    take(lambda g: max(stars(g)) - min(stars(g)))          # 組內差距最大
    take(lambda g: sum(stars(g)) / len(g), reverse=False)  # 整組最低分
    take(lambda g: (max(stars(g)) == min(stars(g)), len(g)))   # 整組一樣（看 AI 能不能分出高下）
    take(len)                                              # 最長的連拍
    rest = [g for g in cands if g not in picked]
    step = max(1, len(rest) // max(1, n - len(picked)))
    picked += rest[::step][:max(0, n - len(picked))]
    return sorted(picked[:n], key=lambda g: g[0]["taken_at"])


def by_ranges(groups, photos, ranges):
    """--groups DSC08979-DSC08983：用檔名範圍指定一組。"""
    byname = sorted(photos, key=lambda p: p["name"])
    out = []
    for r in ranges:
        a, _, b = r.partition("-")
        b = b or a
        g = [p for p in byname if a <= Path(p["name"]).stem <= b]
        if not g:
            sys.exit(f"相簿裡沒有 {r}")
        out.append(sorted(g, key=lambda p: (p.get("taken_at") or "", p["name"])))
    return out


def strip_save(src: Path, dst: Path):
    """轉正 → sRGB → 縮到長邊 2048 → 存成不帶任何 metadata 的 JPG。"""
    with Image.open(src) as im:
        img = ImageOps.exif_transpose(im)
        icc = im.info.get("icc_profile")
        img = img.convert("RGB")
    if icc:
        try:
            img = ImageCms.profileToProfile(img, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                                            ImageCms.createProfile("sRGB"), outputMode="RGB")
        except (ImageCms.PyCMSError, OSError):
            pass
    img.thumbnail((EDGE, EDGE), Image.LANCZOS)
    img.save(dst, "JPEG", quality=92, optimize=True)          # 不傳 exif / icc_profile / comment = 一律不寫
    subprocess.run(["exiftool", "-q", "-overwrite_original", "-all=", str(dst)], check=True)   # 保險再清一次


def leftover_metadata(paths) -> dict:
    """exiftool 掃描：回傳 {檔名: [殘留的 tag]}；空的 dict = 全部乾淨。"""
    r = subprocess.run(["exiftool", "-json", "-a", "-G1", "-u", *map(str, paths)], capture_output=True, text=True)
    bad = {}
    for d in json.loads(r.stdout or "[]"):
        keys = [k for k in d if k != "SourceFile" and k.split(":")[0] not in ALLOWED_GROUPS]
        if keys:
            bad[Path(d["SourceFile"]).name] = keys
    return bad


def cmd_prepare(a):
    base, key = album_api(a.album)
    r = requests.get(f"{base}/api/share/{key}", timeout=30)
    r.raise_for_status()
    album = r.json()
    photos = album["photos"]
    groups = bursts(photos, a.gap)
    chosen = by_ranges(groups, photos, a.groups) if a.groups else auto_pick(groups, a.auto)
    out = SETS / a.set
    img_dir = out / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    cache = Path(tempfile.gettempdir()) / "snappipe-meta-test-cache"
    cache.mkdir(exist_ok=True)
    log(f"相簿「{album['title']}」{len(photos)} 張 → 挑 {len(chosen)} 組、{sum(map(len, chosen))} 張 → {out}")

    manifest = {"album_title": album["title"], "source": "返圖站相簿（分享連結不記錄）", "created": dt.datetime.now().isoformat(timespec="seconds"),
                "note": "ref_stars / ref_tags / original_name 只在本機當參考答案，不會送給 API", "groups": []}
    for gi, g in enumerate(chosen, 1):
        t0 = dt.datetime.fromisoformat(g[0]["taken_at"])
        frames = []
        for fi, p in enumerate(g, 1):
            raw = cache / f"{p['sha']}.jpg"
            if not raw.exists():
                with requests.get(f"{base}/media/{key}/o/{p['sha']}", stream=True, timeout=120) as resp:
                    resp.raise_for_status()
                    tmp = raw.with_suffix(".part")
                    with open(tmp, "wb") as f:
                        for chunk in resp.iter_content(1 << 20):
                            f.write(chunk)
                    tmp.replace(raw)
            name = f"g{gi:02d}_{fi:02d}.jpg"
            strip_save(raw, img_dir / name)
            frames.append({"file": name, "offset_sec": round((dt.datetime.fromisoformat(p["taken_at"]) - t0).total_seconds(), 3),
                           "original_name": p["name"], "ref_stars": p["stars"],
                           "ref_tags": [t for t in p["tags"] if t.isascii()][:8]})
        manifest["groups"].append({"id": f"g{gi:02d}", "frames": frames, "human_pick": []})
        log(f"  g{gi:02d}  {len(g)} 張  {g[0]['name']}…{g[-1]['name']}  參考星等 {[p['stars'] for p in g]}")

    bad = leftover_metadata(sorted(img_dir.glob("*.jpg")))
    if bad:
        sys.exit(f"❌ 還有 metadata 沒抹乾淨：{json.dumps(bad, ensure_ascii=False)[:500]}")
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"✅ metadata 檢查通過：{len(list(img_dir.glob('*.jpg')))} 張只剩檔案本身的屬性（大小、尺寸、JFIF）")
    log(f"   參考答案在 {out / 'manifest.json'}；要比對你自己的選擇，在每組的 human_pick 填檔名")


# ---------- run：呼叫 Meta Model API ----------

def load_key():
    if os.environ.get("META_API_KEY"):
        return os.environ["META_API_KEY"]
    env = REPO / "worker" / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("META_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def check_payload(body: dict):
    """送出前最後一道：每張圖的位元組裡不能有 metadata 區塊。"""
    import base64
    for c in body["messages"][1]["content"]:
        if c.get("type") == "image_url":
            data = base64.b64decode(c["image_url"]["url"].split(",", 1)[1])
            hit = [m for m in LEAK_MARKERS if m in data]
            if hit:
                raise SystemExit(f"❌ 要送出的影像裡有 metadata 區塊 {hit}，停止")


def spearman(xs, ys):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return num / den if den else None


def cmd_run(a):
    set_dir = SETS / a.set
    manifest = json.loads((set_dir / "manifest.json").read_text(encoding="utf-8"))
    img_dir = set_dir / "images"
    groups = manifest["groups"][:a.max_groups] if a.max_groups else manifest["groups"]
    paths = [img_dir / f["file"] for g in groups for f in g["frames"]]
    bad = leftover_metadata(paths)
    if bad:
        sys.exit(f"❌ 這些檔案還有 metadata，先重跑 prepare：{list(bad)[:5]}")
    log(f"✅ {len(paths)} 張 metadata 檢查通過")

    key = load_key() or ("dry-run" if a.dry_run else "")
    if not key:
        sys.exit("沒有 META_API_KEY：設環境變數，或填在 worker/.env")
    games = Path(tempfile.mkdtemp(prefix="snappipe-games-"))
    (games / "default.toml").write_text(
        f'[game]\nsport = "{a.sport}"\nlang = "{a.lang}"\ncreator = "測試"\ncredit = "SnapPipe"\ncaptions = true\n'
        + (f'person = "{a.person}"\n' if a.person else "")
        + (Path(a.plan).read_text(encoding="utf-8") if a.plan else ""), encoding="utf-8")
    cfg = {"META_API_KEY": key, "META_MODEL": a.model, "META_REASONING": a.reasoning, "GAMES_DIR": str(games),
           "WRITE_IPTC": "0", "CAPTION": "0" if a.stage1_only else "1", "META_TIMEOUT": "180"}
    if a.base:
        cfg["META_API_BASE"] = a.base
    if a.caption_min_stars != "":
        cfg["CAPTION_MIN_STARS"] = a.caption_min_stars
    from analyzers.meta_ai import MetaAIAnalyzer
    an = MetaAIAnalyzer(cfg, log=lambda m: log(m))

    calls = []
    real_post = an.client._post

    def recorded(body):
        check_payload(body)
        n_img = sum(1 for c in body["messages"][1]["content"] if c.get("type") == "image_url")
        name = body["response_format"]["json_schema"]["name"]
        if a.dry_run:
            calls.append({"name": name, "images": n_img, "sec": 0, "in": 0, "out": 0})
            raise _DryRun(name, n_img)
        t0 = time.time()
        d = real_post(body)
        u = d.get("usage") or {}
        calls.append({"name": name, "images": n_img, "sec": round(time.time() - t0, 2),
                      "in": int(u.get("prompt_tokens") or 0), "out": int(u.get("completion_tokens") or 0),
                      "raw": (d.get("choices") or [{}])[0].get("message", {}).get("content")})
        return d
    an.client._post = recorded

    label = a.label or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = set_dir / "results" / label
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for g in groups:
        items = []
        for f in g["frames"]:
            job = {"album": "meta-test", "filename": f["file"], "photo_id": f"{g['id']}{f['file']}".ljust(12, "0"),
                   "taken_at": (dt.datetime(2026, 1, 1) + dt.timedelta(seconds=f["offset_sec"])).isoformat(timespec="milliseconds"),
                   "camera": None}
            items.append((img_dir / f["file"], job))
        log(f"\n── {g['id']}：{len(items)} 張")
        try:
            t0 = time.time()
            res = an.analyze_burst(items)
            sec = time.time() - t0
        except _DryRun as e:
            log(f"   （dry-run）會送出 {e.name}：{e.n} 張 512px 縮圖；不呼叫 API")
            continue
        rows.append((g, res, sec))
        for f, r in zip(g["frames"], res):
            mark = "◆" if r.ai.get("pick") else " "
            log(f"   {mark} {f['file']}  AI {r.aesthetic:>4}  ★{r.stars}  參考★{f['ref_stars']}  {','.join(r.ai.get('issues', []))}"
                + (f"\n       {r.caption}" if r.caption else ""))
    if a.dry_run:
        log("\n（dry-run 結束：metadata 檢查通過，沒有呼叫 API）")
        return
    (out / "calls.json").write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding="utf-8")
    # 逐張結果（給跨模型比較用：tests/meta_api/compare.py）
    per = [{"group": g["id"], "file": f["file"], "ref_stars": f["ref_stars"], "human_pick": f["file"] in g.get("human_pick", []),
            "score": r.aesthetic, "stars": r.stars, "pick": bool(r.ai.get("pick")), "rank": r.ai.get("rank"),
            "issues": r.ai.get("issues", []), "moment": r.ai.get("moment"), "caption": r.caption, "headline": r.headline,
            "needs_review": r.ai.get("needs_review"), "review": r.ai.get("review_reasons"), "group_sec": round(sec, 2),
            "players": r.ai.get("players")}
           for g, res, sec in rows for f, r in zip(g["frames"], res)]
    (out / "results.json").write_text(json.dumps({"model": a.model, "reasoning": a.reasoning, "frames": per},
                                                 ensure_ascii=False, indent=2), encoding="utf-8")
    report = make_report(manifest, rows, calls, a)
    (out / "report.md").write_text(report, encoding="utf-8")
    log(f"\n報告：{out / 'report.md'}")


class _DryRun(Exception):
    def __init__(self, name, n):
        super().__init__(name)
        self.name, self.n = name, n


def make_report(manifest, rows, calls, a) -> str:
    L = [f"# Meta Model API 實測：{manifest['album_title']}", "",
         f"- 模型 `{a.model}`，reasoning `{a.reasoning}`，題材描述 `{a.sport}`，時間 {dt.datetime.now():%Y-%m-%d %H:%M}",
         f"- {len(rows)} 組、{sum(len(g['frames']) for g, _, _ in rows)} 張；所有照片送出前已抹除 metadata 並檢查",
         "- 參考星等 = 相簿原本的星等（Prism / 相機內評分，不是人工答案）", ""]
    top1 = top1_any = n_ref = 0
    human_hit = human_n = 0
    rhos, all_ai, all_ref = [], [], []
    for g, res, sec in rows:
        ref = [f["ref_stars"] or 0 for f in g["frames"]]
        ai = [r.aesthetic for r in res]
        picks = [i for i, r in enumerate(res) if r.ai.get("pick")]
        first = next((i for i, r in enumerate(res) if r.ai.get("rank") == 1), picks[0] if picks else None)
        best_ref = [i for i, s in enumerate(ref) if s == max(ref)]
        if len(set(ref)) > 1:
            n_ref += 1
            top1 += first in best_ref
            top1_any += any(i in best_ref for i in picks)
        rho = spearman(ai, ref)
        if rho is not None:
            rhos.append(rho)
        all_ai += ai
        all_ref += ref
        if g.get("human_pick"):
            human_n += 1
            human_hit += any(g["frames"][i]["file"] in g["human_pick"] for i in picks)
        L += [f"## {g['id']}（{len(ref)} 張，{sec:.1f} 秒）", "",
              "| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |", "|---|---|---|---|---|---|---|"]
        for f, r in zip(g["frames"], res):
            L.append(f"| {f['file']} | {f['original_name']} | {f['ref_stars']} | {r.aesthetic} | {r.stars} | "
                     f"{'◆' + str(r.ai.get('rank')) if r.ai.get('pick') else ''} | {', '.join(r.ai.get('issues', []))} |")
        L.append("")
        L.append(f"動作類型：{res[0].ai.get('moment_label')}" + (f"；組內 Spearman ρ = {rho:.2f}" if rho is not None else ""))
        for f, r in zip(g["frames"], res):
            if r.caption:
                L.append(f"- {f['file']} 描述：{r.caption}" + ("（需確認：" + "；".join(r.ai.get("review_reasons", [])) + "）"
                                                            if r.ai.get("needs_review") else ""))
        L.append("")
    s1 = [c for c in calls if c["name"] == "burst_selection"]
    s2 = [c for c in calls if c["name"] == "photo_caption"]
    tin, tout = sum(c["in"] for c in calls), sum(c["out"] for c in calls)
    p_in, p_out = price_of(a.model)
    cost = tin / 1e6 * p_in + tout / 1e6 * p_out
    n_photos = sum(len(g["frames"]) for g, _, _ in rows)

    def lat(cs):
        v = sorted(c["sec"] for c in cs)
        return f"{statistics.median(v):.1f} / {v[min(len(v) - 1, int(len(v) * 0.95))]:.1f} 秒" if v else "—"
    summary = ["## 總結", "", "| 指標 | 數值 |", "|---|---|",
               f"| AI 第一名 = 參考星等最高的那張（星等有差異的 {n_ref} 組） | {top1}/{n_ref} |",
               f"| AI 精選（1~3 張）裡有參考星等最高的 | {top1_any}/{n_ref} |",
               f"| 組內排序一致性（Spearman ρ 平均，{len(rhos)} 組） | {statistics.mean(rhos):.2f} |" if rhos else "| 組內排序一致性 | — |",
               f"| 全部照片 AI 分數 vs 參考星等（Spearman ρ） | {spearman(all_ai, all_ref) or 0:.2f} |",
               (f"| AI 精選裡有你選的（{human_n} 組） | {human_hit}/{human_n} |" if human_n else
                "| AI 精選裡有你選的 | 尚未填 human_pick |"),
               f"| 階段一延遲 p50 / p95（{len(s1)} 次） | {lat(s1)} |",
               f"| 階段二延遲 p50 / p95（{len(s2)} 次） | {lat(s2)} |",
               f"| token 輸入 / 輸出 | {tin:,} / {tout:,} |",
               f"| 費用（US${p_in:g} / ${p_out:g} 每百萬 token） | ${cost:.4f}，每張 ${cost / max(n_photos, 1):.5f}，每 3,000 張約 ${cost / max(n_photos, 1) * 3000:.2f} |",
               ""]
    return "\n".join(L[:6] + summary + L[6:])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="從返圖站挑照片、下載、抹 metadata")
    p.add_argument("--album", required=True, help="相簿網址 https://host/a/<分享碼>")
    p.add_argument("--set", required=True, help="實驗組名稱（存到 tests/meta_api/sets/<名稱>）")
    p.add_argument("--auto", type=int, default=6, help="自動挑幾組連拍（預設 6）")
    p.add_argument("--groups", nargs="*", help="指定檔名範圍，例 DSC08979-DSC08983（給了就不自動挑）")
    p.add_argument("--gap", type=float, default=2.0, help="拍攝間隔幾秒內算同一組（預設 2）")
    r = sub.add_parser("run", help="呼叫 Meta Model API 跑實驗組")
    r.add_argument("--set", required=True)
    r.add_argument("--dry-run", action="store_true", help="只檢查 metadata、不呼叫 API")
    r.add_argument("--stage1-only", action="store_true", help="只跑選片，不寫描述")
    r.add_argument("--model", default="muse-spark-1.3")
    r.add_argument("--reasoning", default="low", help="minimal / low / medium / high")
    r.add_argument("--sport", default="cosplay portrait photoshoot (one cosplayer)",
                   help="給模型的題材描述（體育照片就填 basketball 之類）")
    r.add_argument("--lang", default="zh")
    r.add_argument("--caption-min-stars", default="", help="只替這個星等以上的精選寫圖說（預設同 worker：4；0 = 全寫）")
    r.add_argument("--plan", default="", help="拍攝計劃（TOML 片段：[game] 的 notes 與 [[people]]），接在比賽資料後面")
    r.add_argument("--person", default="", help="認不出名字的人怎麼稱呼（例 \"一名 Coser\"；預設：一名人物）")
    r.add_argument("--max-groups", type=int, default=0)
    r.add_argument("--label", help="這次結果的資料夾名稱（預設時間戳）")
    r.add_argument("--base", help="API 網址（預設 https://api.meta.ai/v1；測試可指向模擬伺服器）")
    a = ap.parse_args()
    (cmd_prepare if a.cmd == "prepare" else cmd_run)(a)


if __name__ == "__main__":
    main()
