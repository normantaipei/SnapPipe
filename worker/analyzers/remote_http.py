"""
遠端分析：把照片 POST 給任何 HTTP 服務（自己架的模型、其他線上多模態 API 的轉接層…），拿回 JSON。

設定（worker/.env）：
  REMOTE_URL       例 https://ai.example.com/analyze
  REMOTE_TOKEN     放在 Authorization: Bearer（選用）
  REMOTE_MAX_EDGE  送出前把長邊縮到這麼大（預設 1536；0 = 原圖）。縮小後再送：省頻寬，也不把全尺寸照片交出去
  REMOTE_TIMEOUT   秒（預設 120）

請求：multipart/form-data
  file  = JPG
  meta  = JSON {"album", "filename", "taken_at", "camera", "width", "height"}
回應：JSON（欄位都可省略）
  {"stars": 4, "aesthetic": 0.62, "tags": ["cosplay", "舞台"], "taken_at": "…",
   "headline": "…", "caption": "…", "extra": {...}}
"""

import io
import json
from pathlib import Path

import requests
from PIL import Image, ImageOps

from .base import Analysis, Analyzer


class RemoteHttpAnalyzer(Analyzer):
    name = "remote-http"

    def __init__(self, cfg, log=print):
        super().__init__(cfg, log)
        self.url = cfg.get("REMOTE_URL", "")
        if not self.url:
            raise SystemExit("ANALYZER=remote_http 需要 .env 的 REMOTE_URL")
        self.max_edge = int(cfg.get("REMOTE_MAX_EDGE", "1536"))
        self.timeout = float(cfg.get("REMOTE_TIMEOUT", "120"))
        self.http = requests.Session()
        if cfg.get("REMOTE_TOKEN"):
            self.http.headers["Authorization"] = f"Bearer {cfg['REMOTE_TOKEN']}"
        self.name = f"remote-http:{self.url.split('//')[-1].split('/')[0]}"

    def payload(self, path: Path) -> bytes:
        if not self.max_edge:
            return path.read_bytes()
        with Image.open(path) as im:
            icc = im.info.get("icc_profile")
            im.draft("RGB", (self.max_edge, self.max_edge))
            img = ImageOps.exif_transpose(im).convert("RGB")
        img.thumbnail((self.max_edge, self.max_edge), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90, icc_profile=icc)
        return buf.getvalue()

    def analyze(self, path: Path, job: dict) -> Analysis:
        meta = {k: job.get(k) for k in ("album", "filename", "taken_at", "camera", "width", "height")}
        r = self.http.post(self.url, files={"file": (path.name, self.payload(path), "image/jpeg")},
                           data={"meta": json.dumps(meta, ensure_ascii=False)}, timeout=self.timeout)
        r.raise_for_status()
        d = r.json()
        return Analysis(stars=d.get("stars"), aesthetic=d.get("aesthetic"), tags=list(d.get("tags") or []),
                        taken_at=d.get("taken_at"), headline=d.get("headline"), caption=d.get("caption"),
                        extra={"model": d.get("model", self.name), **(d.get("extra") or {})})
