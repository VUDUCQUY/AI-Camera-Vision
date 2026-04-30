from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Request
import tempfile
import os
from pydantic import BaseModel
from typing import List, Optional
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
import cv2
from ultralytics import YOLO
from decoder import QRDecoder, _preprocess_variants
from parser import QRParser
from pallet_manager import PalletManager

app = FastAPI()

# ===== 1. CORS =====
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== 2. GOOGLE SHEETS =====
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name('test.json', SCOPE)
G_CLIENT = gspread.authorize(CREDS)
SHEET = G_CLIENT.open("WMS_Pallet").sheet1

# ===== 3. KHỞI TẠO — load YOLO 1 lần khi server start =====
yolo_model = YOLO("weights/best.pt")
decoder    = QRDecoder()
parser     = QRParser()


# ===== 4. DATA MODEL =====
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


# ===== 5. SYNC SHEETS =====
def sync_to_sheets(pallet: Pallet):
    try:
        row = [
            pallet.pallet_id,
            pallet.product_code,
            pallet.lot_batch,
            pallet.total_cartons,
            pallet.min_expiry_date,
            pallet.scan_timestamp,
            pallet.status or "OK",
            pallet.camera_id or "CAM_01",
        ]
        SHEET.append_row(row)
        print(f"✅ Sheets: {pallet.pallet_id}")
    except Exception as e:
        print(f"❌ Lỗi Sheets: {e}")


# =========================================================
# 🔥 ROUTE CHÍNH: YOLO detect → crop → OpenCV decode QR
# =========================================================
@app.post("/process-image")
async def process_image(request: Request, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    try:
        # Lấy server_filename từ form data (nếu có)
        form_data = await request.form()
        server_filename = form_data.get("server_filename")

        # --- A. Nhận file ---
        filename = file.filename.lower()
        is_video = any(filename.endswith(ext) for ext in [".mp4", ".avi", ".mov", ".mkv", ".webm"])
        
        pallet_manager = PalletManager()
        frontend_boxes = []
        img_w, img_h = 0, 0

        if not is_video:
            # --- Xử lý ẢNH (như cũ) ---
            contents = await file.read()
            nparr    = np.frombuffer(contents, np.uint8)
            image    = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if image is None:
                return {"status": "error", "message": "Ảnh không hợp lệ"}
            
            img_h, img_w = image.shape[:2]
            frontend_boxes = process_single_frame(image, pallet_manager, img_w, img_h)
        else:
            # --- Xử lý VIDEO ---
            # Giải pháp "Hai anh em": Copy file ra một bản tạm để AI quét, tránh tranh chấp file với Stream
            
            if not server_filename:
                # Nếu chưa upload preview thì mới lưu mới
                timestamp = int(time.time())
                filename = f"{timestamp}_{filename}"
                base_dir = os.path.dirname(os.path.abspath(__file__))
                tmp_path = os.path.join(base_dir, "uploads", filename)
                contents = await file.read()
                with open(tmp_path, "wb") as f:
                    f.write(contents)
            else:
                filename = server_filename
                base_dir = os.path.dirname(os.path.abspath(__file__))
                orig_path = os.path.join(base_dir, "uploads", filename)
                
                # Tạo bản copy để AI quét (tránh PermissionError do Stream đang đọc orig_path)
                import shutil
                tmp_path = os.path.join(base_dir, "uploads", f"scan_{filename}")
                try:
                    shutil.copy2(orig_path, tmp_path)
                except Exception as e:
                    print(f"⚠️ Không thể copy file, thử dùng trực tiếp: {e}")
                    tmp_path = orig_path

            try:
                cap = cv2.VideoCapture(tmp_path)
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = cap.get(cv2.CAP_PROP_FPS) or 30
                processed_frames = []
                frame_idx = 0
                # Tính toán thời gian nghỉ để video chạy đúng tốc độ thực (Real-time)
                # Nếu quét mỗi 5 frames, mà video 30fps -> nghỉ 5/30 = 0.16s
                scan_sleep = 5 / fps if fps > 0 else 0.1
                
                while True:
                    ret, frame = cap.read()
                    if not ret: break
                    
                    if frame_idx % 5 == 0:
                        fh, fw = frame.shape[:2]
                        img_w, img_h = fw, fh
                        print(f"  → AI đang soi giây thứ {round(frame_idx/fps, 1)}s...")
                        boxes = process_single_frame(frame, pallet_manager, fw, fh)
                        
                        # Vẽ khung xanh CHUẨN ĐÉT
                        draw_frame = frame.copy()
                        for b in boxes:
                            pts = np.array(b["points"])
                            pts[:, 0] *= fw
                            pts[:, 1] *= fh
                            pts = pts.astype(np.int32).reshape((-1, 1, 2))
                            cv2.polylines(draw_frame, [pts], True, (0, 255, 136), 3)
                            
                            label_pos = (int(pts[0][0][0]), int(pts[0][0][1]-10))
                            cv2.putText(draw_frame, b["label"], label_pos, 
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 136), 2)
                        
                        # Đẩy khung hình đã vẽ vào bộ đệm Stream (Dùng filename đã chuẩn hóa)
                        _, buffer = cv2.imencode('.jpg', draw_frame)
                        GLOBAL_FRAME_BUFFER[filename] = buffer.tobytes()
                        print(f"  → Đã cập nhật khung hình AI cho Stream: {filename}")
                        
                        processed_frames.append(frame.copy())
                        for b in boxes:
                            if not any(fb["label"] == b["label"] for fb in frontend_boxes):
                                frontend_boxes.append(b)
                                
                        # Nghỉ đúng nhịp video
                        time.sleep(scan_sleep) 
                    
                    frame_idx += 1
                cap.release()
                
                # Dọn dẹp file copy sau khi quét xong
                if server_filename and os.path.exists(tmp_path) and "scan_" in tmp_path:
                    try:
                        os.remove(tmp_path)
                    except: pass
                    
                print(f"✅ Quét Video xong: {filename}")
            except Exception as e:
                print(f"❌ Lỗi video: {e}")

        # --- D. Finalize ---
        # Gửi về danh sách các ảnh preview (slideshow) để người dùng thấy quá trình quét
        preview_list = []
        if is_video and 'processed_frames' in locals():
            import base64
            # Lấy tối đa 8 ảnh tiêu biểu nhất để làm slideshow
            for pf in processed_frames[:8]:
                _, buffer = cv2.imencode('.jpg', pf)
                preview_list.append(base64.b64encode(buffer).decode('utf-8'))

        if pallet_manager.carton_count == 0:
            return {
                "status": "ok",
                "total_pallets": 0,
                "pallets": [],
                "boxes": frontend_boxes,
                "image_size": [img_w, img_h],
                "previews": preview_list,
                "message": "Không tìm thấy QR code hợp lệ trong file."
            }

        pallet_payloads = pallet_manager.finalize("output.json")
        results = []
        for pallet_data in pallet_payloads:
            p_obj = Pallet(**pallet_data)
            if p_obj.confidence_score < 0.8:
                p_obj.status = "WARNING"
            background_tasks.add_task(sync_to_sheets, p_obj)
            results.append(p_obj.dict())

        return {
            "status": "ok",
            "total_pallets": len(results),
            "pallets": results,
            "boxes": frontend_boxes,
            "image_size": [img_w, img_h],
            "previews": preview_list,
            "message": f"Phát hiện {pallet_manager.carton_count} carton từ file."
        }

    except Exception as e:
        import traceback
        print(traceback.format_exc())
        return {"status": "error", "message": str(e)}

def process_single_frame(image, pallet_manager, img_w, img_h):
    """Hàm bổ trợ để xử lý 1 frame/ảnh và cập nhật pallet_manager."""
    frontend_boxes = []
    # Tăng imgsz lên 1280 và conf lên 0.5 để lọc nhiễu (lá cây, cái thang...)
    yolo_results = yolo_model.predict(source=image, conf=0.5, imgsz=1280, verbose=False)
    boxes_raw    = yolo_results[0].boxes

    for box in boxes_raw:
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        
        # Thêm padding rộng hơn (40px) để đảm bảo lấy đủ Quiet Zone xung quanh QR
        pad = 40
        px1 = max(0, x1 - pad)
        py1 = max(0, y1 - pad)
        px2 = min(img_w, x2 + pad)
        py2 = min(img_h, y2 + pad)

        crop = image[py1:py2, px1:px2]
        if crop.size == 0: continue

        box_entry = {
            "points": [[x1/img_w, y1/img_h], [x2/img_w, y1/img_h], [x2/img_w, y2/img_h], [x1/img_w, y2/img_h]],
            "label": f"QR {len(frontend_boxes) + 1}",
            "decoded": False,
        }

        # Giải mã với nhiều biến thể tiền xử lý
        raw_payloads = decoder.decode_image(crop)
        if raw_payloads:
            box_entry["decoded"] = True
            # Lấy chuỗi đầu tiên tìm được
            raw = raw_payloads[0]
            box_entry["label"] = (raw[:15] + "..") if len(raw) > 15 else raw
            
            # Thử parse để đưa vào pallet
            carton = parser.parse(raw)
            if carton:
                pallet_manager.add_carton(carton)
        
        frontend_boxes.append(box_entry)
    return frontend_boxes


@app.post("/upload-video")
async def upload_video(file: UploadFile = File(...)):
    filename = file.filename.lower()
    timestamp = int(time.time())
    unique_filename = f"{timestamp}_{filename}"
    
    print(f"📁 Nhận video để preview: {unique_filename}")
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        uploads_dir = os.path.join(base_dir, "uploads")
        if not os.path.exists(uploads_dir): os.makedirs(uploads_dir)
        
        file_path = os.path.join(uploads_dir, unique_filename)
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)
        print(f"✅ Đã lưu file vào: {file_path}")
        return {"status": "ok", "filename": unique_filename}
    except Exception as e:
        print(f"❌ Lỗi upload video: {e}")
        return {"status": "error", "message": str(e)}

from fastapi.responses import StreamingResponse
import time

# Biến toàn cục để đồng bộ luồng video đang quét
GLOBAL_FRAME_BUFFER = {} # {filename: current_frame_b64}

@app.get("/video-stream/{filename}")
async def video_stream(filename: str):
    filename = filename.lower()
    def generate():
        base_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(base_dir, "uploads", filename)
        
        # Đợi file xuất hiện (tối đa 5s)
        for _ in range(10):
            if os.path.exists(file_path): break
            time.sleep(0.5)

        cap = cv2.VideoCapture(file_path)
        print(f"📺 Bắt đầu luồng Stream cho: {filename}")
        while True:
            try:
                # 1. Ưu tiên khung hình AI đang quét (Đồng bộ bằng filename)
                frame_data = GLOBAL_FRAME_BUFFER.get(filename)
                if frame_data:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')
                    time.sleep(0.08)
                    continue

                # 2. Nếu không quét, phát video preview vòng lặp
                if not cap.isOpened():
                    cap = cv2.VideoCapture(file_path)
                
                ret, frame = cap.read()
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                
                _, buffer = cv2.imencode('.jpg', frame)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                time.sleep(0.04)
            except Exception as e:
                time.sleep(1)

        cap.release()

    return StreamingResponse(generate(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.post("/get-thumbnail")
async def get_thumbnail(file: UploadFile = File(...)):
    print(f"📸 ĐANG LẤY THUMBNAIL CHO: {file.filename}")
    try:
        filename = file.filename.lower()
        contents = await file.read()
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
            tmp.write(contents)
            tmp_path = tmp.name

        cap = cv2.VideoCapture(tmp_path)
        ret, frame = cap.read()
        cap.release()
        if os.path.exists(tmp_path): os.remove(tmp_path)

        if not ret:
            print("❌ Không lấy được frame nào từ video.")
            return {"status": "error", "message": "Không thể lấy thumbnail"}

        _, buffer = cv2.imencode('.jpg', frame)
        import base64
        b64 = base64.b64encode(buffer).decode('utf-8')
        print("✅ Đã lấy thumbnail thành công!")
        return {"status": "ok", "thumbnail": b64}
    except Exception as e:
        print(f"❌ Lỗi thumbnail: {e}")
        return {"status": "error", "message": str(e)}


# ===== ROUTE PHỤ: sync thủ công từ StepFinalize =====
@app.post("/pallets")
async def receive_pallets(pallets: List[Pallet], background_tasks: BackgroundTasks):
    for p in pallets:
        background_tasks.add_task(sync_to_sheets, p)
    return {"status": "ok", "message": f"Đã nhận {len(pallets)} pallets"}