# Hướng dẫn cài đặt & chạy

Hệ thống gồm 3 phần: **backend API** (`backend/`), **frontend React** (`frontend/`) và **CLI** quét thư mục ảnh (`cli/`).
Tổng quan kiến trúc xem [README.md](../README.md). Host lên server (Docker, HTTPS, đăng nhập) xem [DEPLOY.md](DEPLOY.md).

Mọi lệnh dưới đây chạy từ **thư mục gốc dự án**.

---

## 1. Cài đặt

### Python (backend + CLI)

Khuyến nghị **Python 3.11**.

```bash
pip install -r requirements.txt
```

Cần có sẵn:

- `weights/best_v2.pt`: model YOLO đang dùng. Model gốc được lưu ở `weights/best_v1_original.pt`.
- `test.json`: service account Google, có quyền sửa Google Sheet tên `WMS_Pallet`. **File này không được commit** (đã có trong `.gitignore`).

Tuỳ chọn: để bật WeChat QR (CNN + super-resolution), thay `opencv-python` bằng `opencv-contrib-python`, rồi đặt 4 file
`detect.prototxt`, `detect.caffemodel`, `sr.prototxt`, `sr.caffemodel` vào `weights/wechat/`.
Không có thì decoder tự bỏ qua bước này.

### Node.js (frontend)

```bash
cd frontend
npm install
```

---

## 2. Chạy hệ thống

### Backend (port 8000)

```bash
python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
```

Kiểm tra: mở http://127.0.0.1:8000/docs.

> Server không bật `--reload`. Sau khi sửa code Python, phải khởi động lại server.
> Khởi động lại sẽ làm đứt stream video trên trình duyệt; bấm **START SCAN** để kết nối lại.

### Frontend (port 3000)

```bash
cd frontend
npm start
```

Mở http://localhost:3000. Ở chế độ dev, frontend gọi backend tại `http://127.0.0.1:8000`. Có thể đổi bằng biến `REACT_APP_API_BASE`.

Khi đã `npm run build`, backend phục vụ luôn giao diện tại http://127.0.0.1:8000/, không cần chạy `npm start`.

### CLI: quét cả thư mục ảnh offline

```bash
python -m cli.scan_folder --folder ./images/clean
```

Quét xong, nhấn **SPACE** (Windows: Enter) để chốt pallet. Kết quả ghi vào `data/output.json` và gửi lên `POST /pallets` nếu backend đang chạy.

---

## 3. Cấu hình thường chỉnh (đầu file `backend/api.py`)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `YOLO_WEIGHTS` | `weights/best_v2.pt` | Model YOLO. Đổi về `best_v1_original.pt` để dùng model gốc |
| `YOLO_CONF` | `0.5` | Ngưỡng tin cậy YOLO. Hạ xuống thì bắt nhiều box hơn nhưng chậm hơn và nhiều box rác hơn |
| `YOLO_IMGSZ` | `1280` | Kích thước ảnh đưa vào YOLO |
| `CROP_PAD` | `40` | Lề (px) quanh box khi cắt crop để decode |
| `VIDEO_SAMPLE_FPS` | `1` | Số frame chạy YOLO + decode mỗi giây video |
| `VIDEO_STREAM_FPS` | `1` | Số frame đẩy lên stream mỗi giây video (tăng thì mượt hơn nhưng quét chậm hơn) |
| `UPLOAD_TTL_HOURS` | `6` | Video trong `uploads/` cũ hơn mức này sẽ bị tự xoá |

Các thiết lập khi triển khai (đăng nhập, giới hạn upload, đường dẫn credentials…) đặt qua biến môi trường `WMS_*`. Xem [DEPLOY.md](DEPLOY.md) và `.env.example`.

Các ngưỡng của decoder (kích thước mã nhỏ, độ dài mã tối thiểu, bộ kernel khử nhòe) nằm ở phần **CẤU HÌNH** đầu file `backend/decoder.py`.

---

## 4. Cấu trúc mã nguồn

```
backend/
  api.py              FastAPI: quét ảnh/video, stream MJPEG, thumbnail, đồng bộ Sheets, phục vụ frontend
  decoder.py          Giải mã QR nhiều tầng (zxing-cpp, tiền xử lý, khử nhòe)
  qr_parser.py        Tách payload QR → CartonData
  pallet_manager.py   Gom carton vào pallet, chặn trùng, cảnh báo lệch lô, xuất JSON
cli/
  scan_folder.py      Quét thư mục ảnh (python -m cli.scan_folder)
  console.py          Logging, banner, chờ phím SPACE
  wms_client.py       Gửi pallet từ CLI lên POST /pallets
frontend/             Giao diện React — xem frontend/README.md
training/             Sinh dataset, fine-tune YOLO, so sánh model — xem training/README.md
weights/              Model YOLO (best_v2.pt, best_v1_original.pt) + model WeChat (tuỳ chọn)
docs/                 SETUP.md, DEPLOY.md, yolo_v1_training/ (biểu đồ + args train của model gốc)
images/               Ảnh / video kiểm thử (clean/, test/, z77*.jpg là ảnh kho thật)
uploads/, data/       Video upload / output.json (tự sinh, không commit)
```

---

## 5. Xử lý sự cố

| Hiện tượng | Nguyên nhân / cách xử lý |
|---|---|
| Quét chậm bất thường | Có tiến trình khác đang ăn CPU (quét video song song, train model…). YOLO chạy trên CPU nên bị chia tài nguyên |
| Khung QR không hiện trên stream video | Server vừa khởi động lại → bấm START SCAN để stream kết nối lại |
| Không xoá được file trong `uploads/` | File đang được stream giữ. Đóng tab hoặc tải lại trang, server sẽ tự nhả file |
| API báo "chưa đúng định dạng pallet" | Mã đọc được nhưng không theo `carton_id\|product\|lot\|MM-YYYY`. Mã vẫn hiện trong bảng QR CODES |
| VS Code báo "Cannot find module cv2" | IDE đang dùng Python khác. Chọn interpreter Python 3.11 đã `pip install -r requirements.txt` |
