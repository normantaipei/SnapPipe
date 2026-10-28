"""不分析：照片原樣標成「已處理」。用來先打通 Pi → 伺服器 → worker → NAS 的流程。"""

from pathlib import Path

from .base import Analysis, Analyzer


class NoneAnalyzer(Analyzer):
    name = "none"

    def analyze(self, path: Path, job: dict) -> Analysis:
        return Analysis(extra={"model": "none"})
