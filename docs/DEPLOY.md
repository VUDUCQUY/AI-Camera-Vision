# Triển khai (host) hệ thống

Toàn bộ hệ thống chạy trong **một container**: FastAPI phục vụ cả API lẫn giao diện React đã build, nên frontend
và backend cùng origin, không cần cấu hình CORS. Chạy bằng CPU, không cần GPU.

## Yêu cầu máy chủ

| | Tối thiểu | Khuyến nghị |
|---|---|---|
| CPU | 4 nhân | 8+ nhân (YOLO + decode chạy trên CPU) |
| RAM | 2 GB (container dùng ~0.6–0.7 GB khi quét) | 4 GB |
| Ổ đĩa | 5 GB (image 2.6 GB) | Cộng thêm dung lượng cho video upload (tự xoá sau `WMS_UPLOAD_TTL_HOURS`) |
| Phần mềm | Docker + Docker Compose | |

## Các bước

```bash
git clone <repo> && cd QR_Decode_v2
cp .env.example .env            # đặt WMS_BASIC_AUTH=user:mật-khẩu-mạnh
# (tuỳ chọn) chép file service account Google vào ./test.json để đồng bộ Sheets
mkdir -p uploads data
sudo chown -R 1000:1000 uploads data   # Linux: container chạy bằng user uid 1000
docker compose up -d --build
curl http://localhost:8000/health   # {"status":"ok","model":"best_v2.pt","sheets":...,"auth":true}
```

Mở `http://<máy-chủ>:8000`. Trình duyệt sẽ hỏi tài khoản đã đặt ở `WMS_BASIC_AUTH`.

> **Không dùng Google Sheets?** Xoá dòng mount `./test.json` trong `docker-compose.yml`. Nếu để nguyên mà file
> không tồn tại, Docker sẽ tạo một *thư mục* tên `test.json`. Server vẫn chạy, chỉ tắt đồng bộ Sheets và in cảnh báo.

Chạy không dùng Docker (Windows/Linux):

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
cd frontend && npm ci && npm run build && cd ..
WMS_BASIC_AUTH=admin:matkhau python -m uvicorn backend.api:app --host 0.0.0.0 --port 8000 --workers 1
```

## Checklist trước khi mở ra Internet

- [ ] **Đặt `WMS_BASIC_AUTH`.** Không đặt thì ai có URL cũng upload được và ghi được vào Google Sheet.
- [ ] **Bật HTTPS** (reverse proxy bên dưới). Basic auth gửi mật khẩu dạng base64, qua HTTP thường có thể bị đọc trộm.
- [ ] **`test.json` và `.env` không được commit và không được build vào image.** Đã chặn bằng `.gitignore` và `.dockerignore`, và đã kiểm tra lịch sử git không chứa khoá.
- [ ] **Chọn `WMS_MAX_UPLOAD_MB`** phù hợp (mặc định 1024MB/file). Video DJI mẫu nặng 470MB.
- [ ] **Giữ `--workers 1`.** Model YOLO và bộ đệm frame stream nằm trong RAM của một process. Nhiều worker thì stream video sẽ không thấy frame AI.
- [ ] **Timeout của proxy ≥ 10 phút.** Request quét video giữ kết nối trong suốt thời gian quét (video 4 phút mất ~47s trong container trên CPU 12 nhân, lâu hơn trên máy yếu).

## Reverse proxy (nginx + HTTPS)

```nginx
server {
    listen 443 ssl;
    server_name kho.example.com;
    ssl_certificate     /etc/letsencrypt/live/kho.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/kho.example.com/privkey.pem;

    client_max_body_size 1100m;          # >= WMS_MAX_UPLOAD_MB
    proxy_read_timeout   600s;           # quét video lâu
    proxy_send_timeout   600s;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;             # bắt buộc cho /video-stream (MJPEG)
    }
}
```

Có thể dùng Caddy (`reverse_proxy 127.0.0.1:8000`) hoặc Cloudflare Tunnel thay nginx. Với Cloudflare cần lưu ý
giới hạn upload 100MB của gói Free.

## Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `WMS_BASIC_AUTH` | (trống) | `user:pass` → bắt đăng nhập mọi route trừ `/health` |
| `WMS_MAX_UPLOAD_MB` | `1024` | Giới hạn mỗi file upload; vượt quá → HTTP 413 |
| `WMS_UPLOAD_TTL_HOURS` | `6` | Video upload cũ hơn thì tự xoá |
| `WMS_CORS_ORIGINS` | `*` | Chỉ cần khi frontend ở domain khác, ví dụ `https://kho.example.com` |
| `WMS_GOOGLE_CREDS` | `./test.json` | File service account; thiếu → tắt đồng bộ Sheets |
| `WMS_SHEET_NAME` | `WMS_Pallet` | Tên Google Sheet |
| `WMS_YOLO_WEIGHTS` | `weights/best_v2.pt` | Đổi model mà không cần sửa code |
| `WMS_UPLOAD_DIR` / `WMS_DATA_DIR` | `./uploads` / `./data` | Nơi lưu video upload / `output.json` |

## Đã kiểm thử — trực tiếp và trong Docker container (bật đăng nhập, giới hạn 50MB)

- **Đăng nhập:** `/health` mở; `/`, `/docs` và API trả 401 khi thiếu hoặc sai mật khẩu; giao diện React và file JS tải được khi đăng nhập đúng.
- **Path traversal:** tên file dạng `../`, `..\` gửi vào `/video-stream`, `/process-image`, `/get-thumbnail` đều trả 404; upload với tên `../../x.mp4` vẫn nằm trong `uploads/`.
- **Upload quá cỡ:** trả 413 và phần file dở dang đã bị xoá.
- **Luồng chính:** quét ảnh, upload video, thumbnail, quét video, stream MJPEG, `POST /pallets` khi không có Sheets.
- **Container:** chạy bằng user thường (không phải root), không chứa `test.json`; quét VideoCam1 (234s) ra đủ 7 mã trong 47s.

## Vận hành

- **Xem log:** `docker compose logs -f wms`
- **Cập nhật:** `git pull && docker compose up -d --build`
- **Đổi về model gốc:** thêm `WMS_YOLO_WEIGHTS=/app/weights/best_v1_original.pt` vào `.env`, rồi `docker compose up -d`
- **Sao lưu:** chỉ cần `data/output.json`. Thư mục `uploads/` là dữ liệu tạm.
