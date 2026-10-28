# Meta Model API 實測：2026_06_30_Saki星街貓棚

- 模型 `muse-spark-1.2`，reasoning `low`，題材描述 `cosplay portrait photoshoot (one cosplayer)`，時間 2026-10-28 07:07
- 6 組、30 張；所有照片送出前已抹除 metadata 並檢查
- 參考星等 = 相簿原本的星等（Prism / 相機內評分，不是人工答案）

## 總結

| 指標 | 數值 |
|---|---|
| AI 第一名 = 參考星等最高的那張（星等有差異的 4 組） | 1/4 |
| AI 精選（1~3 張）裡有參考星等最高的 | 2/4 |
| 組內排序一致性（Spearman ρ 平均，3 組） | 0.14 |
| 全部照片 AI 分數 vs 參考星等（Spearman ρ） | 0.62 |
| AI 精選裡有你選的 | 尚未填 human_pick |
| 階段一延遲 p50 / p95（6 次） | 7.8 / 8.9 秒 |
| 階段二延遲 p50 / p95（12 次） | 6.0 / 7.9 秒 |
| token 輸入 / 輸出 | 35,779 / 20,983 |
| 費用（US$1.25 / $4.25 每百萬 token） | $0.1339，每張 $0.00446，每 3,000 張約 $13.39 |

## g01（3 張，13.6 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g01_01.jpg | DSC08652.JPG | 1 | 2.6 | 1 | ◆1 | over_exposed, subject_cropped, under_exposed |
| g01_02.jpg | DSC08653.JPG | 1 | 1.55 | 1 |  | over_exposed, subject_cropped, under_exposed |
| g01_03.jpg | DSC08654.JPG | 1 | 1.6 | 1 |  | over_exposed, under_exposed, subject_cropped |

動作類型：人像
- g01_01.jpg 描述：一名Coser手持紅色摺扇站在幽暗的拱形磚砌長廊中擺拍。（攝影：測試／SnapPipe）（需確認：無運動隊伍及背號資訊，角色扮演肖像且無名單可對照，僅依可見外觀標示）

## g02（4 張，13.9 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g02_01.jpg | DSC08699.JPG | 2 | 1.0 | 1 | ◆1 | motion_blur_subject, face_blocked, eyes_closed, eyes_closed |
| g02_02.jpg | DSC08700.JPG | 2 | 1.0 | 1 |  | subject_cropped, subject_cropped, face_blocked |
| g02_03.jpg | DSC08701.JPG | 1 | 1.0 | 1 |  | motion_blur_subject, face_blocked, eyes_closed |
| g02_04.jpg | DSC08702.JPG | 3 | 1.0 | 1 |  | face_blocked, subject_cropped, subject_cropped |

動作類型：關鍵動作
- g02_01.jpg 描述：一名Coser在傳統木造廊道內手持紅色摺扇擺出姿勢。（攝影：測試／SnapPipe）（需確認：影像存在明顯動態模糊與失焦，人臉與服裝細節不清晰，無法準確判讀球衣號碼與動作細節）

## g03（8 張，14.3 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g03_01.jpg | DSC08761.JPG | 3 | 3.34 | 1 |  | subject_cropped |
| g03_02.jpg | DSC08762.JPG | 3 | 4.23 | 2 |  | subject_cropped |
| g03_03.jpg | DSC08763.JPG | 3 | 5.13 | 2 |  | subject_cropped |
| g03_04.jpg | DSC08764.JPG | 3 | 1.0 | 1 |  | out_of_focus, motion_blur_subject, subject_cropped |
| g03_05.jpg | DSC08765.JPG | 3 | 1.0 | 1 |  | out_of_focus, motion_blur_subject, subject_cropped |
| g03_06.jpg | DSC08766.JPG | 4 | 7.94 | 4 | ◆3 |  |
| g03_07.jpg | DSC08767.JPG | 4 | 8.19 | 4 | ◆2 |  |
| g03_08.jpg | DSC08768.JPG | 4 | 9.1 | 5 | ◆1 |  |

動作類型：人像；組內 Spearman ρ = 0.85
- g03_06.jpg 描述：一名Coser身著黑紅漸層和風服飾走在庭園石橋上進行肖像拍攝。（攝影：測試／SnapPipe）
- g03_07.jpg 描述：一名Coser身穿黑紅配色的和風長袍走下公園石橋的階梯進行人像拍攝。（攝影：測試／SnapPipe）
- g03_08.jpg 描述：一名Coser身穿黑色與紅色服裝在戶外石橋上進行人像擺拍。（攝影：測試／SnapPipe）（需確認：cosplay_portrait_non_sport_no_number_or_team_applicable）

## g04（7 張，16.3 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g04_01.jpg | DSC08773.JPG | 3 | 4.49 | 2 |  | subject_cropped, subject_cropped |
| g04_02.jpg | DSC08774.JPG | 3 | 4.5 | 2 |  | subject_cropped, subject_cropped |
| g04_03.jpg | DSC08775.JPG | 3 | 5.1 | 2 |  | subject_cropped, subject_cropped |
| g04_04.jpg | DSC08776.JPG | 3 | 5.35 | 2 |  | subject_cropped, subject_cropped |
| g04_05.jpg | DSC08777.JPG | 3 | 6.24 | 3 | ◆3 | subject_cropped, subject_cropped |
| g04_06.jpg | DSC08778.JPG | 3 | 7.17 | 4 | ◆1 | subject_cropped, subject_cropped |
| g04_07.jpg | DSC08779.JPG | 3 | 7.08 | 4 | ◆2 | subject_cropped, subject_cropped |

動作類型：人像
- g04_05.jpg 描述：一名Coser身著黑紅漸層古裝走在庭園石橋上進行人像寫真拍攝。（攝影：測試／SnapPipe）
- g04_06.jpg 描述：一名Coser身著黑紅配色的服裝走在公園池塘邊的石橋階梯上。（攝影：測試／SnapPipe）
- g04_07.jpg 描述：一名Coser身穿黑紅色古風服裝走在池畔石橋上進行人像拍攝。（攝影：測試／SnapPipe）

## g05（3 張，12.4 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g05_01.jpg | DSC08917.JPG | 5 | 5.78 | 3 |  | over_exposed, over_exposed |
| g05_02.jpg | DSC08918.JPG | 3 | 8.35 | 4 | ◆1 | over_exposed |
| g05_03.jpg | DSC08919.JPG | 3 | 7.66 | 4 |  | over_exposed |

動作類型：人像；組內 Spearman ρ = -0.87
- g05_02.jpg 描述：一名Coser在金色龍紋圓形雕飾前側身站立並以手輕扶紅色墨鏡擺拍肖像。（攝影：測試／SnapPipe）

## g06（5 張，16.3 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g06_01.jpg | DSC08979.JPG | 3 | 1.0 | 1 |  | out_of_focus, motion_blur_subject, face_blocked, face_blocked, face_blocked, face_blocked, face_blocked, face_blocked |
| g06_02.jpg | DSC08980.JPG | 4 | 3.95 | 1 |  | face_blocked, face_blocked, face_blocked, face_blocked, face_blocked, face_blocked, face_blocked, face_blocked |
| g06_03.jpg | DSC08981.JPG | 4 | 6.7 | 3 | ◆2 | face_blocked, face_blocked, face_blocked, face_blocked, face_blocked, face_blocked, face_blocked, face_blocked, face_blocked, face_blocked, face_blocked |
| g06_04.jpg | DSC08982.JPG | 4 | 7.46 | 4 | ◆1 | face_blocked, face_blocked, face_blocked |
| g06_05.jpg | DSC08983.JPG | 5 | 6.48 | 3 | ◆3 | face_blocked, face_blocked, face_blocked |

動作類型：人像；組內 Spearman ρ = 0.45
- g06_03.jpg 描述：一名Coser身穿黑色唐裝斜靠在木椅上擺拍，背景為金色龍紋圓雕與燈籠。（攝影：測試／SnapPipe）（需確認：cosplay portrait non-sport context no roster jersey number not applicable）
- g06_04.jpg 描述：一名Coser手持煙桿倚坐在裝飾有金色龍紋背景前的木椅上擺出姿勢。（攝影：測試／SnapPipe）
- g06_05.jpg 描述：一名Coser身著黑色中式服裝、戴紅色圓形墨鏡，手持細長菸桿斜倚在中式雕花木椅上進行肖像拍攝。（攝影：測試／SnapPipe）
