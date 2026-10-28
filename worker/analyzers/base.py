"""
分析器介面：worker 把照片交給分析器，拿回星等、分數、標籤、圖說。

兩種寫法：
  - analyze(path, job) → Analysis                     一張一張分析（none、remote_http）
  - analyze_burst([(path, job), …]) → [Analysis, …]   一次拿到整組連拍（meta_ai：同組照片互相比較才挑得出最佳瞬間）
    設 wants_bursts = True，worker 就會先把同一台相機、間隔很短的照片湊成一組再交給你。

如果有把 metadata 寫進檔案（IPTC/XMP），把 file_modified 設 True，worker 會把改過的 JPG 換上伺服器。
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Player:
    key: str              # 分組用：home:23
    label: str            # 顯示用：#23 王小明
    box: Optional[tuple] = None   # (x, y, w, h) 0~1，左上原點；人物頭像用
    confidence: float = 0.0


@dataclass
class Analysis:
    stars: Optional[int] = None          # 1~5；None = 未評分
    aesthetic: Optional[float] = None    # 分數（meta_ai：融合後 1~10），只用來排序
    tags: list = field(default_factory=list)
    taken_at: Optional[str] = None       # ISO 8601；None = 沿用伺服器從 EXIF 讀到的
    camera: Optional[str] = None
    headline: Optional[str] = None
    caption: Optional[str] = None        # 圖說（範本 + AI 的動作描述），編輯確認後發稿
    ai: dict = field(default_factory=dict)       # 給網頁顯示：pick、moment、burst、players、needs_review…
    players: list = field(default_factory=list)  # [Player]：名單比對過的球員，worker 依此做「依球員」分組
    file_modified: bool = False          # True = 已把 metadata 寫進 path 那個檔
    extra: dict = field(default_factory=dict)    # 隨結果記在伺服器的工作上（模型版本、token 用量…）


class Analyzer:
    name = "base"
    wants_bursts = False

    def __init__(self, cfg: dict, log=print):
        self.cfg = cfg
        self.log = log

    def analyze(self, path: Path, job: dict) -> Analysis:   # pragma: no cover
        raise NotImplementedError

    def analyze_burst(self, items: list) -> list:
        return [self.analyze(p, j) for p, j in items]
