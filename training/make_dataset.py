"""
make_dataset.py
Tạo dataset YOLO để fine-tune bộ phát hiện QR cho ảnh kho thực tế (nhãn QR nhỏ dán trên thùng carton).

Hai nguồn dữ liệu:
  1. TỔNG HỢP: dán lên nền thật không có QR (frame video trước khi có thùng, vùng carton trống):
       - "nhãn giấy" trắng có QR + dòng chữ như nhãn kho (QR 14-220px)
       - QR IN THẲNG lên bao bì, không có giấy trắng, màu mực tuỳ ý (QR 20-320px)
         → v2: thiếu loại này ở v1 khiến model "quên" QR in trên thùng sữa, bao bì sản phẩm
     kèm nghiêng / phối cảnh / nhòe chuyển động / nhiễu / nén JPEG.
  2. THẬT: frame video + ảnh test + ảnh PNG nhiều QR (training/data_src), gán nhãn tự động bằng model hiện tại + decoder:
     giữ box đọc được mã, hoặc box vuông có độ tin cậy cao. Box còn lại coi là nền.

Mọi ảnh được đưa về cùng tỉ lệ như lúc chạy thật (cạnh dài 1280px) rồi cắt ô 640x640,
để model học QR đúng kích thước nó sẽ gặp khi dự đoán với imgsz=1280.

Chạy:  python training/make_dataset.py                    → training/data/{images,labels}/{train,val} + data.yaml
       python training/make_dataset.py --synthetic-only   → training/data_synth/...
         Chỉ ảnh tổng hợp: ảnh thật chỉ làm NỀN (vùng không có QR), không lấy nhãn từ ảnh thật
         → không rò rỉ ảnh kiểm tra, không học lại lỗi của model cũ; toàn bộ ảnh thật dùng để chấm.
"""
import argparse
import glob
import os
import random
import string
import sys
from pathlib import Path

import cv2
import numpy as np
import qrcode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from ultralytics import YOLO  # noqa: E402
from decoder import QRDecoder  # noqa: E402

OUT = ROOT / "training" / "data"
TILE = 640
INFER_SIDE = 1280           # cạnh dài của ảnh lúc chạy thật (imgsz)
N_SYNTH_TRAIN, N_SYNTH_VAL = 700, 80
VAL_SOURCES = ("VideoCam3", "real_data4", "Capture_cam3")  # ảnh thật dành cho val
SEED = 0

rng = random.Random(SEED)
np_rng = np.random.default_rng(SEED)


# ------------------------------------------------------------------ tiện ích
def to_infer_scale(img):
    f = INFER_SIDE / max(img.shape[:2])
    return cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA), f


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)


def save(split, name, img, boxes):
    """boxes: [(x1, y1, x2, y2)] theo pixel của img."""
    (OUT / "images" / split).mkdir(parents=True, exist_ok=True)
    (OUT / "labels" / split).mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT / "images" / split / f"{name}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    h, w = img.shape[:2]
    lines = [f"0 {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}"
             for x1, y1, x2, y2 in boxes]
    (OUT / "labels" / split / f"{name}.txt").write_text("\n".join(lines))


def tiles_with_boxes(img, boxes, n_tiles):
    """Cắt ô TILE x TILE; mỗi ô ưu tiên chứa box. Box bị cắt >40% thì bỏ ô đó."""
    h, w = img.shape[:2]
    if h < TILE or w < TILE:
        img = cv2.copyMakeBorder(img, 0, max(0, TILE - h), 0, max(0, TILE - w), cv2.BORDER_REFLECT)
        h, w = img.shape[:2]
    out = []
    for _ in range(n_tiles * 4):
        if len(out) >= n_tiles:
            break
        if boxes and rng.random() < 0.8:
            bx = rng.choice(boxes)
            cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
            x0 = int(np.clip(cx - rng.uniform(0.1, 0.9) * TILE, 0, w - TILE))
            y0 = int(np.clip(cy - rng.uniform(0.1, 0.9) * TILE, 0, h - TILE))
        else:
            x0, y0 = rng.randint(0, w - TILE), rng.randint(0, h - TILE)
        kept, bad = [], False
        for x1, y1, x2, y2 in boxes:
            cx1, cy1, cx2, cy2 = max(x1, x0), max(y1, y0), min(x2, x0 + TILE), min(y2, y0 + TILE)
            if cx2 <= cx1 or cy2 <= cy1:
                continue
            frac = (cx2 - cx1) * (cy2 - cy1) / ((x2 - x1) * (y2 - y1))
            if frac < 0.6:
                bad = True
                break
            kept.append((cx1 - x0, cy1 - y0, cx2 - x0, cy2 - y0))
        if not bad:
            out.append((img[y0:y0 + TILE, x0:x0 + TILE].copy(), kept))
    return out


# ------------------------------------------------------------------ nhãn tự động cho ảnh thật
yolo = YOLO("weights/best.pt")
decoder = QRDecoder()


def pseudo_label(img_infer, img_full, f):
    """Box QR tin cậy (theo toạ độ img_infer) + box nghi vấn (để loại khỏi nền tổng hợp)."""
    keep, any_det = [], []
    H, W = img_full.shape[:2]
    for b in yolo.predict(img_infer, conf=0.1, imgsz=INFER_SIDE, verbose=False)[0].boxes:
        x1, y1, x2, y2 = map(float, b.xyxy[0]); conf = float(b.conf)
        any_det.append((x1, y1, x2, y2))
        if conf < 0.25:
            continue
        X1, Y1, X2, Y2 = int(x1 / f), int(y1 / f), int(x2 / f), int(y2 / f)
        crop = img_full[max(0, Y1 - 40):min(H, Y2 + 40), max(0, X1 - 40):min(W, X2 + 40)]
        ar = (x2 - x1) / max(1.0, y2 - y1)
        if decoder.decode_image(crop) or (conf >= 0.7 and 0.6 < ar < 1.6):
            keep.append((x1, y1, x2, y2))
    return keep, any_det


# ------------------------------------------------------------------ nhãn QR tổng hợp
def random_payload():
    k = rng.random()
    if k < 0.5:
        return "".join(rng.choices(string.ascii_uppercase, k=4)) + "".join(rng.choices(string.digits, k=9))
    if k < 0.75:
        return f"{rng.randint(0, 99999999):08d}-{rng.randint(1, 9)}"
    return "http://qr." + "".join(rng.choices(string.ascii_lowercase, k=8)) + ".vn/" + "".join(rng.choices(string.ascii_letters + string.digits, k=rng.randint(4, 12)))


def qr_matrix(qr_px):
    """Ma trận QR đã phóng (255 = sáng, 0 = tối), vẽ to gấp 4 rồi mới thu nhỏ → mép mềm như ảnh thật."""
    qr = qrcode.QRCode(error_correction=rng.choice([qrcode.constants.ERROR_CORRECT_L, qrcode.constants.ERROR_CORRECT_M]),
                       box_size=1, border=0)
    qr.add_data(random_payload()); qr.make(fit=True)
    m = np.array(qr.get_matrix(), dtype=np.uint8)
    mod = max(1, int(round(qr_px / m.shape[0]))) * 4
    return cv2.resize((1 - m) * 255, (m.shape[1] * mod, m.shape[0] * mod), interpolation=cv2.INTER_NEAREST)


def render_printed(qr_px):
    """QR in thẳng lên bao bì: mực màu tối, vùng sáng trong suốt hoặc phủ màu nhạt.
    Trả về (BGR, alpha 0..1, 4 góc QR)."""
    code = qr_matrix(qr_px)
    q = code.shape[0]
    qz = int(q * rng.uniform(0.04, 0.15))  # quiet zone hẹp
    dark = code == 0
    img = np.zeros((q + 2 * qz, q + 2 * qz, 3), np.float32)
    light_col = np.array([rng.randint(170, 255) for _ in range(3)], np.float32)
    ink = np.array([rng.randint(0, 80) for _ in range(3)], np.float32)
    img[:] = light_col
    img[qz:qz + q, qz:qz + q][dark] = ink
    alpha = np.full(img.shape[:2], rng.uniform(0.0, 0.9), np.float32)  # vùng sáng: lộ màu bao bì bên dưới
    alpha[qz:qz + q, qz:qz + q][dark] = rng.uniform(0.85, 1.0)
    s = qr_px / q
    img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    alpha = cv2.resize(alpha, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    corners = np.float32([[qz, qz], [qz + q, qz], [qz + q, qz + q], [qz, qz + q]]) * s
    return img.astype(np.uint8), alpha, corners


def render_sticker(qr_px):
    """Nhãn giấy trắng có QR + chữ. Trả về (BGR, alpha 0..1, 4 góc QR)."""
    code = qr_matrix(qr_px)
    q = code.shape[0]
    ml, mt = int(q * rng.uniform(0.15, 1.2)), int(q * rng.uniform(0.15, 0.6))
    mr, mb = int(q * rng.uniform(0.15, 1.2)), int(q * rng.uniform(0.25, 0.9))
    paper = np.full((q + mt + mb, q + ml + mr), rng.randint(215, 255), np.uint8)
    paper[mt:mt + q, ml:ml + q] = np.minimum(paper[mt:mt + q, ml:ml + q], code)
    for _ in range(rng.randint(0, 4)):  # dòng chữ / khung kẻ như nhãn kho
        txt = "".join(rng.choices(string.ascii_uppercase + string.digits + " ", k=rng.randint(4, 14)))
        org = (rng.randint(0, max(1, paper.shape[1] // 2)), rng.randint(mt + q + 5, paper.shape[0] - 2) if rng.random() < 0.6 else rng.randint(8, max(9, mt)))
        cv2.putText(paper, txt, org, cv2.FONT_HERSHEY_SIMPLEX, q / 260 * rng.uniform(0.6, 1.4), rng.randint(0, 90), max(1, q // 120))
    s = qr_px / q
    paper = cv2.resize(paper, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    corners = np.float32([[ml, mt], [ml + q, mt], [ml + q, mt + q], [ml, mt + q]]) * s
    return cv2.cvtColor(paper, cv2.COLOR_GRAY2BGR), np.ones(paper.shape[:2], np.float32), corners


def paste_sticker(bg, occupied):
    """Dán 1 nhãn lên bg. occupied: bbox các TỜ NHÃN đã dán (không cho chồng lên nhau,
    nếu không QR cũ bị che mà vẫn còn nhãn). Trả về (bbox QR, bbox tờ nhãn) hoặc None."""
    h, w = bg.shape[:2]
    if rng.random() < 0.35:  # QR in thẳng lên bao bì
        qr_px = int(np.exp(rng.uniform(np.log(20), np.log(320))))
        st, st_alpha, corners = render_printed(qr_px)
    else:                    # nhãn giấy trắng; log-uniform → nhiều mã nhỏ
        qr_px = int(np.exp(rng.uniform(np.log(14), np.log(220))))
        st, st_alpha, corners = render_sticker(qr_px)
    sh, sw = st.shape[:2]
    src = np.float32([[0, 0], [sw, 0], [sw, sh], [0, sh]])
    jitter = np.float32(np_rng.uniform(-0.12, 0.12, (4, 2)) * [sw, sh])  # phối cảnh
    M = cv2.getPerspectiveTransform(src, src + jitter)
    R = np.vstack([cv2.getRotationMatrix2D((sw / 2, sh / 2), rng.uniform(-45, 45), 1.0), [0, 0, 1]])
    M = R @ M
    pts = cv2.perspectiveTransform(src[None], M)[0]
    ox, oy = rng.uniform(-pts[:, 0].min(), w - pts[:, 0].max()), rng.uniform(-pts[:, 1].min(), h - pts[:, 1].max())
    M = np.array([[1, 0, ox], [0, 1, oy], [0, 0, 1]]) @ M
    qc = cv2.perspectiveTransform(corners[None], M)[0]
    box = (qc[:, 0].min(), qc[:, 1].min(), qc[:, 0].max(), qc[:, 1].max())
    sp = cv2.perspectiveTransform(src[None], M)[0]
    sheet = (sp[:, 0].min(), sp[:, 1].min(), sp[:, 0].max(), sp[:, 1].max())
    if box[0] < 0 or box[1] < 0 or box[2] > w or box[3] > h or any(iou(sheet, o) > 0 for o in occupied):
        return None
    warped = cv2.warpPerspective(st, M, (w, h))
    alpha = cv2.warpPerspective(st_alpha, M, (w, h))[..., None]
    shade = rng.uniform(0.75, 1.1)  # ánh sáng nhãn khớp với nền
    bg[:] = (bg * (1 - alpha) + np.clip(warped * shade, 0, 255) * alpha).astype(np.uint8)
    return box, sheet


def degrade(img):
    if rng.random() < 0.5:  # nhòe chuyển động
        L = rng.choice([3, 5, 7, 9, 13, 17])
        k = np.zeros((L, L), np.float32); k[L // 2, :] = 1
        k = cv2.warpAffine(k, cv2.getRotationMatrix2D((L / 2 - 0.5, L / 2 - 0.5), rng.uniform(0, 180), 1), (L, L))
        img = cv2.filter2D(img, -1, k / max(k.sum(), 1e-6))
    if rng.random() < 0.4:
        img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.5, 2.0))
    if rng.random() < 0.5:
        img = np.clip(img.astype(np.float32) + np_rng.normal(0, rng.uniform(3, 18), img.shape), 0, 255).astype(np.uint8)
    img = cv2.convertScaleAbs(img, alpha=rng.uniform(0.7, 1.25), beta=rng.uniform(-30, 30))
    q = rng.randint(25, 90)
    return cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1], cv2.IMREAD_COLOR)


# ------------------------------------------------------------------ main
def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic-only", action="store_true", help="không lưu ô ảnh thật (chỉ dùng làm nền)")
    ap.add_argument("--out", default=None, help="thư mục dataset (mặc định training/data hoặc training/data_synth)")
    args = ap.parse_args()
    OUT = Path(args.out) if args.out else ROOT / "training" / ("data_synth" if args.synthetic_only else "data")
    n_synth_train = N_SYNTH_TRAIN * 2 if args.synthetic_only else N_SYNTH_TRAIN  # bù phần ảnh thật bị bỏ

    if OUT.exists():
        import shutil
        shutil.rmtree(OUT)
    real_counts = {"train": 0, "val": 0}

    # 1) ẢNH THẬT: ảnh test + frame video, nhãn tự động
    backgrounds = []
    sources = [(f, None) for f in sorted(glob.glob("images/clean/*") + glob.glob("images/test/*.jpg") + glob.glob("images/test/*.bmp")
                                         + glob.glob("training/data_src/*.png"))]
    for v in sorted(glob.glob("images/test/*.mp4")):
        cap = cv2.VideoCapture(v)
        dur = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
        cap.release()
        sources += [(v, float(t)) for t in np.arange(0, dur - 1, 4)]  # 1 frame / 4 giây
    print(f"Ảnh thật: {len(sources)} nguồn")
    caps = {}
    for i, (f, t) in enumerate(sources):
        if t is None:
            full = cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_COLOR)
        else:
            cap = caps.setdefault(f, cv2.VideoCapture(f)); cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000); full = cap.read()[1]
        if full is None:
            continue
        img, fscale = to_infer_scale(full)
        boxes, dets = pseudo_label(img, full, fscale)
        split = "val" if any(k in f for k in VAL_SOURCES) else "train"
        stem = f"real_{i:04d}"
        is_synthetic_png = "data_src" in f  # ảnh PNG nhiều QR do script sinh ra → không phải ảnh thật
        if not args.synthetic_only or is_synthetic_png:
            for j, (tile, tb) in enumerate(tiles_with_boxes(img, boxes, n_tiles=3 if boxes else 1)):
                save(split, f"{stem}_{j}", tile, tb); real_counts[split] += 1
        # nền cho ảnh tổng hợp: ô không chứa bất kỳ phát hiện nào (kể cả conf thấp)
        if split == "train":
            for _ in range(3):
                h, w = img.shape[:2]
                if h < TILE or w < TILE:
                    break
                x0, y0 = rng.randint(0, w - TILE), rng.randint(0, h - TILE)
                if not any(iou((x0, y0, x0 + TILE, y0 + TILE), d) > 0 for d in dets):
                    backgrounds.append(img[y0:y0 + TILE, x0:x0 + TILE].copy())
        if i % 25 == 0:
            print(f"  {i}/{len(sources)}  nền={len(backgrounds)}  ô thật={real_counts}", flush=True)
    print(f"Ô ảnh thật: {real_counts}, ô nền sạch: {len(backgrounds)}")

    # 2) ẢNH TỔNG HỢP
    for split, n in (("train", n_synth_train), ("val", N_SYNTH_VAL)):
        for k in range(n):
            bg = rng.choice(backgrounds).copy()
            if rng.random() < 0.5:
                bg = cv2.flip(bg, rng.choice([0, 1, -1]))
            boxes, sheets = [], []
            for _ in range(rng.randint(1, 8)):
                r = paste_sticker(bg, sheets)
                if r:
                    boxes.append(r[0]); sheets.append(r[1])
            save(split, f"synth_{split}_{k:04d}", degrade(bg), boxes)
    print(f"Ảnh tổng hợp: train={n_synth_train} val={N_SYNTH_VAL}")

    (OUT / "data.yaml").write_text(f"path: {OUT.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n  0: qr_code\n")
    print(f"Xong → {OUT / 'data.yaml'}")


if __name__ == "__main__":
    main()
