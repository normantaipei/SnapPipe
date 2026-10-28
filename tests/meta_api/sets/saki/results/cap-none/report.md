# Meta Model API 實測：2026_06_30_Saki星街貓棚

- 模型 `muse-spark-1.3`，reasoning `low`，題材描述 `cosplay portrait photoshoot (one cosplayer)`，時間 2026-10-28 23:30
- 6 組、30 張；所有照片送出前已抹除 metadata 並檢查
- 參考星等 = 相簿原本的星等（Prism / 相機內評分，不是人工答案）

## 總結

| 指標 | 數值 |
|---|---|
| AI 第一名 = 參考星等最高的那張（星等有差異的 4 組） | 2/4 |
| AI 精選（1~3 張）裡有參考星等最高的 | 3/4 |
| 組內排序一致性（Spearman ρ 平均，4 組） | 0.37 |
| 全部照片 AI 分數 vs 參考星等（Spearman ρ） | 0.71 |
| AI 精選裡有你選的 | 尚未填 human_pick |
| 階段一延遲 p50 / p95（6 次） | 4.9 / 5.9 秒 |
| 階段二延遲 p50 / p95（0 次） | — |
| token 輸入 / 輸出 | 10,224 / 5,620 |
| 費用（US$1.25 / $4.25 每百萬 token） | $0.0367，每張 $0.00122，每 3,000 張約 $3.67 |

## g01（3 張，4.4 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g01_01.jpg | DSC08652.JPG | 1 | 4.1 | 2 | ◆1 | under_exposed |
| g01_02.jpg | DSC08653.JPG | 1 | 1.0 | 1 |  | under_exposed, face_blocked, out_of_focus |
| g01_03.jpg | DSC08654.JPG | 1 | 1.6 | 1 |  | under_exposed, face_blocked |

動作類型：人像

## g02（4 張，5.2 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g02_01.jpg | DSC08699.JPG | 2 | 1.0 | 1 |  | motion_blur_subject, out_of_focus |
| g02_02.jpg | DSC08700.JPG | 2 | 1.0 | 1 |  | subject_cropped, face_blocked |
| g02_03.jpg | DSC08701.JPG | 1 | 1.0 | 1 |  | motion_blur_subject, out_of_focus |
| g02_04.jpg | DSC08702.JPG | 3 | 3.5 | 1 | ◆1 | face_blocked |

動作類型：人像；組內 Spearman ρ = 0.82

## g03（8 張，5.8 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g03_01.jpg | DSC08761.JPG | 3 | 4.59 | 2 |  |  |
| g03_02.jpg | DSC08762.JPG | 3 | 5.48 | 2 |  |  |
| g03_03.jpg | DSC08763.JPG | 3 | 5.48 | 2 |  |  |
| g03_04.jpg | DSC08764.JPG | 3 | 3.72 | 1 |  | out_of_focus |
| g03_05.jpg | DSC08765.JPG | 3 | 3.71 | 1 |  | out_of_focus |
| g03_06.jpg | DSC08766.JPG | 4 | 7.94 | 4 | ◆3 |  |
| g03_07.jpg | DSC08767.JPG | 4 | 8.84 | 5 | ◆2 |  |
| g03_08.jpg | DSC08768.JPG | 4 | 9.1 | 5 | ◆1 |  |

動作類型：人像；組內 Spearman ρ = 0.85

## g04（7 張，6.4 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g04_01.jpg | DSC08773.JPG | 3 | 5.49 | 2 |  |  |
| g04_02.jpg | DSC08774.JPG | 3 | 5.83 | 3 |  |  |
| g04_03.jpg | DSC08775.JPG | 3 | 6.35 | 3 |  |  |
| g04_04.jpg | DSC08776.JPG | 3 | 6.67 | 3 |  |  |
| g04_05.jpg | DSC08777.JPG | 3 | 7.57 | 4 | ◆3 |  |
| g04_06.jpg | DSC08778.JPG | 3 | 8.49 | 4 | ◆1 |  |
| g04_07.jpg | DSC08779.JPG | 3 | 5.58 | 3 | ◆2 | out_of_focus |

動作類型：人像

## g05（3 張，5.0 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g05_01.jpg | DSC08917.JPG | 5 | 7.18 | 4 |  |  |
| g05_02.jpg | DSC08918.JPG | 3 | 8.85 | 5 | ◆1 |  |
| g05_03.jpg | DSC08919.JPG | 3 | 8.16 | 4 |  |  |

動作類型：人像；組內 Spearman ρ = -0.87

## g06（5 張，4.7 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g06_01.jpg | DSC08979.JPG | 3 | 3.57 | 1 |  | out_of_focus |
| g06_02.jpg | DSC08980.JPG | 4 | 5.1 | 2 |  | subject_cropped |
| g06_03.jpg | DSC08981.JPG | 4 | 7.2 | 4 | ◆3 | subject_cropped |
| g06_04.jpg | DSC08982.JPG | 4 | 8.71 | 5 | ◆1 |  |
| g06_05.jpg | DSC08983.JPG | 5 | 7.98 | 4 | ◆2 |  |

動作類型：人像；組內 Spearman ρ = 0.67
