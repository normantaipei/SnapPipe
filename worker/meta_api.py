"""
Meta Model API（Muse Spark）的最小用戶端：Chat Completions + 影像 + JSON Schema 結構化輸出。

只用 requests，不依賴 OpenAI SDK。文件：https://dev.meta.ai/docs/quickstart
  - POST {META_API_BASE}/chat/completions，Authorization: Bearer <金鑰>
  - 影像放在 user 訊息的 image_url（base64 data URL），一次最多 50 張
  - response_format = {"type": "json_schema", "json_schema": {"name", "schema", "strict"}}
"""

import base64
import io
import json
import time
from pathlib import Path

import requests
from PIL import Image, ImageOps

DEFAULT_BASE = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
MAX_IMAGES = 50


# 帳號類錯誤的白話說明（setup 驗證與 worker 記錄共用）
ACCOUNT_HINTS = {
    401: "金鑰錯誤或已撤銷：執行 worker/setup.sh --ask-key 換金鑰",
    402: "帳號還沒設定付款或額度用完：到 https://dev.meta.ai 的 Billing 頁加信用卡 / 查看額度",
    403: "這把金鑰沒有權限（或帳號所在地區不能用）",
    404: "找不到模型：檢查 worker/.env 的 META_MODEL",
}


class MetaApiError(RuntimeError):
    """呼叫失敗。retry=True 表示晚點再試可能會好（網路、429、5xx）。"""

    def __init__(self, msg: str, retry: bool = True, status: int = 0):
        super().__init__(msg)
        self.retry = retry
        self.status = status


def check_key(api_key: str, base: str = DEFAULT_BASE, model: str = DEFAULT_MODEL, timeout: float = 20):
    """金鑰能不能用：GET /models/{model}（不產生內容、不收費），確認金鑰有效、這個模型可以用。
    Meta 沒有查付款狀態的 API，沒綁卡要等第一次真的分析時才會收到 402（worker 記錄會說明怎麼處理）。
    回傳 (結果, 說明)；結果是 ok / invalid（要換金鑰或設定才會好）/ network（連不上，晚點可能會好）。"""
    if not api_key:
        return "invalid", "沒有金鑰"
    try:
        r = requests.get(f"{base.rstrip('/')}/models/{model}", timeout=timeout,
                         headers={"Authorization": f"Bearer {api_key}"})
    except requests.RequestException as e:
        return "network", f"連不上 {base}：{type(e).__name__}"
    if r.status_code == 200:
        return "ok", f"{model} 可以使用"
    try:
        err = r.json().get("error") or {}
        detail = err.get("message") or err.get("code") or ""
    except (ValueError, AttributeError):
        detail = r.text[:120]
    hint = {401: "金鑰錯誤或已撤銷", 404: f"找不到模型 {model}（檢查 META_MODEL）"}.get(r.status_code) \
        or ACCOUNT_HINTS.get(r.status_code, "")
    msg = f"HTTP {r.status_code}" + (f" {hint}" if hint else "") + (f"（{detail}）" if detail else "")
    return ("network" if r.status_code >= 500 or r.status_code == 429 else "invalid"), msg


def load_rgb(path: Path, max_edge: int) -> Image.Image:
    """讀 JPG、依 EXIF 轉正、縮到長邊 max_edge。draft() 讓 JPEG 解碼時就先縮小，快很多。"""
    with Image.open(path) as im:
        im.draft("RGB", (max_edge, max_edge))
        img = ImageOps.exif_transpose(im).convert("RGB")
    img.thumbnail((max_edge, max_edge), Image.LANCZOS)
    return img


def data_url(img: Image.Image, quality: int = 85) -> str:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


class MetaClient:
    def __init__(self, api_key: str, base: str = DEFAULT_BASE, model: str = DEFAULT_MODEL,
                 reasoning: str = "", timeout: float = 120, retries: int = 4, log=print):
        if not api_key:
            raise SystemExit("ANALYZER=meta_ai 需要 Meta API 金鑰：執行 worker/setup.sh 輸入金鑰（會先驗證），"
                             "或設環境變數 META_API_KEY；不用 AI、只當普通相簿就在 worker/.env 設 ANALYZER=none")
        if model.endswith("-contributor"):
            log("  ⚠ 用的是 contributor 方案：Meta 可以拿送出的照片與圖說訓練模型。新聞照片建議用一般方案。")
        self.base = base.rstrip("/")
        self.model = model
        self.reasoning = reasoning
        self.timeout = timeout
        self.retries = retries
        self.log = log
        self.http = requests.Session()
        self.http.headers.update({"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})

    def _post(self, body: dict) -> dict:
        """送出請求；網路錯誤、429、5xx 會退避重試，其餘錯誤直接丟出。"""
        wait = 2.0
        for attempt in range(self.retries + 1):
            try:
                r = self.http.post(f"{self.base}/chat/completions", data=json.dumps(body), timeout=self.timeout)
            except requests.RequestException as e:
                err = MetaApiError(f"連不到 Meta Model API：{e}")
            else:
                if r.ok:
                    return r.json()
                detail = r.text[:300]
                try:
                    detail = r.json().get("error", {}).get("message") or detail
                except (ValueError, AttributeError):
                    pass
                transient = r.status_code == 429 or r.status_code >= 500
                hint = ACCOUNT_HINTS.get(r.status_code, "")
                err = MetaApiError(f"Meta Model API {r.status_code}：{detail}" + (f"（{hint}）" if hint else ""),
                                   retry=transient, status=r.status_code)
                if not transient:
                    raise err
                if r.headers.get("Retry-After", "").isdigit():
                    wait = max(wait, float(r.headers["Retry-After"]))
            if attempt < self.retries:
                time.sleep(min(wait, 60))
                wait *= 2
        raise err

    def chat_json(self, system: str, content: list, schema: dict, name: str, max_tokens: int = 4000,
                  schema_retries: int = 2) -> tuple:
        """回傳 (解析後的 dict, usage)。輸出不是合法 JSON 時最多重送 schema_retries 次。"""
        n_img = sum(1 for c in content if c.get("type") == "image_url")
        if n_img > MAX_IMAGES:
            raise MetaApiError(f"一次最多 {MAX_IMAGES} 張圖，這次 {n_img} 張", retry=False)
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": False}},
            "max_completion_tokens": max_tokens,
        }
        if self.reasoning:
            body["reasoning_effort"] = self.reasoning
        usage = {"input_tokens": 0, "output_tokens": 0}
        last = ""
        for _ in range(schema_retries + 1):
            d = self._post(body)
            u = d.get("usage") or {}
            usage["input_tokens"] += int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
            usage["output_tokens"] += int(u.get("completion_tokens") or u.get("output_tokens") or 0)
            try:
                last = d["choices"][0]["message"]["content"] or ""
                out = json.loads(strip_fence(last))
                if isinstance(out, dict):
                    return out, usage
            except (KeyError, IndexError, TypeError, ValueError):
                pass
        raise MetaApiError(f"模型輸出不是合法的 JSON：{last[:200]}", retry=False)


def strip_fence(s: str) -> str:
    """有些回應會包在 ```json … ``` 裡。"""
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1].rsplit("```", 1)[0]
    return s
