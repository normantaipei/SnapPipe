# Meta Model API 實測：2026_06_30_Saki星街貓棚

- 模型 `muse-spark-1.1`，reasoning `low`，題材描述 `cosplay portrait photoshoot (one cosplayer)`，時間 2026-10-28 07:06
- 6 組、30 張；所有照片送出前已抹除 metadata 並檢查
- 參考星等 = 相簿原本的星等（Prism / 相機內評分，不是人工答案）

## 總結

| 指標 | 數值 |
|---|---|
| AI 第一名 = 參考星等最高的那張（星等有差異的 4 組） | 1/4 |
| AI 精選（1~3 張）裡有參考星等最高的 | 2/4 |
| 組內排序一致性（Spearman ρ 平均，3 組） | 0.14 |
| 全部照片 AI 分數 vs 參考星等（Spearman ρ） | 0.53 |
| AI 精選裡有你選的 | 尚未填 human_pick |
| 階段一延遲 p50 / p95（6 次） | 4.4 / 5.4 秒 |
| 階段二延遲 p50 / p95（13 次） | 5.0 / 6.3 秒 |
| token 輸入 / 輸出 | 38,048 / 17,914 |
| 費用（US$1.25 / $4.25 每百萬 token） | $0.1237，每張 $0.00412，每 3,000 張約 $12.37 |

## g01（3 張，9.3 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g01_01.jpg | DSC08652.JPG | 1 | 5.8 | 3 | ◆1 | subject_cropped, under_exposed |
| g01_02.jpg | DSC08653.JPG | 1 | 1.0 | 1 |  | subject_cropped, face_blocked, face_blocked, under_exposed, subject_cropped, subject_cropped |
| g01_03.jpg | DSC08654.JPG | 1 | 1.0 | 1 |  | subject_cropped, face_blocked, under_exposed, subject_cropped |

動作類型：人像
- g01_01.jpg 描述：一名Coser手持紅色摯扇走在傳統建築的黑暗廊道中。（攝影：測試／SnapPipe）

## g02（4 張，10.5 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g02_01.jpg | DSC08699.JPG | 2 | 1.0 | 1 | ◆1 | motion_blur_subject, face_blocked, face_blocked, subject_cropped |
| g02_02.jpg | DSC08700.JPG | 2 | 1.0 | 1 |  | subject_cropped, subject_cropped, subject_cropped, face_blocked, subject_cropped, subject_cropped |
| g02_03.jpg | DSC08701.JPG | 1 | 1.0 | 1 |  | motion_blur_subject, motion_blur_subject, face_blocked, face_blocked, face_blocked |
| g02_04.jpg | DSC08702.JPG | 3 | 1.0 | 1 |  | face_blocked, subject_cropped, face_blocked, face_blocked |

動作類型：人像
- g02_01.jpg 描述：一名Coser在傳統建築廊道中手持紅色摺扇擺姿勢拍攝人像。（攝影：測試／SnapPipe）（需確認：cosplay_portrait_not_sport_context；image_blur_motions；no_roster_name_rule）

## g03（8 張，11.1 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g03_01.jpg | DSC08761.JPG | 3 | 3.34 | 1 |  | subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g03_02.jpg | DSC08762.JPG | 3 | 4.23 | 2 |  | subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g03_03.jpg | DSC08763.JPG | 3 | 4.48 | 2 |  | subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g03_04.jpg | DSC08764.JPG | 3 | 4.32 | 2 |  | subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g03_05.jpg | DSC08765.JPG | 3 | 4.31 | 2 |  | subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g03_06.jpg | DSC08766.JPG | 4 | 6.04 | 3 | ◆3 | subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g03_07.jpg | DSC08767.JPG | 4 | 6.94 | 3 | ◆2 | subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g03_08.jpg | DSC08768.JPG | 4 | 8.1 | 4 | ◆1 | subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped |

動作類型：人像；組內 Spearman ρ = 0.85
- g03_06.jpg 描述：一名Coser身穿黑紅漸層服裝走在庭園石橋上進行人像寫真拍攝。（攝影：測試／SnapPipe）
- g03_07.jpg 描述：一名Coser身著黑紅相間的長袍在公園石橋上行走擺拍。（攝影：測試／SnapPipe）
- g03_08.jpg 描述：一名Coser身穿黑色旗袍式服裝搭配藍色假髮走在公園石橋上擺拍。（攝影：測試／SnapPipe）

## g04（7 張，11.3 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g04_01.jpg | DSC08773.JPG | 3 | 4.49 | 2 |  | subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g04_02.jpg | DSC08774.JPG | 3 | 4.5 | 2 |  | subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g04_03.jpg | DSC08775.JPG | 3 | 5.35 | 2 |  | subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g04_04.jpg | DSC08776.JPG | 3 | 6.25 | 3 |  | subject_cropped, subject_cropped, subject_cropped |
| g04_05.jpg | DSC08777.JPG | 3 | 6.24 | 3 | ◆3 | subject_cropped, subject_cropped |
| g04_06.jpg | DSC08778.JPG | 3 | 7.17 | 4 | ◆2 | subject_cropped |
| g04_07.jpg | DSC08779.JPG | 3 | 7.98 | 4 | ◆1 | subject_cropped |

動作類型：人像
- g04_05.jpg 描述：一名Coser身穿黑紅漸層長袍與藍色假髮，走在庭園石橋上。（攝影：測試／SnapPipe）
- g04_06.jpg 描述：一名Coser身穿黑紅漸層長袍與藍色假髮走下公園內的石橋階梯。（攝影：測試／SnapPipe）
- g04_07.jpg 描述：一名Coser身穿黑紅配色的服裝走在公園的石橋上。（攝影：測試／SnapPipe）

## g05（3 張，10.4 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g05_01.jpg | DSC08917.JPG | 5 | 2.28 | 1 |  | motion_blur_subject, face_blocked, subject_cropped |
| g05_02.jpg | DSC08918.JPG | 3 | 8.85 | 5 | ◆1 |  |
| g05_03.jpg | DSC08919.JPG | 3 | 6.66 | 3 | ◆2 | face_blocked |

動作類型：人像；組內 Spearman ρ = -0.87
- g05_02.jpg 描述：一名Coser在金色龍紋圓形雕飾前側身擺拍並輕扶紅色墨鏡。（攝影：測試／SnapPipe）
- g05_03.jpg 描述：一名Coser側身站在一面金色龍鳳雕花圓飾前，手扶紅色墨鏡擺出肖像姿勢。（攝影：測試／SnapPipe）

## g06（5 張，8.6 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g06_01.jpg | DSC08979.JPG | 3 | 1.82 | 1 |  | face_blocked, motion_blur_subject, subject_cropped |
| g06_02.jpg | DSC08980.JPG | 4 | 4.6 | 2 |  | subject_cropped, under_exposed, subject_cropped |
| g06_03.jpg | DSC08981.JPG | 4 | 8.85 | 5 | ◆1 |  |
| g06_04.jpg | DSC08982.JPG | 4 | 6.31 | 3 | ◆2 | face_blocked |
| g06_05.jpg | DSC08983.JPG | 5 | 6.23 | 3 | ◆3 | face_blocked |

動作類型：人像；組內 Spearman ρ = 0.45
- g06_03.jpg 描述：一名Coser身穿黑色中式服裝、戴著紅色圓形墨鏡，頂著藍色假髮靠坐在木椅上擺出姿勢拍照。（攝影：測試／SnapPipe）
- g06_04.jpg 描述：一名Coser戴著紅色墨鏡、留著藍色長髮，身穿黑色中式服裝，手持煙管斜坐在木椅上擺拍。（攝影：測試／SnapPipe）
- g06_05.jpg 描述：一名Coser身穿黑色唐裝坐在木椅上，手持長煙管擺出姿勢進行寫真拍攝。（攝影：測試／SnapPipe）
