# Train lại YOLO phát hiện QR

Model gốc (`weights/best_v1_original.pt`) được train trên ảnh QR chụp cận cảnh. Vì vậy trên ảnh kho thật (nhãn nhỏ
trên carton, camera giám sát, drone) nó hay bắt nhầm cây, thang, logo. Thư mục này chứa quy trình fine-tune
cho đúng loại ảnh thực tế. Kết quả hiện đang dùng là `weights/best_v2.pt`.

## Quy trình

```bash
python training/make_dataset.py                 # → training/data/   (~10 phút)
python training/train.py --epochs 12            # → training/runs/finetune_v2/weights/best.pt  (~50 phút CPU)
python training/compare.py weights/best_v1_original.pt training/runs/finetune_v2/weights/best.pt
```

Chỉ chép model mới vào `weights/` và đổi `YOLO_WEIGHTS` trong `backend/api.py` (hoặc biến `WMS_YOLO_WEIGHTS`) khi `compare.py` cho thấy model mới
**không đọc mất mã** trên nhóm ảnh **CHƯA THẤY**.

## Dataset (`make_dataset.py`)

Mọi ảnh được đưa về tỉ lệ như lúc chạy thật (cạnh dài 1280px), rồi cắt thành ô 640×640.

1. **Tổng hợp**: dán lên nền thật không có QR (vùng không có phát hiện nào, kể cả conf thấp)
   - nhãn giấy trắng có QR và dòng chữ, QR cỡ 14–220px
   - QR **in thẳng lên bao bì**, màu mực tuỳ ý, vùng sáng trong suốt một phần, cỡ 20–320px
   - nghiêng ±45°, phối cảnh, nhòe chuyển động/Gauss, nhiễu, độ sáng, JPEG q25–90
2. **Ảnh thật** (frame video mỗi 4 giây, ảnh test, ảnh PNG nhiều QR ở `training/data_src/`), gán nhãn tự động:
   giữ box đọc được mã, hoặc box vuông có conf ≥ 0.7. Box khác được coi là nền.

`--synthetic-only`: chỉ dùng ảnh tổng hợp; ảnh thật chỉ làm nền (→ `training/data_synth/`). Dùng khi muốn giữ
toàn bộ ảnh thật để chấm điểm.

`training/data_src/` chứa ảnh PNG nhiều QR, trích từ lịch sử git (`git show HEAD:images/<file>.png`).

## Train (`train.py`)

Fine-tune từ model gốc, `imgsz=640`, AdamW `lr0=0.001`, **đóng băng 10 layer backbone** (`--freeze 10`) để không
"quên" các kiểu QR model gốc đã biết, `scale=0.3` để giữ cỡ vật thể sát thực tế.

## Lưu ý về leak dữ liệu & overfitting

- Nhãn của ảnh thật do chính model cũ gán, nên QR mà model cũ bỏ sót sẽ bị dạy là nền.
- `real_data4`, `Capture_cam3` và `VideoCam3` chỉ nằm trong val, nhưng dùng **chung tờ nhãn và camera** với
  dữ liệu train, nên không hoàn toàn độc lập.
- **Chỉ 9 ảnh kho `images/z77*.jpg` là thật sự chưa thấy**: không vào dataset, khác địa điểm, khác máy chụp.
  Quyết định thay model dựa vào nhóm này.
- mAP trên tập val (một phần là ảnh tổng hợp) chỉ để theo dõi quá trình train, không dùng để so model.

## Lịch sử

| Bản | Thay đổi | Kết quả (`compare.py`) |
|---|---|---|
| v1 (`runs/finetune`) | Nhãn giấy trắng 14–140px, không đóng băng backbone | Bớt box rác nhưng **quên QR in trên bao bì** (ảnh kho 3/5 mã) → không dùng |
| **v2** (`runs/finetune_v2`) | Thêm QR in bao bì, cỡ lớn, ảnh PNG; freeze 10; lr 0.001 | Ảnh kho 5/5 như model gốc, box rác −30–40%, nhanh hơn 27% → **đang dùng** |
