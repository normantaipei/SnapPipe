# SnapPipe

**體育新聞攝影的即時回傳系統。** 快門按下幾秒後，照片已經上傳備份、完成符合新聞倫理的校色、由 Meta AI 選出連拍中的最佳瞬間、辨識球員並草擬圖說，編輯檯只要確認就能發稿。

Meta Global AI Developer Hackathon 2026 參賽專案。

## 文件

- [設計文件 Design Document（中文）](docs/DESIGN.md)
- [Application Draft（English）](docs/APPLICATION.md)

## 架構概要

```
相機（FTPS）──────────────────────────▶ ┐
相機（純 FTP）────────────────────────▶ ├ port 21 ┐
相機（純 FTP）──FTP──▶ Pi（FTPS 中繼）─▶ ┘          ├─ SnapPipe 伺服器 ──▶ 編輯檯（人工確認）──▶ FTP / CMS
相機（無 FTP）──USB──▶ Pi（USB 轉送）──── HTTPS ──┘   ├─ 校色（只做整體調整）
                                                       ├─ Meta AI 階段一：連拍比較選片
             記憶卡即緩衝，Pi 只負責轉送               ├─ Meta AI 階段二：號碼 → 名單 → 圖說草稿
                                                       └─ 寫入 IPTC/XMP
```

目標：從快門到「可發稿的照片與圖說草稿」少於 60 秒。

支援多台相機同時使用（含同型號機身）：每張照片依機身序號標明拍攝相機、攝影師與機位，並可依相機、攝影師或球員分類匯出。
