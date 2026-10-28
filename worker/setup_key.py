#!/usr/bin/env python3
"""
設定 Meta API 金鑰（worker/setup.sh 會呼叫；也可以單獨跑 .venv/bin/python setup_key.py --ask 換金鑰）。

金鑰從哪來（依序）：--api-key、環境變數 META_API_KEY / SP_META_API_KEY、worker/.env 裡原本的。
  - 帶了金鑰：先驗證，通過就存進 .env；沒通過就請你重新輸入
  - 沒帶：問你（輸入時不顯示）。驗證通過才存；沒通過就再問一次
  - 問的時候直接按 Enter 留空：關掉 AI（ANALYZER=none），照片照常進相簿，只是不評分、不選片、不寫圖說
  - 不是在終端機裡跑（systemd、自動化）又沒有金鑰：同樣關掉 AI，之後再跑 setup.sh 就會問
驗證用 Meta 的模型查詢端點（GET /models/{模型}，不收費），確認金鑰有效、模型可以用。
Meta 沒有查付款狀態的 API：還沒綁卡的話，要到第一次真的分析才會知道（worker 記錄會說明）。
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from meta_api import DEFAULT_BASE, DEFAULT_MODEL, check_key  # noqa: E402

# 訊息語言：SNAPPIPE_LANG=en 用英文，其他（或沒設）用中文；setup.sh --lang 會 export 進來
EN = os.environ.get("SNAPPIPE_LANG") == "en"


def t(zh, en):
    return en if EN else zh


PROMPT = t("Meta API 金鑰（https://dev.meta.ai → API keys；直接按 Enter = 不用 AI，只當普通相簿）：",
           "Meta API key (https://dev.meta.ai → API keys; press Enter to skip AI and use it as a plain album): ")
ENABLE_HINT = t("之後要開 AI：worker/setup.sh --ask-key（或 --api-key <金鑰>）",
                "To turn on AI later: worker/setup.sh --ask-key (or --api-key <key>)")


def read_env(path: Path) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def write_env(path: Path, values: dict):
    """改 .env 裡的設定，保留其他行與註解；同一個設定寫了好幾行就全部改（讀的時候是最後一行算數），沒有就加在最後。"""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen = set()
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if k in values:
            lines[i] = f"{k}={values[k]}"
            seen.add(k)
    lines += [f"{k}={v}" for k, v in values.items() if k not in seen]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


class KeySetup:
    def __init__(self, env_path: Path, interactive: bool, out=print, ask=None, confirm=None):
        self.path = env_path
        self.env = read_env(env_path)
        self.base = self.env.get("META_API_BASE") or DEFAULT_BASE
        self.model = self.env.get("META_MODEL") or DEFAULT_MODEL
        self.interactive = interactive
        self.out = out
        self.ask = ask or (lambda: getpass.getpass(PROMPT))
        self.confirm = confirm or (lambda q: input(q).strip().lower() in ("y", "yes"))

    def check(self, key: str):
        self.out(t("  驗證金鑰中…", "  Checking the key…"))
        return check_key(key, self.base, self.model)

    def save(self, key: str):
        write_env(self.path, {"META_API_KEY": key, "ANALYZER": "meta_ai"})
        self.out(t(f"✅ Meta API 金鑰已存進 {self.path}（權限 600），AI 選片、星等與標籤開啟（有拍攝計劃才寫圖說）",
                   f"✅ Meta API key saved to {self.path} (mode 600). AI picks, stars and tags are on (captions only with a shoot plan)."))
        return "meta_ai"

    def disable(self, why: str):
        write_env(self.path, {"META_API_KEY": "", "ANALYZER": "none"})
        self.out(t(f"ℹ️ {why}：AI 關閉（ANALYZER=none），照片照常進相簿，不評分、不選片、不寫圖說。{ENABLE_HINT}",
                   f"ℹ️ {why}: AI is off (ANALYZER=none). Photos still go to the album, but with no stars, picks, or captions. {ENABLE_HINT}"))
        return "none"

    def try_key(self, key: str):
        """驗證一把金鑰：通過就存。回傳 'meta_ai' 或 None（沒通過）。"""
        status, msg = self.check(key)
        if status == "ok":
            self.out(f"  {msg}")
            return self.save(key)
        self.out(t(f"❌ 金鑰沒有通過：{msg}", f"❌ The key did not pass: {msg}"))
        if status == "network" and self.interactive and \
                self.confirm(t("  連不上 Meta，可能是網路暫時的問題。先存起來、之後 worker 啟動時再試？[y/N] ",
                               "  Can't reach Meta. It may be a temporary network problem. Save the key anyway and retry when the worker starts? [y/N] ")):
            write_env(self.path, {"META_API_KEY": key, "ANALYZER": "meta_ai"})
            self.out(t("⚠️ 金鑰已存但還沒驗證通過；worker 呼叫失敗時會在記錄裡顯示原因",
                       "⚠️ Key saved, but not verified yet. If the worker's calls fail, the log will show why."))
            return "meta_ai"
        return None

    def prompt_loop(self):
        while True:
            try:
                key = self.ask().strip()
            except (EOFError, KeyboardInterrupt):
                self.out("")
                return self.disable(t("沒有輸入金鑰", "No key entered"))
            if not key:
                return self.disable(t("沒有輸入金鑰", "No key entered"))
            if self.try_key(key):
                return "meta_ai"
            self.out(t("  請再輸入一次（直接按 Enter = 不用 AI）", "  Please try again (press Enter to skip AI)"))

    def run(self, given: str = "", force_ask: bool = False, no_ai: bool = False, no_check: bool = False):
        if no_ai:
            return self.disable(t("指定 --no-ai", "--no-ai was given"))
        if given and no_check:                       # 呼叫端已經驗證過（例：PVE 主機上的 create-lxc.sh）
            return self.save(given)
        if given:                                    # 自己帶了金鑰
            if self.try_key(given):
                return "meta_ai"
            if not self.interactive:
                raise SystemExit(t("帶入的 Meta API 金鑰沒有通過驗證（見上方原因）；換一把金鑰再跑，或加 --no-ai",
                                   "The Meta API key you passed did not pass the check (see the reason above). Run again with another key, or add --no-ai."))
            return self.prompt_loop()
        existing = self.env.get("META_API_KEY", "")
        analyzer = self.env.get("ANALYZER", "meta_ai") or "meta_ai"
        if not force_ask:
            if existing:                             # 之前設過：在終端機裡就順便確認還能用
                if not self.interactive:
                    return analyzer
                status, msg = self.check(existing)
                if status == "ok":
                    self.out(t(f"✅ worker/.env 的 Meta API 金鑰可以用（{msg}）", f"✅ The Meta API key in worker/.env works ({msg})"))
                    return analyzer
                if status == "network":
                    self.out(t(f"⚠️ 沒辦法驗證現有的金鑰：{msg}（先保留，之後再跑 setup.sh 確認）",
                               f"⚠️ Couldn't check the current key: {msg} (keeping it; run setup.sh again later to check)"))
                    return analyzer
                self.out(t(f"❌ worker/.env 現有的金鑰沒有通過：{msg}", f"❌ The current key in worker/.env did not pass: {msg}"))
                return self.prompt_loop()
            if analyzer != "meta_ai":                # 之前選過不用 AI（或用 remote_http）：不再問
                self.out(t(f"ℹ️ 分析器是 {analyzer}，不需要 Meta 金鑰。{ENABLE_HINT}", f"ℹ️ The analyzer is {analyzer}, so no Meta key is needed. {ENABLE_HINT}"))
                return analyzer
        if not self.interactive:
            return self.disable(t("不是在終端機裡執行、也沒有帶金鑰", "Not running in a terminal and no key was given"))
        return self.prompt_loop()


def main():
    ap = argparse.ArgumentParser(description=t("設定並驗證 Meta API 金鑰", "Set up and check the Meta API key"))
    ap.add_argument("--env", default=str(HERE / ".env"))
    ap.add_argument("--api-key", default="", help=t("直接帶金鑰（也可以用環境變數 META_API_KEY）", "Pass the key directly (or use the META_API_KEY env var)"))
    ap.add_argument("--ask", action="store_true", help=t("不管原本有沒有設，重新詢問", "Ask again even if a key is already set"))
    ap.add_argument("--no-ai", action="store_true", help=t("不用 AI，只當普通相簿", "No AI; use it as a plain album"))
    ap.add_argument("--no-check", action="store_true", help=t("帶入的金鑰已經驗證過，直接存", "The key was already checked; save it as is"))
    a = ap.parse_args()
    given = a.api_key or os.environ.get("META_API_KEY") or os.environ.get("SP_META_API_KEY") or ""
    KeySetup(Path(a.env), interactive=sys.stdin.isatty()).run(given.strip(), a.ask, a.no_ai, a.no_check)


if __name__ == "__main__":
    main()
