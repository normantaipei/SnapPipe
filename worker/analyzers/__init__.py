"""可用的分析器；用 .env 的 ANALYZER 選。"""

from .base import Analysis, Analyzer, Player  # noqa: F401

ANALYZERS = {
    "meta_ai": ("analyzers.meta_ai", "MetaAIAnalyzer"),               # Meta Model API（Muse Spark）：連拍選片 + 球員 + 圖說
    "remote_http": ("analyzers.remote_http", "RemoteHttpAnalyzer"),   # 把圖 POST 給任何 HTTP 服務
    "none": ("analyzers.none", "NoneAnalyzer"),                       # 不分析，只走通流程（測試）
}


def get_analyzer(name: str, cfg: dict, log=print) -> Analyzer:
    import importlib
    if name not in ANALYZERS:
        raise SystemExit(f"不認得的 ANALYZER：{name}（可用：{', '.join(ANALYZERS)}）")
    mod, cls = ANALYZERS[name]
    return getattr(importlib.import_module(mod), cls)(cfg, log)
