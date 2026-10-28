# Meta Model API 實測：2026_06_30_Saki星街貓棚

- 模型 `muse-spark-1.1`，reasoning `low`，題材描述 `cosplay portrait photoshoot (one cosplayer)`，時間 2026-10-28 07:08
- 6 組、30 張；所有照片送出前已抹除 metadata 並檢查
- 參考星等 = 相簿原本的星等（Prism / 相機內評分，不是人工答案）

## 總結

| 指標 | 數值 |
|---|---|
| AI 第一名 = 參考星等最高的那張（星等有差異的 4 組） | 2/4 |
| AI 精選（1~3 張）裡有參考星等最高的 | 2/4 |
| 組內排序一致性（Spearman ρ 平均，3 組） | 0.29 |
| 全部照片 AI 分數 vs 參考星等（Spearman ρ） | 0.65 |
| AI 精選裡有你選的 | 尚未填 human_pick |
| 階段一延遲 p50 / p95（9 次） | 4.0 / 6.0 秒 |
| 階段二延遲 p50 / p95（13 次） | 4.1 / 6.2 秒 |
| token 輸入 / 輸出 | 44,197 / 25,314 |
| 費用（US$1.25 / $4.25 每百萬 token） | $0.1628，每張 $0.00543，每 3,000 張約 $16.28 |

## g01（3 張，8.4 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g01_01.jpg | DSC08652.JPG | 1 | 2.25 | 1 | ◆1 | under_exposed, face_blocked, face_blocked, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g01_02.jpg | DSC08653.JPG | 1 | 1.0 | 1 |  | under_exposed, face_blocked, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g01_03.jpg | DSC08654.JPG | 1 | 1.25 | 1 |  | under_exposed, face_blocked, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped, subject_cropped |

動作類型：人像
- g01_01.jpg 描述：一名Coser手持紅色紙傘站在昏暗的拱形廊道中擺拍。（攝影：測試／SnapPipe）

## g02（4 張，6.6 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g02_01.jpg | DSC08699.JPG | 2 | 1.0 | 1 | ◆1 | motion_blur_subject, face_blocked |
| g02_02.jpg | DSC08700.JPG | 2 | 1.0 | 1 |  | subject_cropped, face_blocked, face_blocked, motion_blur_subject |
| g02_03.jpg | DSC08701.JPG | 1 | 1.0 | 1 |  | motion_blur_subject, face_blocked |
| g02_04.jpg | DSC08702.JPG | 3 | 1.0 | 1 |  | face_blocked, subject_cropped, motion_blur_subject |

動作類型：人像
- g02_01.jpg 描述：一名Coser手持紅色扇子在掛著燈籠的傳統建築廊道前進行人像拍攝。（攝影：測試／SnapPipe）

## g03（8 張，20.0 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g03_01.jpg | DSC08761.JPG | 3 | 3.34 | 1 |  | subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g03_02.jpg | DSC08762.JPG | 3 | 4.23 | 2 |  | subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g03_03.jpg | DSC08763.JPG | 3 | 4.48 | 2 |  | subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g03_04.jpg | DSC08764.JPG | 3 | 4.32 | 2 |  | subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g03_05.jpg | DSC08765.JPG | 3 | 4.31 | 2 |  | subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g03_06.jpg | DSC08766.JPG | 4 | 6.29 | 3 | ◆3 | subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g03_07.jpg | DSC08767.JPG | 4 | 7.19 | 4 | ◆2 | subject_cropped, subject_cropped, subject_cropped, subject_cropped |
| g03_08.jpg | DSC08768.JPG | 4 | 8.1 | 4 | ◆1 | subject_cropped, subject_cropped, subject_cropped, subject_cropped |

動作類型：人像；組內 Spearman ρ = 0.85
- g03_06.jpg 描述：一名Coser身穿黑紅漸層服裝走在公園的石橋上進行人像拍攝。（攝影：測試／SnapPipe）
- g03_07.jpg 描述：一名Coser身穿黑色與紅色為主的和風服裝，走下公園中的石橋階梯進行人像拍攝。（攝影：測試／SnapPipe）
- g03_08.jpg 描述：一名Coser穿著黑紅相間的服裝走在戶外公園池塘上的石橋。（攝影：測試／SnapPipe）

## g04（7 張，15.1 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g04_01.jpg | DSC08773.JPG | 3 | 3.59 | 1 |  | subject_cropped, subject_cropped |
| g04_02.jpg | DSC08774.JPG | 3 | 3.93 | 1 |  | subject_cropped, subject_cropped |
| g04_03.jpg | DSC08775.JPG | 3 | 5.1 | 2 |  | subject_cropped |
| g04_04.jpg | DSC08776.JPG | 3 | 5.67 | 3 |  | subject_cropped |
| g04_05.jpg | DSC08777.JPG | 3 | 6.07 | 3 | ◆3 | motion_blur_subject |
| g04_06.jpg | DSC08778.JPG | 3 | 8.3 | 4 | ◆2 |  |
| g04_07.jpg | DSC08779.JPG | 3 | 7.23 | 4 | ◆1 | motion_blur_subject |

動作類型：人像
- g04_05.jpg 描述：一名Coser穿著黑色與紅色漸層的角色扮演服裝走在庭園石橋上進行人像拍攝。（攝影：測試／SnapPipe）
- g04_06.jpg 描述：一名Coser身穿黑紅相間的角色扮演服裝走下庭園中的石橋階梯。（攝影：測試／SnapPipe）
- g04_07.jpg 描述：一名Coser身著黑紅相間的古風服裝並戴著藍色假髮，走在公園池塘邊的石橋上。（攝影：測試／SnapPipe）

## g05（3 張，8.4 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g05_01.jpg | DSC08917.JPG | 5 | 5.78 | 3 |  | over_exposed, over_exposed |
| g05_02.jpg | DSC08918.JPG | 3 | 8.35 | 4 | ◆1 | over_exposed, over_exposed |
| g05_03.jpg | DSC08919.JPG | 3 | 7.66 | 4 | ◆2 | over_exposed, over_exposed, over_exposed |

動作類型：人像；組內 Spearman ρ = -0.87
- g05_02.jpg 描述：一名Coser在金色龍紋圓形雕飾前側身擺姿勢，手輕觸紅色墨鏡進行人像拍攝。（攝影：測試／SnapPipe）
- g05_03.jpg 描述：一名Coser在金色龍紋圓形雕飾背景前側身站立並以手輕扶紅色墨鏡擺拍。（攝影：測試／SnapPipe）

## g06（5 張，8.4 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g06_01.jpg | DSC08979.JPG | 3 | 1.0 | 1 |  | out_of_focus, subject_cropped, motion_blur_subject |
| g06_02.jpg | DSC08980.JPG | 4 | 1.6 | 1 |  | under_exposed, subject_cropped, motion_blur_subject, face_blocked |
| g06_03.jpg | DSC08981.JPG | 4 | 6.45 | 3 | ◆2 | subject_cropped, over_exposed |
| g06_04.jpg | DSC08982.JPG | 4 | 8.06 | 4 | ◆3 |  |
| g06_05.jpg | DSC08983.JPG | 5 | 8.88 | 5 | ◆1 |  |

動作類型：人像；組內 Spearman ρ = 0.89
- g06_03.jpg 描述：一名Coser戴著紅色圓形墨鏡、頂著藍色假髮，身穿黑色中式服裝坐在木椅上擺出姿勢拍攝肖像。（攝影：測試／SnapPipe）（需確認：cosplay_portrait_not_sport_jersey_unavailable；roster_missing_so_names_redacted）
- g06_04.jpg 描述：一名Coser身穿黑色中式服裝斜倚在木椅上，手持長桿擺出姿勢拍照。（攝影：測試／SnapPipe）
- g06_05.jpg 描述：一名Coser坐在雕花木椅上，手持長煙桿擺出姿勢進行人像拍攝。（攝影：測試／SnapPipe）（需確認：Game type is non-sport, team and jersey not applicable, box estimate provided）
