# Meta Model API 實測：2026_06_30_Saki星街貓棚

- 模型 `muse-wonder-1.0`，reasoning `low`，題材描述 `cosplay portrait photoshoot (one cosplayer)`，時間 2026-10-28 07:07
- 6 組、30 張；所有照片送出前已抹除 metadata 並檢查
- 參考星等 = 相簿原本的星等（Prism / 相機內評分，不是人工答案）

## 總結

| 指標 | 數值 |
|---|---|
| AI 第一名 = 參考星等最高的那張（星等有差異的 4 組） | 2/4 |
| AI 精選（1~3 張）裡有參考星等最高的 | 2/4 |
| 組內排序一致性（Spearman ρ 平均，3 組） | 0.22 |
| 全部照片 AI 分數 vs 參考星等（Spearman ρ） | 0.43 |
| AI 精選裡有你選的 | 尚未填 human_pick |
| 階段一延遲 p50 / p95（6 次） | 8.0 / 11.0 秒 |
| 階段二延遲 p50 / p95（11 次） | 7.3 / 9.0 秒 |
| token 輸入 / 輸出 | 33,515 / 13,869 |
| 費用（US$4 / $20 每百萬 token） | $0.4114，每張 $0.01371，每 3,000 張約 $41.14 |

## g01（3 張，13.2 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g01_01.jpg | DSC08652.JPG | 1 | 6.3 | 3 | ◆1 | subject_cropped |
| g01_02.jpg | DSC08653.JPG | 1 | 1.0 | 1 |  | motion_blur_subject, subject_cropped, face_blocked |
| g01_03.jpg | DSC08654.JPG | 1 | 1.4 | 1 |  | motion_blur_subject, subject_cropped, face_blocked |

動作類型：關鍵動作
- g01_01.jpg 描述：一名Coser手持紅色折扇站在昏暗迴廊中側身望向左方。（攝影：測試／SnapPipe）（需確認：Game data lists cosplay portrait photoshoot with no roster and no sports teams or jersey numbers visible, so team and identity cannot be verified.）

## g02（4 張，19.0 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g02_01.jpg | DSC08699.JPG | 2 | 1.0 | 1 | ◆1 | motion_blur_subject, face_blocked |
| g02_02.jpg | DSC08700.JPG | 2 | 1.0 | 1 |  | subject_cropped, face_blocked |
| g02_03.jpg | DSC08701.JPG | 1 | 1.0 | 1 |  | face_blocked, motion_blur_subject |
| g02_04.jpg | DSC08702.JPG | 3 | 1.0 | 1 |  | subject_cropped, motion_blur_subject, face_blocked |

動作類型：人像
- g02_01.jpg 描述：一名Coser手持紅色摺扇，在傳統建築走廊的黃色燈籠旁擺姿勢供人像攝影。（攝影：測試／SnapPipe）（需確認：roster not provided; cannot identify person；image is motion-blurred and number not applicable/visible；non-sport cosplay portrait）

## g03（8 張，16.3 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g03_01.jpg | DSC08761.JPG | 3 | 3.34 | 1 |  | subject_cropped |
| g03_02.jpg | DSC08762.JPG | 3 | 4.23 | 2 |  | subject_cropped |
| g03_03.jpg | DSC08763.JPG | 3 | 5.13 | 2 |  | subject_cropped |
| g03_04.jpg | DSC08764.JPG | 3 | 4.72 | 2 |  | motion_blur_subject |
| g03_05.jpg | DSC08765.JPG | 3 | 4.71 | 2 |  | motion_blur_subject |
| g03_06.jpg | DSC08766.JPG | 4 | 6.29 | 3 | ◆3 | subject_cropped |
| g03_07.jpg | DSC08767.JPG | 4 | 7.19 | 4 | ◆2 | subject_cropped |
| g03_08.jpg | DSC08768.JPG | 4 | 8.1 | 4 | ◆1 | subject_cropped |

動作類型：關鍵動作；組內 Spearman ρ = 0.85
- g03_06.jpg 描述：一名Coser穿著黑紅漸層服裝、戴著藍色假髮站在石橋階梯上擺姿勢。（攝影：測試／SnapPipe）（需確認：No roster or team uniform information is provided; identity, character, and team/jersey cannot be verified from the image.）
- g03_07.jpg 描述：一名Coser身穿黑紅服裝並配戴藍色假髮，走下公園小橋階梯面向鏡頭擺姿勢。（攝影：測試／SnapPipe）（需確認：非體育賽事畫面且無名單提供，無法確認人物身分與角色名稱，需編輯核查。）
- g03_08.jpg 描述：一名Coser穿著黑紅服裝並戴著藍色假髮，走過石橋進行戶外角色扮演人像外拍。（攝影：測試／SnapPipe）（需確認：Game data lists cosplay portrait photoshoot rather than a sport, so team and jersey are not applicable and were set to unknown/null.；No roster was provided, so no name was used.）

## g04（7 張，19.9 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g04_01.jpg | DSC08773.JPG | 3 | 3.59 | 1 |  | subject_cropped |
| g04_02.jpg | DSC08774.JPG | 3 | 4.25 | 2 |  | subject_cropped |
| g04_03.jpg | DSC08775.JPG | 3 | 5.1 | 2 |  | subject_cropped |
| g04_04.jpg | DSC08776.JPG | 3 | 6.0 | 3 |  | subject_cropped |
| g04_05.jpg | DSC08777.JPG | 3 | 6.24 | 3 | ◆3 | subject_cropped |
| g04_06.jpg | DSC08778.JPG | 3 | 7.82 | 4 | ◆1 | eyes_closed |
| g04_07.jpg | DSC08779.JPG | 3 | 5.83 | 3 | ◆2 | eyes_closed, motion_blur_subject |

動作類型：關鍵動作
- g04_05.jpg 描述：一名Coser戴著藍色假髮、穿著黑紅色服裝走在池塘旁的石橋上。（攝影：測試／SnapPipe）（需確認：非體育賽事照片且無名單提供，無法確認人物身分與隊伍歸屬；人物未穿著可辨識的球衣號碼）
- g04_06.jpg 描述：一名Coser身穿黑紅服裝、配戴藍色假髮走下石橋階梯擺姿勢拍照。（攝影：測試／SnapPipe）（需確認：場景為角色扮演外拍而非體育賽事，無球隊與球衣號碼可辨識；未提供花名冊，無法確認人物身分）
- g04_07.jpg 描述：一名Coser穿著黑紅服裝並戴著藍色假髮走下池畔石階。（攝影：測試／SnapPipe）（需確認：Game data indicates cosplay portrait photoshoot rather than a sports event; no roster, team or jersey is visible.）

## g05（3 張，16.5 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g05_01.jpg | DSC08917.JPG | 5 | 4.68 | 2 |  | subject_cropped, motion_blur_subject |
| g05_02.jpg | DSC08918.JPG | 3 | 8.85 | 5 | ◆1 |  |
| g05_03.jpg | DSC08919.JPG | 3 | 6.66 | 3 |  | motion_blur_subject |

動作類型：人像；組內 Spearman ρ = -0.87
- g05_02.jpg 描述：一名Coser以藍色假髮與紅色墨鏡造型側身擺姿勢。（攝影：測試／SnapPipe）（需確認：場景為角色扮演人像攝影而非體育賽事，無隊伍與背號可辨識且無名單提供）

## g06（5 張，16.1 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g06_01.jpg | DSC08979.JPG | 3 | 2.32 | 1 |  | subject_cropped, motion_blur_subject, face_blocked |
| g06_02.jpg | DSC08980.JPG | 4 | 1.45 | 1 |  | subject_cropped, face_blocked, motion_blur_subject |
| g06_03.jpg | DSC08981.JPG | 4 | 3.95 | 1 |  | subject_cropped, face_blocked, motion_blur_subject |
| g06_04.jpg | DSC08982.JPG | 4 | 4.66 | 2 | ◆2 | subject_cropped, face_blocked |
| g06_05.jpg | DSC08983.JPG | 5 | 7.38 | 4 | ◆1 | face_blocked |

動作類型：人像；組內 Spearman ρ = 0.67
- g06_04.jpg 描述：一名Coser戴著紅色圓形墨鏡、身穿黑色服裝，坐在木椅上擺姿勢進行人像攝影。（攝影：測試／SnapPipe）（需確認：無提供名單，無法確認人物身分；非體育賽事畫面，隊伍與背號不適用需編輯確認）
- g06_05.jpg 描述：一名Coser戴著紅色圓形墨鏡、頂著藍色長髮坐在木椅上，手持長桿擺姿勢進行人像拍攝。（攝影：測試／SnapPipe）（需確認：場次資訊為角色扮演人像拍攝且未提供名單，無法確認人物身分與隊伍歸屬，請編輯核查。）
