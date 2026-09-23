"""
backend/api.py
API cho hệ thống quét pallet: nhận ảnh/video → YOLO tìm vùng QR → giải mã → gom pallet → Google Sheets.

Chạy (từ thư mục gốc dự án):  python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
Routes:
  POST /process-image   ảnh hoặc video → boxes, codes, pallets, previews, evidence
  POST /upload-video    lưu video để xem trước / quét (trả về tên file trên server)
  GET  /video-stream/…  MJPEG: frame AI đang quét, không thì phát video gốc lặp lại
  POST /get-thumbnail   frame đầu tiên của video
  POST /pallets         đồng bộ pallet lên Google Sheets
  GET  /health          kiểm tra server (không cần đăng nhập)
  /                     giao diện React (nếu đã build frontend/build)

Cấu hình qua biến môi trường (xem .env.example): WMS_BASIC_AUTH, WMS_CORS_ORIGINS, WMS_MAX_UPLOAD_MB,
WMS_GOOGLE_CREDS, WMS_SHEET_NAME, WMS_YOLO_WEIGHTS, WMS_UPLOAD_DIR, WMS_DATA_DIR, WMS_UPLOAD_TTL_HOURS.
"""
import asyncio
import base64
import binascii
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
import traceback
from typing import List, Optional, Tuple

import cv2
import gspread
import numpy as np
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from oauth2client.service_account import ServiceAccountCredentials
from pydantic import BaseModel
from ultralytics import YOLO

from .decoder import QRDecoder
from .pallet_manager import PalletManager
from .qr_parser import QRParser

# ============================================================== CẤU HÌNH
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # thư mục gốc dự án


def _env(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


# --- triển khai (đặt qua biến môi trường khi host)
UPLOAD_DIR = _env("WMS_UPLOAD_DIR", os.path.join(BASE_DIR, "uploads"))
DATA_DIR = _env("WMS_DATA_DIR", os.path.join(BASE_DIR, "data"))           # output.json của pallet
UPLOAD_TTL_HOURS = float(_env("WMS_UPLOAD_TTL_HOURS", "6"))              # video upload cũ hơn → tự xoá
MAX_UPLOAD_MB = float(_env("WMS_MAX_UPLOAD_MB", "1024"))                 # giới hạn mỗi file upload
BASIC_AUTH = _env("WMS_BASIC_AUTH", "")                                  # "user:mật_khẩu" → bật đăng nhập
CORS_ORIGINS = [o.strip() for o in _env("WMS_CORS_ORIGINS", "*").split(",") if o.strip()]
GOOGLE_CREDS = _env("WMS_GOOGLE_CREDS", os.path.join(BASE_DIR, "test.json"))  # service account (không commit!)
SHEET_NAME = _env("WMS_SHEET_NAME", "WMS_Pallet")
YOLO_WEIGHTS = _env("WMS_YOLO_WEIGHTS", os.path.join(BASE_DIR, "weights", "best_v2.pt"))  # gốc: best_v1_original.pt
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend", "build")   # `npm run build` → phục vụ tại "/"

VIDEO_EXTS = (".mp4", ".avi", ".mov", ".mkv", ".webm")

# --- nhận diện
YOLO_CONF = 0.5          # lọc nhiễu (lá cây, cái thang...)
YOLO_IMGSZ = 1280
CROP_PAD = 40            # lấy đủ Quiet Zone quanh QR
MAX_PREVIEWS = 8         # số ảnh slideshow trả về cho frontend
PREVIEW_MAX_W = 1280     # ảnh preview / bằng chứng gửi về frontend được thu nhỏ về chiều ngang này

# Video
VIDEO_SAMPLE_FPS = 1          # số frame chạy YOLO + decode mỗi giây video (QR thường hiện nhiều giây liền)
VIDEO_STREAM_FPS = 1          # số frame đẩy lên /video-stream mỗi giây video; 1 = chỉ frame vừa quét (nhanh nhất)
STREAM_MAX_W = 960            # chiều ngang frame stream (nhỏ → nén và gửi nhanh)
VIDEO_MIN_FRAME_DIFF = 2.5    # frame khác frame vừa quét ít hơn mức này (độ sáng TB, 0..255) → bỏ qua
VIDEO_FORCE_SCAN_SEC = 10     # cảnh đứng yên vẫn quét lại sau mỗi N giây
CACHE_MAX_DIFF = 8.0          # crop cùng vị trí khác ít hơn mức này → dùng lại kết quả cũ
CACHE_RETRY_FAILED_SEC = 2    # crop decode thất bại: thử lại sau N giây video
BOX_COLOR = (0, 255, 136)

# ============================================================== KHỞI TẠO (1 lần khi server start)
app = FastAPI(title="WMS QR Scanner")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_ORIGINS != ["*"],  # trình duyệt không cho credentials với origin "*"
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Bật khi đặt WMS_BASIC_AUTH="user:pass". Trình duyệt hỏi mật khẩu 1 lần rồi tự gửi kèm
    cho mọi request cùng origin (kể cả <img> stream video). /health luôn mở cho health check."""
    if not BASIC_AUTH or request.url.path == "/health" or request.method == "OPTIONS":
        return await call_next(request)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("basic "):
        try:
            given = base64.b64decode(header[6:]).decode("utf-8")
            if secrets.compare_digest(given, BASIC_AUTH):
                return await call_next(request)
        except (binascii.Error, UnicodeDecodeError):
            pass
    return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="WMS QR Scanner"'})


def _open_sheet():
    """Google Sheets là tuỳ chọn: thiếu credentials hoặc lỗi mạng → vẫn chạy, chỉ tắt đồng bộ."""
    if not os.path.isfile(GOOGLE_CREDS):
        print(f"⚠️ Không có {GOOGLE_CREDS} → tắt đồng bộ Google Sheets")
        return None
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS, scope)
        return gspread.authorize(creds).open(SHEET_NAME).sheet1
    except Exception as e:
        print(f"⚠️ Không mở được Google Sheet '{SHEET_NAME}': {e} → tắt đồng bộ")
        return None


SHEET = _open_sheet()

yolo_model = YOLO(YOLO_WEIGHTS)
_yolo_lock = threading.Lock()  # ảnh + video có thể quét song song; YOLO không an toàn khi gọi đồng thời
decoder = QRDecoder()
parser = QRParser()

# Khung hình AI mới nhất của từng video đang quét, để /video-stream phát lại: {filename: jpeg bytes}
GLOBAL_FRAME_BUFFER: dict = {}


def cleanup_uploads(max_age_hours: float = UPLOAD_TTL_HOURS):
    """Xoá video upload cũ + khung AI tương ứng. File đang bị stream giữ (Windows khoá) → bỏ qua, lần sau xoá."""
    if not os.path.isdir(UPLOAD_DIR):
        return
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for name in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, name)
        if not os.path.isfile(path) or os.path.getmtime(path) >= cutoff:
            continue
        try:
            os.remove(path)
            GLOBAL_FRAME_BUFFER.pop(name.lower(), None)
            removed += 1
        except OSError:
            pass
    if removed:
        print(f"🧹 Đã xoá {removed} video upload cũ hơn {max_age_hours}h")


def safe_upload_name(name: Optional[str]) -> str:
    """Tên file an toàn trong UPLOAD_DIR: bỏ thư mục, chỉ giữ chữ/số/._- và khoảng trắng.
    Chặn path traversal ('../', '..\\') từ tên file do client gửi lên."""
    base = os.path.basename((name or "").replace("\\", "/")).lower()
    base = re.sub(r"[^a-z0-9._ -]", "_", base).strip(" .")
    if not base:
        raise HTTPException(status_code=400, detail="Tên file không hợp lệ")
    return base


def uploaded_path(server_filename: str) -> str:
    """Đường dẫn file đã upload; 404 nếu không tồn tại."""
    path = os.path.join(UPLOAD_DIR, safe_upload_name(server_filename))
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Không tìm thấy file đã upload")
    return path


async def save_upload(file: UploadFile, dest: str):
    """Ghi file upload theo từng khúc, dừng + xoá nếu vượt MAX_UPLOAD_MB (tránh đầy ổ đĩa)."""
    limit, written = MAX_UPLOAD_MB * 1024 * 1024, 0
    try:
        with open(dest, "wb") as f:
            while chunk := await file.read(8 * 1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(status_code=413, detail=f"File vượt quá {MAX_UPLOAD_MB:.0f}MB")
                f.write(chunk)
    except BaseException:
        if os.path.exists(dest):
            os.remove(dest)
        raise


async def read_upload(file: UploadFile) -> bytes:
    """Đọc cả file (ảnh) vào RAM, có giới hạn dung lượng."""
    data = await file.read(int(MAX_UPLOAD_MB * 1024 * 1024) + 1)
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File vượt quá {MAX_UPLOAD_MB:.0f}MB")
    return data


os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
cleanup_uploads()


# ============================================================== DATA MODEL
class Pallet(BaseModel):
    pallet_id:        str
    warehouse_code:   str
    station:          str
    carton_id:        List[str]
    total_cartons:    int
    product_code:     str
    lot_batch:        str
    min_expiry_date:  str
    scan_timestamp:   str
    camera_id:        Optional[str] = ""
    status:           Optional[str] = "COMPLETED"
    confidence_score: float = 1.0


def sync_to_sheets(pallet: Pallet):
    if SHEET is None:
        return
    try:
        SHEET.append_row([
            pallet.pallet_id,
            pallet.product_code,
            pallet.lot_batch,
            pallet.total_cartons,
            pallet.min_expiry_date,
            pallet.scan_timestamp,
            pallet.status or "OK",
            pallet.camera_id or "CAM_01",
        ])
        print(f"✅ Sheets: {pallet.pallet_id}")
    except Exception as e:
        print(f"❌ Lỗi Sheets: {e}")


# ============================================================== XỬ LÝ ẢNH
def encode_jpeg(img: np.ndarray, quality: int = 95) -> bytes:
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tobytes()


def detect_qr_boxes(image: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """YOLO → danh sách box (x1, y1, x2, y2) theo pixel."""
    with _yolo_lock:
        dets = yolo_model.predict(source=image, conf=YOLO_CONF, imgsz=YOLO_IMGSZ, verbose=False)[0].boxes
    return [tuple(map(int, d.xyxy[0])) for d in dets]


def crop_box(image: np.ndarray, xyxy) -> np.ndarray:
    h, w = image.shape[:2]
    x1, y1, x2, y2 = xyxy
    return image[max(0, y1 - CROP_PAD):min(h, y2 + CROP_PAD), max(0, x1 - CROP_PAD):min(w, x2 + CROP_PAD)]


def make_box(xyxy, img_w: int, img_h: int, index: int, code: Optional[str]) -> dict:
    """Box cho frontend: toạ độ chuẩn hoá 0..1, nhãn = mã (cắt ngắn) hoặc 'QR n'."""
    x1, y1, x2, y2 = xyxy
    box = {
        "points": [[x1 / img_w, y1 / img_h], [x2 / img_w, y1 / img_h],
                   [x2 / img_w, y2 / img_h], [x1 / img_w, y2 / img_h]],
        "label": f"QR {index}",
        "decoded": bool(code),
    }
    if code:
        box["code"] = code
        box["label"] = (code[:15] + "..") if len(code) > 15 else code
    return box


def decode_crop(crop: np.ndarray) -> Optional[str]:
    payloads = decoder.decode_image(crop)
    return payloads[0] if payloads else None


def register_code(code: str, pallet_manager: PalletManager):
    carton = parser.parse(code)
    if carton:
        pallet_manager.add_carton(carton)


def process_single_frame(image: np.ndarray, pallet_manager: PalletManager) -> List[dict]:
    """Ảnh tĩnh: YOLO tìm vùng QR → giải mã từng vùng → thêm carton vào pallet_manager."""
    img_h, img_w = image.shape[:2]
    boxes = []
    for xyxy in detect_qr_boxes(image):
        crop = crop_box(image, xyxy)
        if crop.size == 0:
            continue
        code = decode_crop(crop)
        if code:
            register_code(code, pallet_manager)
        boxes.append(make_box(xyxy, img_w, img_h, len(boxes) + 1, code))
    return boxes


def draw_boxes(frame: np.ndarray, boxes: List[dict]) -> np.ndarray:
    """Vẽ khung + nhãn của các box (toạ độ chuẩn hoá) lên bản sao của frame."""
    h, w = frame.shape[:2]
    out = frame.copy()
    for b in boxes:
        pts = (np.array(b["points"]) * [w, h]).astype(np.int32).reshape((-1, 1, 2))
        cv2.polylines(out, [pts], True, BOX_COLOR, 3)
        cv2.putText(out, b["label"], (int(pts[0][0][0]), int(pts[0][0][1] - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, BOX_COLOR, 2)
    return out


def downscale(img: np.ndarray, max_w: int = PREVIEW_MAX_W) -> np.ndarray:
    h, w = img.shape[:2]
    return img if w <= max_w else cv2.resize(img, (max_w, int(h * max_w / w)), interpolation=cv2.INTER_AREA)


def to_b64_jpeg(img: np.ndarray) -> str:
    return base64.b64encode(encode_jpeg(img)).decode("utf-8")


# ============================================================== VIDEO
def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _thumb(img: np.ndarray, size) -> np.ndarray:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return cv2.resize(gray, size, interpolation=cv2.INTER_AREA).astype(np.float32)


class CropCache:
    """
    QR thường đứng yên qua nhiều frame. Nhớ kết quả theo vị trí box:
    cùng chỗ (IoU > 0.5) và trông như cũ → dùng lại kết quả, khỏi decode lại.
    Kết quả THẤT BẠI chỉ được nhớ một lúc rồi thử lại (frame sau có thể nét hơn).
    """

    def __init__(self, retry_after: int):
        self.retry_after = retry_after  # số frame trước khi thử decode lại crop thất bại
        self._entries = []  # [xyxy, thumb, code, frame_no]

    def lookup(self, xyxy, thumb: np.ndarray, frame_no: int):
        for bx, th, code, seen_at in self._entries:
            if _iou(bx, xyxy) > 0.5 and float(np.mean(np.abs(th - thumb))) < CACHE_MAX_DIFF:
                if code or frame_no - seen_at < self.retry_after:
                    return True, code
        return False, None

    def store(self, xyxy, thumb: np.ndarray, code: Optional[str], frame_no: int):
        self._entries = [e for e in self._entries if _iou(e[0], xyxy) <= 0.5]
        self._entries.append([xyxy, thumb, code, frame_no])


def scan_video(path: str, stream_key: str, pallet_manager: PalletManager):
    """
    Quét video (chạy trong thread riêng):
      - lấy mẫu VIDEO_SAMPLE_FPS frame/giây, bỏ qua frame gần như không đổi so với frame vừa quét
      - CropCache: không decode lại QR đứng yên, không thử lại liên tục vùng YOLO bắt nhầm
      - đẩy khung hình đã vẽ vào GLOBAL_FRAME_BUFFER cho /video-stream
    Trả về (boxes không trùng mã, preview frames, evidence {mã: {image, points}}, (w, h)).
    """
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step = max(1, round(fps / VIDEO_SAMPLE_FPS))
    stream_step = max(1, round(fps / VIDEO_STREAM_FPS))
    force_every = int(VIDEO_FORCE_SCAN_SEC * fps)

    cache = CropCache(retry_after=int(CACHE_RETRY_FAILED_SEC * fps))
    boxes, previews, evidence, size = [], [], {}, (0, 0)
    last_thumb, last_scanned = None, -force_every
    last_boxes = []
    frame_no = scanned = 0
    t0 = time.time()

    def publish(frame, frame_boxes):  # frame cho /video-stream: thu nhỏ + vẽ khung, nén nhẹ cho nhanh
        small = draw_boxes(downscale(frame, STREAM_MAX_W), frame_boxes)
        GLOBAL_FRAME_BUFFER[stream_key] = encode_jpeg(small, quality=75)

    try:
        while True:
            is_sample = frame_no % step == 0
            if not is_sample and frame_no % stream_step:
                if not cap.grab():  # frame không dùng tới: chỉ tua qua
                    break
                frame_no += 1
                continue
            ret, frame = cap.read()
            if not ret:
                break
            frame_no += 1
            if not is_sample:  # chỉ để stream mượt: vẽ lại khung YOLO gần nhất
                publish(frame, last_boxes)
                continue

            thumb = _thumb(frame, (160, 90))
            changed = last_thumb is None or float(np.mean(np.abs(thumb - last_thumb))) >= VIDEO_MIN_FRAME_DIFF
            if not changed and frame_no - last_scanned < force_every:
                publish(frame, last_boxes)
                continue
            last_thumb, last_scanned = thumb, frame_no
            scanned += 1

            img_h, img_w = frame.shape[:2]
            size = (img_w, img_h)
            frame_boxes, new_boxes = [], []
            for xyxy in detect_qr_boxes(frame):
                crop = crop_box(frame, xyxy)
                if crop.size == 0:
                    continue
                crop_thumb = _thumb(crop, (32, 32))
                hit, code = cache.lookup(xyxy, crop_thumb, frame_no)
                if not hit:
                    code = decode_crop(crop)
                    cache.store(xyxy, crop_thumb, code, frame_no)
                box = make_box(xyxy, img_w, img_h, len(frame_boxes) + 1, code)
                frame_boxes.append(box)
                if code and code not in evidence and all(b["code"] != code for b in new_boxes):
                    register_code(code, pallet_manager)
                    new_boxes.append(box)

            if new_boxes:  # lưu frame bằng chứng: bấm vào mã ở bước 3 sẽ thấy đúng chỗ
                small = downscale(frame)
                img_b64 = to_b64_jpeg(small)
                for box in new_boxes:
                    evidence[box["code"]] = {"image": img_b64, "points": box["points"]}
                if len(previews) < MAX_PREVIEWS:
                    previews.append(small)
                print(f"  → {frame_no / fps:6.1f}s: mã mới {[b['code'] for b in new_boxes]}")

            last_boxes = frame_boxes
            publish(frame, frame_boxes)
            seen = {b.get("code") or b["label"] for b in boxes}
            boxes += [b for b in frame_boxes if (b.get("code") or b["label"]) not in seen]
    finally:
        cap.release()
    print(f"  → đã quét {scanned}/{frame_no} frame, {len(evidence)} mã, {time.time() - t0:.0f}s")
    return boxes, previews, evidence, size


async def prepare_video_file(file: UploadFile, server_filename: Optional[str]):
    """Trả về (đường dẫn để quét, tên file dùng làm key stream, có cần xoá sau khi quét không).

    Nếu video đã được upload qua /upload-video thì quét trên BẢN COPY,
    tránh PermissionError vì /video-stream đang đọc file gốc."""
    if not server_filename:
        name = f"{int(time.time())}_{safe_upload_name(file.filename)}"
        path = os.path.join(UPLOAD_DIR, name)
        await save_upload(file, path)
        return path, name, False

    orig_path = uploaded_path(server_filename)
    name = os.path.basename(orig_path)
    copy_path = os.path.join(UPLOAD_DIR, f"scan_{name}")
    try:
        shutil.copy2(orig_path, copy_path)
        return copy_path, name, True
    except Exception as e:
        print(f"⚠️ Không thể copy file, thử dùng trực tiếp: {e}")
        return orig_path, name, False


def build_pallets(pallet_manager: PalletManager, background_tasks: BackgroundTasks) -> List[dict]:
    results = []
    for data in pallet_manager.finalize(os.path.join(DATA_DIR, "output.json")):
        pallet = Pallet(**data)
        if pallet.confidence_score < 0.8:
            pallet.status = "WARNING"
        background_tasks.add_task(sync_to_sheets, pallet)
        results.append(pallet.dict())
    return results


# ============================================================== ROUTES
@app.get("/health")
async def health():
    return {"status": "ok", "model": os.path.basename(YOLO_WEIGHTS), "sheets": SHEET is not None,
            "auth": bool(BASIC_AUTH)}


@app.post("/process-image")
async def process_image(request: Request, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """Route chính: ảnh hoặc video → YOLO → giải mã QR → pallet."""
    try:
        server_filename = (await request.form()).get("server_filename")
        filename = (file.filename or "").lower()
        pallet_manager = PalletManager()
        previews, evidence = [], {}

        if not filename.endswith(VIDEO_EXTS):
            image = cv2.imdecode(np.frombuffer(await read_upload(file), np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                return {"status": "error", "message": "Ảnh không hợp lệ"}
            boxes = await asyncio.to_thread(process_single_frame, image, pallet_manager)  # không chặn /video-stream
            size = (image.shape[1], image.shape[0])
        else:
            path, stream_key, is_copy = await prepare_video_file(file, server_filename)
            boxes, frames, size = [], [], (0, 0)
            try:
                # thread riêng: server vẫn phục vụ /video-stream trong lúc quét
                boxes, frames, evidence, size = await asyncio.to_thread(scan_video, path, stream_key, pallet_manager)
                print(f"✅ Quét Video xong: {stream_key}")
            except Exception as e:
                print(f"❌ Lỗi video: {e}")
            finally:
                if is_copy and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            previews = [to_b64_jpeg(f) for f in frames]

        # Mọi mã đọc được, kể cả mã không đúng định dạng pallet — để frontend luôn hiện ra
        codes = list(dict.fromkeys(b["code"] for b in boxes if b.get("code")))
        found = pallet_manager.carton_count > 0
        pallets = build_pallets(pallet_manager, background_tasks) if found else []

        if found:
            message = f"Phát hiện {pallet_manager.carton_count} carton từ file."
        elif codes:
            message = f"Đọc được {len(codes)} mã QR (chưa đúng định dạng pallet)."
        else:
            message = "Không tìm thấy QR code trong file."

        return {
            "status": "ok",
            "total_pallets": len(pallets),
            "pallets": pallets,
            "codes": codes,
            "boxes": boxes,
            "image_size": list(size),
            "previews": previews,
            "evidence": evidence,  # video: {mã: {image, points}} — frame mà mã được đọc ra
            "message": message,
        }

    except HTTPException:
        raise
    except Exception as e:
        print(traceback.format_exc())
        return {"status": "error", "message": str(e)}


@app.post("/upload-video")
async def upload_video(file: UploadFile = File(...)):
    """Lưu video để frontend xem trước qua /video-stream trước khi quét."""
    unique_filename = f"{int(time.time())}_{safe_upload_name(file.filename)}"
    print(f"📁 Nhận video để preview: {unique_filename}")
    try:
        cleanup_uploads()
        file_path = os.path.join(UPLOAD_DIR, unique_filename)
        await save_upload(file, file_path)
        print(f"✅ Đã lưu file vào: {file_path}")
        return {"status": "ok", "filename": unique_filename}
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Lỗi upload video: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/video-stream/{filename}")
async def video_stream(filename: str, request: Request):
    """MJPEG stream: ưu tiên khung hình AI đang quét, nếu không thì phát video gốc lặp lại.
    Trình duyệt ngắt kết nối (đóng/tải lại trang) → dừng stream và đóng file video."""
    filename = safe_upload_name(filename)
    file_path = os.path.join(UPLOAD_DIR, filename)
    for _ in range(10):  # file vừa upload có thể chưa ghi xong: đợi tối đa 5s
        if os.path.isfile(file_path):
            break
        await asyncio.sleep(0.5)
    else:
        raise HTTPException(status_code=404, detail="Không tìm thấy video")

    def mjpeg(jpeg: bytes) -> bytes:
        return b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"

    def next_video_frame(cap) -> Optional[bytes]:
        ret, frame = cap.read()
        if not ret:  # hết video → tua về đầu, phát lặp lại
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()
        return encode_jpeg(frame) if ret else None

    async def generate():
        cap = cv2.VideoCapture(file_path)
        print(f"📺 Bắt đầu luồng Stream cho: {filename}")
        try:
            while not await request.is_disconnected():
                ai_frame = GLOBAL_FRAME_BUFFER.get(filename)
                if ai_frame:
                    yield mjpeg(ai_frame)
                    await asyncio.sleep(0.04)
                    continue
                jpeg = await asyncio.to_thread(next_video_frame, cap)  # giải mã frame ngoài event loop
                if jpeg is None:
                    await asyncio.sleep(1)
                    continue
                yield mjpeg(jpeg)
                await asyncio.sleep(0.04)
        finally:
            cap.release()
            print(f"📺 Đóng luồng Stream cho: {filename}")

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.post("/get-thumbnail")
async def get_thumbnail(request: Request, file: UploadFile = File(...)):
    """Trả frame đầu tiên của video (base64 JPEG). Có server_filename thì đọc file đã upload."""
    print(f"📸 ĐANG LẤY THUMBNAIL CHO: {file.filename}")
    try:
        server_filename = (await request.form()).get("server_filename")
        uploaded = uploaded_path(server_filename) if server_filename else None
        if uploaded:
            cap = cv2.VideoCapture(uploaded)
            ret, frame = cap.read()
            cap.release()
        else:
            suffix = os.path.splitext(safe_upload_name(file.filename))[1]
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp_path = tmp.name
            await save_upload(file, tmp_path)
            cap = cv2.VideoCapture(tmp_path)
            ret, frame = cap.read()
            cap.release()
            os.remove(tmp_path)

        if not ret:
            print("❌ Không lấy được frame nào từ video.")
            return {"status": "error", "message": "Không thể lấy thumbnail"}

        print("✅ Đã lấy thumbnail thành công!")
        return {"status": "ok", "thumbnail": to_b64_jpeg(frame)}
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Lỗi thumbnail: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/pallets")
async def receive_pallets(pallets: List[Pallet], background_tasks: BackgroundTasks):
    """Sync thủ công từ StepFinalize."""
    for p in pallets:
        background_tasks.add_task(sync_to_sheets, p)
    return {"status": "ok", "message": f"Đã nhận {len(pallets)} pallets"}


# ============================================================== FRONTEND
# Có bản build React → phục vụ luôn tại "/" (1 server, cùng origin với API → không cần CORS khi host).
# Mount cuối cùng để các route API ở trên được ưu tiên.
if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
else:
    @app.get("/")
    async def root():
        return JSONResponse({"status": "ok", "message": "API đang chạy. Chưa có frontend build → xem /docs"})
