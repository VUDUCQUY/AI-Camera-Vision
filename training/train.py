"""
train.py
Fine-tune YOLOv8 phát hiện QR (weights/best.pt) trên dataset của make_dataset.py.

Chạy:  python training/train.py --epochs 12        (mặc định: fine-tune weights/best.pt, freeze 10 layer, lr 0.001)
Kết quả: training/runs/<name>/weights/best.pt  (so sánh bằng training/compare.py trước khi thay weights/best.pt)
"""
import argparse
import os
from pathlib import Path

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

ap = argparse.ArgumentParser()
ap.add_argument("--epochs", type=int, default=25)
ap.add_argument("--batch", type=int, default=16)
ap.add_argument("--base", default="weights/best.pt", help="model gốc để fine-tune")
ap.add_argument("--name", default="finetune_v2")
ap.add_argument("--freeze", type=int, default=10, help="đóng băng N layer đầu (backbone) → giữ kiến thức của model gốc")
ap.add_argument("--lr0", type=float, default=0.001)
ap.add_argument("--data", default="training/data/data.yaml", help="training/data_synth/data.yaml cho bản chỉ tổng hợp")
args = ap.parse_args()

YOLO(args.base).train(
    data=str(ROOT / args.data),
    imgsz=640,            # ô 640 đã ở đúng tỉ lệ vật thể như khi chạy thật với imgsz=1280
    epochs=args.epochs,
    batch=args.batch,
    device="cpu",
    workers=4,
    patience=8,
    project=str(ROOT / "training" / "runs"),
    name=args.name,
    freeze=args.freeze,
    optimizer="AdamW",
    lr0=args.lr0,
    exist_ok=True,
    # tăng cường dữ liệu: giữ cỡ vật thể gần đúng thực tế (scale nhỏ), cho phép xoay nhẹ
    scale=0.3,
    degrees=10.0,
    mosaic=1.0,
    close_mosaic=5,
    fliplr=0.5,
    plots=True,
)
