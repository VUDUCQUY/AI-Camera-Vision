# Frontend — AI Camera Warehouse Management

Giao diện React (Create React App) cho hệ thống quét QR pallet.

- `npm start` (dev): gọi backend tại `http://127.0.0.1:8000`.
- `npm run build` (production): gọi **cùng origin**. Backend `backend/api.py` tự phục vụ thư mục `build/` tại `/`.
- Ghi đè địa chỉ backend bằng biến `REACT_APP_API_BASE` (khai báo `API_BASE` trong `src/StepScan.jsx`).

```bash
npm install
npm start        # http://localhost:3000
npm run build    # bản production vào build/
```

## Luồng 3 bước

| Bước | Component | Việc |
|---|---|---|
| 1. Upload | `StepUpload.jsx` | Kéo thả ảnh (JPG/PNG/BMP/HEIC) hoặc video. HEIC được chuyển sang JPEG bằng `heic2any` |
| 2. Scan | `StepScan.jsx` | Gọi `POST /process-image` lần lượt cho từng file. Hiện khung QR trên ảnh và bảng **QR CODES** gồm mọi mã đọc được |
| 3. Finalize | `StepFinalize.jsx` | Danh sách mã đã quét. Bấm một mã sẽ mở ảnh bằng chứng, **khung của mã đó sáng vàng và có vòng "ping"**. Nút **XÁC NHẬN** kết thúc lượt quét |

## Video

- Video được upload **một lần** qua `POST /upload-video` ngay khi chọn file. Khi bấm quét, nếu upload chưa xong thì
  frontend đợi, rồi chỉ gửi tên file (`server_filename`), không gửi lại cả video.
- Màn hình quét dùng `<img src="/video-stream/…">` (MJPEG). Frame AI từ server đã vẽ sẵn khung YOLO, nên không vẽ
  thêm overlay lên video. Mỗi lần bấm quét, stream tự kết nối lại (`streamKey`).
- Ở bước 3, mã đọc từ video hiện đúng frame mà mã được đọc ra (`evidence` do API trả về).

## Trạng thái giữa các bước (`App.js`)

`App.js` giữ `files`, `scanStore` (ảnh preview, boxes, evidence của từng file) và `codes` (`[{ code, src }]`).
Bấm **BACK** từ bước 3 về bước 2 sẽ khôi phục kết quả lượt quét, không phải quét lại.
Chọn file mới ở bước 1 hoặc bấm "＋ QUÉT MỚI" sẽ xoá hết.

## Còn thiếu

- Nút **XÁC NHẬN** tạm thời chỉ đổi trạng thái giao diện (hiện "ĐÃ XÁC NHẬN N MÃ"), không lưu hay đồng bộ Google Sheets — người dùng không được báo điều này trên màn hình.
  Khi cần lưu, gọi `POST /pallets` hoặc thêm API mới trong `StepFinalize.jsx`. `HistoryTable` hiện chưa có dữ liệu.
