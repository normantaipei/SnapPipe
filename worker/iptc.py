"""
把分析結果寫進 JPG 的 IPTC / XMP（業界通用欄位，Photo Mechanic、Lightroom、通訊社與 CMS 都讀得到）。
用 exiftool（Mac：brew install exiftool；Debian / Ubuntu：apt install libimage-exiftool-perl）。

寫的欄位：
  xmp:Rating（1~5 星）、Urgency（1 最急 ~ 8）、xmp:Label（AI 精選 = Select）
  Headline、Caption-Abstract / dc:description、Keywords / dc:subject、Iptc4xmpExt:PersonInImage、Event
  City、Sub-location、Country、By-line / dc:creator、Credit、Copyright Notice
"""

import json
import shutil
import subprocess
from pathlib import Path


def have_exiftool() -> bool:
    return shutil.which("exiftool") is not None


def read_exif(path: Path) -> dict:
    r = subprocess.run(["exiftool", "-json", "-q", "-DateTimeOriginal", "-SubSecTimeOriginal", "-Rating",
                        "-BodySerialNumber", "-SerialNumber", "-Make", "-Model", str(path)],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout or "[]")[0]
    except (ValueError, IndexError):
        return {}


def write(path: Path, *, stars=None, urgency=None, pick=False, headline="", caption="", keywords=(),
          people=(), event="", city="", sublocation="", country="", creator="", credit="", copyright="") -> bool:
    """寫入 metadata（直接改這個檔，不留 _original 備份：原始檔在伺服器上另有一份）。成功回傳 True。"""
    args = ["exiftool", "-q", "-m", "-overwrite_original", "-charset", "iptc=UTF8", "-IPTC:CodedCharacterSet=UTF8"]

    def put(tags, value):
        if value not in (None, ""):
            for t in tags:
                args.append(f"-{t}={value}")

    put(["XMP-xmp:Rating"], stars)
    put(["IPTC:Urgency", "XMP-photoshop:Urgency"], urgency)
    if pick:
        put(["XMP-xmp:Label"], "Select")
    put(["IPTC:Headline", "XMP-photoshop:Headline"], headline[:256])
    put(["IPTC:Caption-Abstract", "XMP-dc:Description"], caption[:2000])
    put(["XMP-iptcExt:Event"], event)
    put(["IPTC:City", "XMP-photoshop:City"], city)
    put(["IPTC:Sub-location", "XMP-iptcCore:Location"], sublocation)
    put(["IPTC:Country-PrimaryLocationName", "XMP-photoshop:Country"], country)
    put(["IPTC:By-line", "XMP-dc:Creator"], creator)
    put(["IPTC:Credit", "XMP-photoshop:Credit"], credit)
    put(["IPTC:CopyrightNotice", "XMP-dc:Rights"], copyright)
    seen = set()
    for k in keywords:
        k = str(k).strip()[:64]
        if k and k.lower() not in seen:
            seen.add(k.lower())
            args += [f"-IPTC:Keywords-={k}", f"-IPTC:Keywords+={k}", f"-XMP-dc:Subject-={k}", f"-XMP-dc:Subject+={k}"]
    for p in people:
        if p:
            args += [f"-XMP-iptcExt:PersonInImage-={p}", f"-XMP-iptcExt:PersonInImage+={p}"]
    if len(args) == 6:
        return False
    r = subprocess.run(args + [str(path)], capture_output=True, text=True)
    return r.returncode == 0
