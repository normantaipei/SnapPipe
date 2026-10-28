# Meta Model API 實測

用真的活動照片跑 SnapPipe 正式版的 Meta AI 分析器（`worker/analyzers/meta_ai.py`，同一套 prompt、schema、評分與圖說組裝），
量選片準確度、穩定度、延遲和費用，並比較 Meta Model API 上所有能讀圖的模型。

照片不在 repo 裡（是真人照片，只留在本機）；這裡放的是程式、每組照片的參考答案（`manifest.json`、`expect.json`）和每次實測的結果。

## 檔案

| 路徑 | 內容 |
|---|---|
| `meta_api_test.py` | `prepare`：從返圖站相簿挑連拍組、**抹掉所有 metadata** 後存檔；`run`：呼叫 API、輸出報告 |
| `compare.py` | 讀多次 run 的結果，輸出跨模型比較表 `results/compare.md` |
| `run.sh` | 用 worker 的 venv 執行 `meta_api_test.py` |
| `sets/saki/manifest.json` | 實驗組：6 組連拍、30 張；相簿原本的星等只當參考，**不會送給 API** |
| `sets/saki/expect.json` | 人工看圖確認、答案明顯的檢核點 |
| `sets/saki/results/<label>/` | 每次實測：`report.md`（逐張結果）、`results.json`、`calls.json`（每次請求的延遲、token 與模型原始回應） |
| `sets/saki/results/compare.md` | 跨模型比較 |

## 怎麼跑

```bash
tests/meta_api/run.sh prepare --album "https://<返圖站>/a/<分享碼>" --set saki --auto 6
tests/meta_api/run.sh run --set saki --dry-run
tests/meta_api/run.sh run --set saki --model muse-spark-1.3 --person "一名 Coser" --label cmp-muse-spark-1.3-r1
worker/.venv/bin/python tests/meta_api/compare.py --set saki
```

金鑰從環境變數 `META_API_KEY` 或 `worker/.env` 讀，不會寫進結果。送出前會再檢查一次：每張圖重新編碼後的位元組裡不能有 Exif / XMP / IPTC 區塊。

## 2026-10-28 實測結果（Saki 外拍，30 張，每個模型跑 2 次，reasoning `low`）

| 模型 | 每張費用 | 一場估計* | 明顯案例 | 兩次第一名一致 | 選片延遲 p50 | 圖說延遲 p50 |
|---|---|---|---|---|---|---|
| `muse-spark-1.3` | $0.00404 | **$5.9** | **15/16** | **100%** | 5.6 秒 | 5.3 秒 |
| `muse-spark-1.1` | $0.00478 | $6.2 | 15/16 | 83% | 4.1 秒 | 4.6 秒 |
| `muse-spark-1.2` | $0.00468 | $7.0 | 12/16 | 67% | 7.0 秒 | 5.8 秒 |
| `muse-wonder-1.0` | $0.01378 | $21.9 | 11/16 | 100% | 8.0 秒 | 7.8 秒 |

\* 一場 = 3,000 張照片、300 張精選寫圖說。`muse-spark-1.3`：選片每張約 $0.0013，圖說每張精選約 $0.0066。

**結論：用 `muse-spark-1.3`。** 最便宜、兩次結果完全一致、明顯案例錯最少；`muse-wonder-1.0` 貴 3.4 倍但沒有比較準；`muse-spark-1.2` 最不穩。

- 「明顯案例」是 `expect.json` 的檢核點：g01 三張都偏暗、g02 有三張晃到、g01 / g03 的最佳幀很明顯。
- 相簿原本的星等是 Prism 自動評分，各模型和它的 Spearman 只有 0.55–0.63，只能當弱參考；要量真正的準確度，請在 `manifest.json` 的 `human_pick` 填人工答案。
- 四個模型都常把紅色油紙傘說成摺扇：圖說裡的道具細節仍要人工確認。
- `muse-wonder-1.0` 的圖說 100% 被標「需確認」，是因為描述 prompt 是給體育比賽寫的，它會如實回報「沒有隊伍與背號」，不是模型本身的問題。
- 沒測 `-contributor` 方案：那會讓 Meta 拿送出的照片訓練模型，照片裡有第三方。
- `results/run1-low/` 是修正前的第一次實測（當時沒名單時圖說會寫「一名球員」、整組糊掉也選三張精選），留著對照。
