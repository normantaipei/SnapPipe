"""產生測試照片（兩台相機：A 連拍 5 張、B 兩張單張），用 Pi 的分塊上傳協定送進伺服器。"""
import hashlib, random, subprocess, sys
from pathlib import Path
import requests
from PIL import Image, ImageDraw

out = Path(sys.argv[1]); server = sys.argv[2]; token = sys.argv[3]; album = sys.argv[4]
out.mkdir(parents=True, exist_ok=True)
shots = [("1235530", "2026:10:30 20:41:07", f"{100 + i * 120:03d}", f"A{i:04d}.JPG") for i in range(5)]
shots += [("8887781", "2026:10:30 20:45:00", "000", "B0001.JPG"), ("8887781", "2026:10:30 20:47:30", "000", "B0002.JPG")]
paths = []
for k, (serial, t, sub, name) in enumerate(shots):
    random.seed(k)
    im = Image.new("RGB", (3000, 2000), (random.randint(0, 255), 90, 140))
    d = ImageDraw.Draw(im)
    for _ in range(400):
        x, y = random.randint(0, 2999), random.randint(0, 1999)
        d.rectangle([x, y, x + random.randint(5, 80), y + random.randint(5, 80)], fill=tuple(random.randint(0, 255) for _ in range(3)))
    p = out / name
    im.save(p, quality=90)
    subprocess.run(["exiftool", "-q", "-overwrite_original", f"-DateTimeOriginal={t}", f"-SubSecTimeOriginal={sub}",
                    f"-ExifIFD:SerialNumber={serial}", "-Make=Sony", "-Model=ILCE-9M3", str(p)], check=True)
    paths.append(p)

for p in paths:
    data = p.read_bytes()
    uid = hashlib.sha256(f"test|{p.name}|{len(data)}".encode()).hexdigest()[:40]
    r = requests.put(f"{server}/api/uploads/{uid}", data=data, headers={
        "Authorization": f"Bearer {token}", "Content-Range": f"bytes 0-{len(data) - 1}/{len(data)}",
        "X-SnapPipe-Album": album, "X-SnapPipe-Filename": p.name}, timeout=60)
    r.raise_for_status()
    print(p.name, r.json().get("complete"), r.json().get("album"))
