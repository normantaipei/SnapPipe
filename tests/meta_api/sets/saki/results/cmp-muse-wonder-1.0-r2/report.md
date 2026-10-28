# Meta Model API 實測：2026_06_30_Saki星街貓棚

- 模型 `muse-wonder-1.0`，reasoning `low`，題材描述 `cosplay portrait photoshoot (one cosplayer)`，時間 2026-10-28 07:09
- 6 組、30 張；所有照片送出前已抹除 metadata 並檢查
- 參考星等 = 相簿原本的星等（Prism / 相機內評分，不是人工答案）

## 總結

| 指標 | 數值 |
|---|---|
| AI 第一名 = 參考星等最高的那張（星等有差異的 4 組） | 2/4 |
| AI 精選（1~3 張）裡有參考星等最高的 | 2/4 |
| 組內排序一致性（Spearman ρ 平均，4 組） | 0.43 |
| 全部照片 AI 分數 vs 參考星等（Spearman ρ） | 0.66 |
| AI 精選裡有你選的 | 尚未填 human_pick |
| 階段一延遲 p50 / p95（6 次） | 8.3 / 12.6 秒 |
| 階段二延遲 p50 / p95（11 次） | 8.1 / 9.4 秒 |
| token 輸入 / 輸出 | 33,514 / 14,053 |
| 費用（US$4 / $20 每百萬 token） | $0.4151，每張 $0.01384，每 3,000 張約 $41.51 |

## g01（3 張，13.6 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g01_01.jpg | DSC08652.JPG | 1 | 3.65 | 1 | ◆1 | subject_cropped, eyes_closed, under_exposed, subject_cropped |
| g01_02.jpg | DSC08653.JPG | 1 | 1.3 | 1 |  | subject_cropped, eyes_closed, under_exposed, subject_cropped |
| g01_03.jpg | DSC08654.JPG | 1 | 2.0 | 1 |  | subject_cropped, eyes_closed, under_exposed, subject_cropped |

動作類型：人像
- g01_01.jpg 描述：一名Coser手持紅色油紙傘，站在昏暗的迴廊中側身擺姿勢進行人像外拍。（攝影：測試／SnapPipe）（需確認：未提供名單且非體育賽事，無球隊與球衣號碼可辨識）

## g02（4 張，18.1 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g02_01.jpg | DSC08699.JPG | 2 | 1.24 | 1 | ◆1 | motion_blur_subject, face_blocked |
| g02_02.jpg | DSC08700.JPG | 2 | 1.0 | 1 |  | subject_cropped |
| g02_03.jpg | DSC08701.JPG | 1 | 1.0 | 1 |  | motion_blur_subject, subject_cropped |
| g02_04.jpg | DSC08702.JPG | 3 | 3.45 | 1 |  |  |

動作類型：人像；組內 Spearman ρ = 0.83
- g02_01.jpg 描述：一名Coser手持紅色摺扇，站在傳統建築的黃色燈籠旁進行人像拍攝。（攝影：測試／SnapPipe）（需確認：畫面中的人物略為模糊，且無名單可供核對身分與造型資訊。；此為角色扮演人像拍攝，非體育賽事畫面，球隊與球衣號碼不適用。）

## g03（8 張，15.8 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g03_01.jpg | DSC08761.JPG | 3 | 3.34 | 1 |  | subject_cropped |
| g03_02.jpg | DSC08762.JPG | 3 | 4.23 | 2 |  | subject_cropped |
| g03_03.jpg | DSC08763.JPG | 3 | 4.48 | 2 |  | subject_cropped |
| g03_04.jpg | DSC08764.JPG | 3 | 5.22 | 2 |  | subject_cropped |
| g03_05.jpg | DSC08765.JPG | 3 | 5.21 | 2 |  | subject_cropped |
| g03_06.jpg | DSC08766.JPG | 4 | 6.29 | 3 | ◆3 | subject_cropped |
| g03_07.jpg | DSC08767.JPG | 4 | 8.19 | 4 | ◆2 |  |
| g03_08.jpg | DSC08768.JPG | 4 | 9.1 | 5 | ◆1 |  |

動作類型：關鍵動作；組內 Spearman ρ = 0.85
- g03_06.jpg 描述：一名Coser身穿黑紅漸層服裝站在涼亭旁的石橋階梯上擺姿勢拍照。（攝影：測試／SnapPipe）（需確認：No roster provided and the subject is a single cosplayer, not a sports player with a visible team or jersey number.）
- g03_07.jpg 描述：一名Coser身穿黑紅服裝並戴著藍色假髮，走下涼亭旁的石橋階梯擺出姿勢。（攝影：測試／SnapPipe）（需確認：照片內容為角色扮演人像外拍而非體育賽事，無法判定主客隊與球衣號碼，且名單未提供，均需編輯確認）
- g03_08.jpg 描述：一名Coser身穿藍色假髮與黑紅色服裝走在石橋上進行角色扮演人像拍攝。（攝影：測試／SnapPipe）（需確認：Game data is cosplay not sports; no roster provided; person identity and character identity cannot be verified from the image.）

## g04（7 張，18.9 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g04_01.jpg | DSC08773.JPG | 3 | 1.0 | 1 |  | subject_cropped, eyes_closed, face_blocked |
| g04_02.jpg | DSC08774.JPG | 3 | 2.75 | 1 |  | face_blocked, eyes_closed |
| g04_03.jpg | DSC08775.JPG | 3 | 5.1 | 2 |  | eyes_closed |
| g04_04.jpg | DSC08776.JPG | 3 | 6.0 | 3 |  | eyes_closed |
| g04_05.jpg | DSC08777.JPG | 3 | 6.89 | 3 | ◆2 | eyes_closed |
| g04_06.jpg | DSC08778.JPG | 3 | 8.82 | 5 | ◆1 |  |
| g04_07.jpg | DSC08779.JPG | 3 | 4.93 | 2 | ◆3 | motion_blur_subject, eyes_closed |

動作類型：關鍵動作
- g04_05.jpg 描述：一名Coser站在池畔石橋上面對鏡頭擺出角色扮演造型。（攝影：測試／SnapPipe）（需確認：非體育賽事畫面：無球隊、球衣號碼或名單可供辨識；僅能依畫面描述角色扮演外拍，需編輯確認人物與角色身分）
- g04_06.jpg 描述：一名Coser身穿黑紅服裝、頭戴藍色長髮，沿著池塘旁的石橋階梯向下走。（攝影：測試／SnapPipe）（需確認：Game data indicates cosplay portrait photoshoot with no roster provided, so identity, character, and team/jersey information cannot be verified from the image.；team and jersey are not applicable or not visible; jersey set to null.）
- g04_07.jpg 描述：一名Coser穿著黑紅服裝、戴著藍色假髮走下池畔石橋階梯擺姿勢。（攝影：測試／SnapPipe）（需確認：非體育賽事畫面，無球衣號碼與主客隊資訊，且無選手名單可供對照）

## g05（3 張，15.7 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g05_01.jpg | DSC08917.JPG | 5 | 4.93 | 2 |  | subject_cropped, motion_blur_subject |
| g05_02.jpg | DSC08918.JPG | 3 | 9.1 | 5 | ◆1 |  |
| g05_03.jpg | DSC08919.JPG | 3 | 7.41 | 4 |  | subject_cropped |

動作類型：人像；組內 Spearman ρ = -0.87
- g05_02.jpg 描述：一名Coser戴著紅色圓形眼鏡並以手輕觸鏡框，在金色龍紋圓形背景前側身擺姿勢。（攝影：測試／SnapPipe）（需確認：Game data indicates cosplay portrait photoshoot with no roster provided, so identity, team and jersey number cannot be determined from the image.；The subject is not in a sports uniform and no jersey number is visible.）

## g06（5 張，22.4 秒）

| 檔案 | 原檔名 | 參考★ | AI 分數 | AI★ | 精選 | 問題 |
|---|---|---|---|---|---|---|
| g06_01.jpg | DSC08979.JPG | 3 | 4.17 | 2 |  | subject_cropped |
| g06_02.jpg | DSC08980.JPG | 4 | 5.1 | 2 |  | subject_cropped |
| g06_03.jpg | DSC08981.JPG | 4 | 6.3 | 3 | ◆2 | subject_cropped |
| g06_04.jpg | DSC08982.JPG | 4 | 7.06 | 4 |  | subject_cropped |
| g06_05.jpg | DSC08983.JPG | 5 | 7.63 | 4 | ◆1 | eyes_closed |

動作類型：人像；組內 Spearman ρ = 0.89
- g06_03.jpg 描述：一名Coser戴著紅色圓形墨鏡、身穿黑色服裝，坐在金色龍紋裝飾前擺姿勢拍照。（攝影：測試／SnapPipe）（需確認：No roster provided; person must not be named；Image is a cosplay portrait, not a sports action photo; team and jersey are not applicable）
- g06_05.jpg 描述：一名Coser戴著紅色圓形墨鏡、頂著藍色長假髮，身穿黑色紅邊服裝坐在木椅上，右手持長桿擺拍。（攝影：測試／SnapPipe）（需確認：roster未提供且非球賽畫面，無法確認身分與隊伍編號，僅能以服裝特徵描述；畫面無可辨識球衣號碼）
