"""
compare.py
So sánh 2 model YOLO end-to-end (YOLO + decoder) trên ảnh test + ảnh kho:
  - số mã đọc đúng / đáp án (đáp án = mọi mã mà ít nhất một model đọc ra, gộp theo cảnh:
    các ảnh real_dataN_* là cùng một cảnh nên có chung bộ mã)
  - tổng số box, số box rác (không đọc được mã), thời gian

Chạy:  python training/compare.py weights/best.pt training/runs/finetune/weights/best.pt
"""
import glob
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from ultralytics import YOLO  # noqa: E402
from decoder import QRDecoder  # noqa: E402

CONF, IMGSZ, PAD = 0.5, 1280, 40
dec = QRDecoder()
files = sorted(glob.glob("images/clean/*") + glob.glob("images/test/*.jpg") + glob.glob("images/test/*.bmp")
               + glob.glob("images/z77*.jpg"))


def scene(f):
    m = re.match(r"(real_data\d)_", os.path.basename(f))
    return m.group(1) if m else os.path.basename(f)


# Ảnh model mới CHƯA từng thấy khi train (z77 không đưa vào dataset; real_data4 + Capture_cam3 chỉ nằm ở val)
# → thước đo chống overfitting; quyết định thay model dựa trên nhóm này.
HELD_OUT = ("z77", "real_data4_", "Capture_cam3")


def group(f):
    b = os.path.basename(f)
    kind = "ảnh kho z77" if b.startswith("z77") else ("camera" if "Capture" in b else "real_data")
    return ("CHƯA THẤY " if any(k in b for k in HELD_OUT) else "đã thấy ") + kind


def run(weights):
    y = YOLO(weights)
    per, boxes, junk, t0 = {}, defaultdict(int), defaultdict(int), time.time()
    for f in files:
        img = cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        codes = set()
        for b in y.predict(img, conf=CONF, imgsz=IMGSZ, verbose=False)[0].boxes:
            x1, y1, x2, y2 = map(int, b.xyxy[0])
            r = dec.decode_image(img[max(0, y1 - PAD):min(h, y2 + PAD), max(0, x1 - PAD):min(w, x2 + PAD)])
            boxes[group(f)] += 1; junk[group(f)] += not r; codes.update(r)
        per[f] = codes
    return per, boxes, junk, time.time() - t0


results = {w: run(w) for w in sys.argv[1:]}
gt = defaultdict(set)
for per, *_ in results.values():
    for f, c in per.items():
        gt[scene(f)] |= c
total = sum(len(gt[scene(f)]) for f in files)
for w, (per, boxes, junk, t) in results.items():
    hit = sum(len(per[f] & gt[scene(f)]) for f in files)
    g = defaultdict(lambda: [0, 0])
    for f in files:
        g[group(f)][0] += len(per[f] & gt[scene(f)]); g[group(f)][1] += len(gt[scene(f)])
    print(f"{w}\n  mã đọc đúng {hit}/{total} ({100 * hit / total:.1f}%)   thời gian={t:.0f}s")
    for k in sorted(g):
        a, b = g[k]
        print(f"    {k:22s} mã {a}/{b}   box {boxes[k]}  (rác, không ra mã: {junk[k]})")
