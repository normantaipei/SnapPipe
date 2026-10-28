#!/usr/bin/env python3
"""
跨模型比較：讀 sets/<set>/results/ 底下每次 run 的 results.json + calls.json，輸出一張比較表。

  python tests/meta_api/compare.py --set saki [--prefix cmp-]      → sets/<set>/results/compare.md

同一模型跑多次（label 結尾 -r1、-r2…）會合併計算，並算出兩次之間的穩定度。
準確度用三種角度看（這組照片沒有完整的人工答案）：
  1. 明顯案例：sets/<set>/expect.json 裡人工確認過、答案明顯的檢核點
  2. 參考星等：相簿原本的星等（Prism 自動評分，只能當弱參考）
  3. 共識：所有模型所有次數的第一名多數決；跟共識一樣代表判斷不偏離大家
"""

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from meta_api_test import price_of  # noqa: E402


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


def spearman(a, b):
    if len(a) < 3 or len(set(a)) < 2 or len(set(b)) < 2:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = statistics.mean(ra), statistics.mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else None


def top1(frames):
    """每組的第一名：rank 1 的那張。"""
    out = {}
    for f in frames:
        if f["rank"] == 1:
            out[f["group"]] = f["file"]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True)
    ap.add_argument("--prefix", default="cmp-")
    a = ap.parse_args()
    set_dir = HERE / "sets" / a.set
    expect = json.loads((set_dir / "expect.json").read_text(encoding="utf-8")) if (set_dir / "expect.json").exists() else {}

    runs = defaultdict(list)          # model → [(label, results, calls)]
    for d in sorted((set_dir / "results").glob(a.prefix + "*")):
        if not (d / "results.json").exists():
            continue
        res = json.loads((d / "results.json").read_text(encoding="utf-8"))
        calls = json.loads((d / "calls.json").read_text(encoding="utf-8"))
        runs[res["model"]].append((d.name, res, calls))
    if not runs:
        sys.exit("找不到結果，先跑 run.sh run --label cmp-<模型>-r1")

    all_tops = defaultdict(list)
    for model, rs in runs.items():
        for _, res, _ in rs:
            for g, f in top1(res["frames"]).items():
                all_tops[g].append(f)
    consensus = {g: Counter(v).most_common(1)[0][0] for g, v in all_tops.items()}

    rows, detail = [], []
    for model, rs in sorted(runs.items()):
        p_in, p_out = price_of(model)
        n_photos = len(rs[0][1]["frames"])
        costs, s1, s2, checks_ok, checks_n, rho_ref, cons, caps, reviews, picks, fails = [], [], [], 0, 0, [], 0, 0, 0, 0, 0
        prop_ok = prop_n = 0
        cp = expect.get("caption_prop")
        n_groups = 0
        for label, res, calls in rs:
            fr = res["frames"]
            tin = sum(c["in"] for c in calls)
            tout = sum(c["out"] for c in calls)
            costs.append(tin / 1e6 * p_in + tout / 1e6 * p_out)
            s1 += [c["sec"] for c in calls if c["name"] == "burst_selection"]
            s2 += [c["sec"] for c in calls if c["name"] == "photo_caption"]
            tops = top1(fr)
            by_file = {f["file"]: f for f in fr}
            for g, ok in expect.get("top_in", {}).items():
                checks_n += 1
                checks_ok += tops.get(g) in ok
            for chk in expect.get("issue_on", []):
                for fn in chk["files"]:
                    checks_n += 1
                    checks_ok += bool(set(by_file[fn]["issues"]) & set(chk["issue"]))
            r = spearman([f["score"] for f in fr], [f["ref_stars"] for f in fr])
            if r is not None:
                rho_ref.append(r)
            cons += sum(tops.get(g) == f for g, f in consensus.items())
            n_groups += len(consensus)
            pk = [f for f in fr if f["pick"]]
            picks += len(pk)
            caps += sum(1 for f in pk if f["caption"])
            fails += sum(1 for f in pk if not f["caption"])
            reviews += sum(1 for f in pk if f["needs_review"])
            if cp:
                for f in pk:
                    c = f["caption"] or ""
                    if f["group"] in cp["groups"] and (cp["right"] in c or cp["wrong"] in c):
                        prop_n += 1
                        prop_ok += cp["right"] in c and cp["wrong"] not in c
        # 穩定度：第 1 次和第 2 次比
        stab_top = stab_rho = None
        if len(rs) >= 2:
            f1, f2 = rs[0][1]["frames"], rs[1][1]["frames"]
            t1, t2 = top1(f1), top1(f2)
            stab_top = sum(t1.get(g) == t2.get(g) for g in t1) / max(len(t1), 1)
            stab_rho = spearman([f["score"] for f in f1], [f["score"] for f in f2])
        cost = statistics.mean(costs)
        rows.append({
            "model": model, "runs": len(rs), "cost_photo": cost / n_photos, "cost_3000": cost / n_photos * 3000,
            "s1_p50": statistics.median(s1) if s1 else None, "s2_p50": statistics.median(s2) if s2 else None,
            "checks": f"{checks_ok}/{checks_n}", "checks_pct": checks_ok / max(checks_n, 1),
            "rho_ref": statistics.mean(rho_ref) if rho_ref else None, "consensus": cons / max(n_groups, 1),
            "stab_top": stab_top, "stab_rho": stab_rho, "picks": picks / len(rs), "cap_fail": fails,
            "review": reviews / max(picks, 1), "prop": f"{prop_ok}/{prop_n}" if prop_n else "—",
        })
        # 每組第一名、第一張精選的圖說
        for label, res, _ in rs:
            tops = top1(res["frames"])
            caps_by = {f["file"]: f["caption"] for f in res["frames"] if f["rank"] == 1}
            detail.append((model, label, tops, caps_by))

    fmt = lambda v, p=2: "—" if v is None else f"{v:.{p}f}"
    pct = lambda v: "—" if v is None else f"{v * 100:.0f}%"
    L = [f"# 跨模型比較：{a.set}", "",
         "明顯案例 = expect.json 的人工檢核點；參考ρ = AI 分數與 Prism 星等的 Spearman；共識 = 第一名跟所有模型多數決相同的比例；"
         "穩定 = 同模型兩次跑第一名相同的比例 / 分數 Spearman；圖說道具正確 = expect.json caption_prop 的檢查。", "",
         "| 模型 | 次數 | 每張費用 | 每 3,000 張 | 選片延遲 p50 | 圖說延遲 p50 | 明顯案例 | 參考ρ | 共識 | 穩定（第一名 / 分數ρ） | 每次精選數 | 圖說道具正確 | 圖說需確認 | 圖說失敗 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["cost_photo"]):
        L.append(f"| `{r['model']}` | {r['runs']} | ${r['cost_photo']:.5f} | ${r['cost_3000']:.2f} | {fmt(r['s1_p50'], 1)}s | "
                 f"{fmt(r['s2_p50'], 1)}s | {r['checks']}（{pct(r['checks_pct'])}） | {fmt(r['rho_ref'])} | {pct(r['consensus'])} | "
                 f"{pct(r['stab_top'])} / {fmt(r['stab_rho'])} | {r['picks']:.1f} | {r['prop']} | {pct(r['review'])} | {r['cap_fail']} |")
    L += ["", "## 共識第一名", "", " / ".join(f"{g}: {f}（{Counter(all_tops[g])[f]}/{len(all_tops[g])}）"
                                               for g, f in sorted(consensus.items())), "", "## 各次的第一名與圖說", ""]
    for model, label, tops, caps_by in detail:
        L.append(f"### {label}")
        for g in sorted(tops):
            L.append(f"- {g} → {tops[g]}：{caps_by.get(tops[g]) or '（無圖說）'}")
        L.append("")
    out = set_dir / "results" / "compare.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:6 + len(rows)]))
    print(f"\n完整比較：{out}")


if __name__ == "__main__":
    main()
