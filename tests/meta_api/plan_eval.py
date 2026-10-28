#!/usr/bin/env python3
"""拍攝計劃對照實驗的評分：比較 results/<label>/results.json 裡精選照片的圖說。

  python tests/meta_api/plan_eval.py --set saki plan-off-r1 plan-off-r2 plan-on-r1 plan-on-r2
"""
import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "示範Coser（飾示範角色甲）"   # 系統會清掉中文旁的空格
TRAP = ("另一位Coser", "示範角色乙")
OUTDOOR, INDOOR = re.compile("戶外|室外|庭園|公園|石橋|池塘"), re.compile("室內|攝影棚")


def score(frames):
    pk = [f for f in frames if f["pick"] and f.get("caption")]
    prop = [f for f in pk if f["group"] in ("g01", "g02") and ("傘" in f["caption"] or "扇" in f["caption"])]
    prop_ok = sum("傘" in f["caption"] and "扇" not in f["caption"] for f in prop)
    named = sum(NAME in f["caption"].replace(" ", "") for f in pk)
    style_bad = sum("和風" in f["caption"] or "和服" in f["caption"] for f in pk)   # 服裝是中式，寫成日式算錯
    trap = sum(any(t in f["caption"] for t in TRAP) for f in pk)
    leak = sum(any("未經" in r for r in (f.get("review") or [])) for f in pk)
    scene_n = scene_bad = 0
    for f in pk:
        if f["group"] in ("g05", "g06"):
            scene_n += 1; scene_bad += bool(OUTDOOR.search(f["caption"]))
        elif f["group"] in ("g03", "g04"):
            scene_n += 1; scene_bad += bool(INDOOR.search(f["caption"]))
    review = sum(bool(f.get("needs_review")) for f in pk)
    return {"圖說數": len(pk), "道具正確": f"{prop_ok}/{len(prop)}", "名字填入": f"{named}/{len(pk)}",
            "誤套陷阱人物": trap, "模型直接寫名字": leak, "場景寫錯": f"{scene_bad}/{scene_n}",
            "服裝寫成日式": style_bad, "需確認": f"{review}/{len(pk)}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True)
    ap.add_argument("labels", nargs="+")
    a = ap.parse_args()
    base = HERE / "sets" / a.set / "results"
    rows, detail = [], []
    for lb in a.labels:
        fr = json.loads((base / lb / "results.json").read_text(encoding="utf-8"))["frames"]
        s = score(fr)
        calls = json.loads((base / lb / "calls.json").read_text(encoding="utf-8"))
        s["費用 US$"] = round(sum(c["in"] for c in calls) / 1e6 * 1.25 + sum(c["out"] for c in calls) / 1e6 * 4.25, 4)
        rows.append((lb, s))
        detail.append((lb, [(f["file"], f["caption"], f.get("review")) for f in fr if f["pick"] and f.get("caption")]))
    keys = list(rows[0][1])
    L = ["# 拍攝計劃對照實驗", "", "| 這次 | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
    L += [f"| {lb} | " + " | ".join(str(s[k]) for k in keys) + " |" for lb, s in rows]
    L += ["", "名字填入 = 圖說裡有「" + NAME + "」；誤套陷阱人物 = 寫了計劃裡沒出現在照片的人；"
          "場景寫錯 = 室內照寫成戶外、戶外照寫成室內；服裝寫成日式 = 中式服裝寫成和風 / 和服。", ""]
    for lb, caps in detail:
        L.append(f"## {lb}")
        L += [f"- {fn}：{c}" + (f"（需確認：{'；'.join(r)}）" if r else "") for fn, c, r in caps]
        L.append("")
    out = base / "plan_compare.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:4 + len(rows)]))
    print(f"\n完整結果：{out}")


if __name__ == "__main__":
    main()
