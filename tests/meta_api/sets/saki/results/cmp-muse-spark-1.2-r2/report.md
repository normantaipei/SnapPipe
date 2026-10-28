# Meta Model API 實測：2026_06_30_Saki星街貓棚

- 模型 `muse-spark-1.2`，reasoning `low`，題材描述 `cosplay portrait photoshoot (one cosplayer)`，時間 2026-10-28 07:08
- 6 組、30 張；所有照片送出前已抹除 metadata 並檢查
- 參考星等 = 相簿原本的星等（Prism / 相機內評分，不是人工答案）

## 總結

| 指標 | 數值 |
|---|---|
| AI 第一名 = 參考星等最高的那張（星等有差異的 4 組） | 2/4 |
| AI 精選（1~3 張）裡有參考星等最高的 | 2/4 |
| 組內排序一致性（Spearman ρ 平均，3 組） | 0.29 |
| 全部照片 AI 分數 vs 參考星等（Spearman ρ） | 0.63 |
| AI 精選裡有你選的 | 尚未填 human_pick |
| 階段一延遲 p50 / p95（6 次） | 6.8 / 7.1 秒 |
| 階段二延遲 p50 / p95（13 次） | 5.7 / 8.3 秒 |
| token 輸入 / 輸出 | 38,051 / 23,382 |
| 費用（US$1.25 / $4.25 每百萬 token） | $0.1469，每張 $0.00490，每 3,000 張約 $14.69 |

## g01（3 張，12.4 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g01_01.jpg | DSC08652.JPG | 1 | 3.75 | 1 | ◆1 | face_blocked, face_blocked, face_blocked |
| g01_02.jpg | DSC08653.JPG | 1 | 2.05 | 1 |  | face_blocked |
| g01_03.jpg | DSC08654.JPG | 1 | 3.0 | 1 |  | face_blocked |

動作類型：人像
- g01_01.jpg 描述：一名Coser手持紅色摺扇傘佇立於昏暗的拱形廊道中。（攝影：測試／SnapPipe）

## g02（4 張，13.6 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g02_01.jpg | DSC08699.JPG | 2 | 1.0 | 1 | ◆1 | motion_blur_subject, face_blocked, subject_cropped |
| g02_02.jpg | DSC08700.JPG | 2 | 1.0 | 1 |  | subject_cropped, face_blocked, motion_blur_subject |
| g02_03.jpg | DSC08701.JPG | 1 | 1.0 | 1 |  | motion_blur_subject, face_blocked, subject_cropped, out_of_focus |
| g02_04.jpg | DSC08702.JPG | 3 | 1.0 | 1 |  | motion_blur_subject, face_blocked, subject_cropped |

動作類型：人像
- g02_01.jpg 描述：一名Coser手持紅色摺扇站在傳統建築廊道中進行人像拍攝。（攝影：測試／SnapPipe）（需確認：影像呈動態模糊影響清晰度）

## g03（8 張，20.9 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g03_01.jpg | DSC08761.JPG | 3 | 4.24 | 2 |  | subject_cropped |
| g03_02.jpg | DSC08762.JPG | 3 | 4.48 | 2 |  | subject_cropped |
| g03_03.jpg | DSC08763.JPG | 3 | 5.13 | 2 |  | subject_cropped |
| g03_04.jpg | DSC08764.JPG | 3 | 3.07 | 1 |  | out_of_focus |
| g03_05.jpg | DSC08765.JPG | 3 | 3.06 | 1 |  | out_of_focus |
| g03_06.jpg | DSC08766.JPG | 4 | 7.94 | 4 | ◆3 |  |
| g03_07.jpg | DSC08767.JPG | 4 | 8.84 | 5 | ◆2 |  |
| g03_08.jpg | DSC08768.JPG | 4 | 9.75 | 5 | ◆1 |  |

動作類型：人像；組內 Spearman ρ = 0.85
- g03_06.jpg 描述：一名Coser身穿黑色與紅色漸層服飾走在公園石橋上進行角色扮演人像拍攝。（攝影：測試／SnapPipe）
- g03_07.jpg 描述：一名Coser身穿黑紅色系服裝走在庭園石橋上進行肖像拍攝。（攝影：測試／SnapPipe）
- g03_08.jpg 描述：一名Coser身穿黑紅相間服裝走在戶外庭園的石橋上進行人像拍攝。（攝影：測試／SnapPipe）

## g04（7 張，13.3 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g04_01.jpg | DSC08773.JPG | 3 | 3.59 | 1 |  | subject_cropped, subject_cropped |
| g04_02.jpg | DSC08774.JPG | 3 | 4.25 | 2 |  | subject_cropped |
| g04_03.jpg | DSC08775.JPG | 3 | 4.45 | 2 |  | subject_cropped |
| g04_04.jpg | DSC08776.JPG | 3 | 5.35 | 2 |  | subject_cropped |
| g04_05.jpg | DSC08777.JPG | 3 | 6.24 | 3 | ◆3 | subject_cropped |
| g04_06.jpg | DSC08778.JPG | 3 | 8.17 | 4 | ◆2 |  |
| g04_07.jpg | DSC08779.JPG | 3 | 7.98 | 4 | ◆1 | subject_cropped |

動作類型：關鍵動作
- g04_05.jpg 描述：一名Coser身著黑紅漸層古裝在庭園石橋上向前行走。（攝影：測試／SnapPipe）
- g04_06.jpg 描述：一名Coser身穿黑紅配色古風服飾走下公園石橋的階梯。（攝影：測試／SnapPipe）（需確認：cosplay_portrait_not_a_sport_no_team_or_jersey）
- g04_07.jpg 描述：一名Coser身穿黑紅相間服裝走在公園池塘邊的石橋上。（攝影：測試／SnapPipe）

## g05（3 張，13.1 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g05_01.jpg | DSC08917.JPG | 5 | 3.1 | 1 |  | over_exposed, face_blocked, face_blocked |
| g05_02.jpg | DSC08918.JPG | 3 | 6.45 | 3 | ◆1 | face_blocked, face_blocked |
| g05_03.jpg | DSC08919.JPG | 3 | 6.41 | 3 |  | face_blocked, face_blocked |

動作類型：人像；組內 Spearman ρ = -0.87
- g05_02.jpg 描述：一名Coser在金色龍紋圓形雕飾前側身輕扶紅色太陽眼鏡擺拍肖像。（攝影：測試／SnapPipe）（需確認：cosplay_portrait_non_sport_no_roster_requires_team_jersey_null_placeholder）

## g06（5 張，12.9 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g06_01.jpg | DSC08979.JPG | 3 | 1.0 | 1 |  | out_of_focus, motion_blur_subject, under_exposed, face_blocked |
| g06_02.jpg | DSC08980.JPG | 4 | 4.6 | 2 |  | under_exposed, subject_cropped, subject_cropped, subject_cropped |
| g06_03.jpg | DSC08981.JPG | 4 | 4.55 | 2 | ◆3 | subject_cropped, subject_cropped, subject_cropped, face_blocked |
| g06_04.jpg | DSC08982.JPG | 4 | 8.06 | 4 | ◆2 |  |
| g06_05.jpg | DSC08983.JPG | 5 | 8.88 | 5 | ◆1 |  |

動作類型：人像；組內 Spearman ρ = 0.89
- g06_03.jpg 描述：一名Coser戴著紅色墨鏡、身穿黑色中式服裝坐在木椅上於金色龍紋圓形雕飾前擺拍。（攝影：測試／SnapPipe）（需確認：unverified_identity_team_roster；generic_cosplay_portrait_no_sport_action）
- g06_04.jpg 描述：一名Coser身穿黑色中式服裝、戴著紅色墨鏡，手持長煙管倚靠在木椅上擺拍肖像。（攝影：測試／SnapPipe）
- g06_05.jpg 描述：一名Coser身著黑色中式服裝、戴著紅色墨鏡與藍色假髮，手持長菸桿斜倚在木製座椅上擺出姿勢。（攝影：測試／SnapPipe）
