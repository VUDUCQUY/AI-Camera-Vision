import cv2
import os
from pathlib import Path
from ultralytics import YOLO
from decoder import QRDecoder
from parser import QRParser
from pallet_manager import PalletManager
from wms_api_client import WMSApiClient

model = YOLO("weights/best.pt")
my_decoder = QRDecoder()
my_parser = QRParser()
my_pallet_manager = PalletManager()
api_client = WMSApiClient("http://localhost:8000")

folder_path = Path("images/images")
extensions = {".jpg", ".jpeg", ".png", ".webp"}

# Lấy danh sách tất cả file ảnh trong folder
image_files = [p for p in folder_path.iterdir() if p.suffix.lower() in extensions]

print(f"🚀 Tìm thấy {len(image_files)} ảnh trong thư mục. Bắt đầu quét...")

for idx, img_path in enumerate(image_files, start=1):
    print(f"\n[{idx}/{len(image_files)}] Đang xử lý: {img_path.name}")

    img = cv2.imread(str(img_path))
    if img is None: continue
    results = model.predict(source=img, conf=0.5, verbose=False)

    for box in results[0].boxes:
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        crop_img = img[y1:y2, x1:x2]
        raw_payloads = my_decoder._detect_all(crop_img)
        for raw in raw_payloads:
            carton = my_parser.parse(raw)
            if carton:
                added = my_pallet_manager.add_carton(carton)
                if added is True:
                    print(f"    + Thêm thành công: {carton.carton_id}")

try:
    if my_pallet_manager.carton_count > 0:
        print("\n📦 TẤT CẢ ẢNH ĐÃ QUÉT XONG. Đang chốt sổ pallet...")
        final_payloads = my_pallet_manager.finalize(output_path="output.json")
        # Gửi toàn bộ dữ liệu của tất cả các ảnh lên Sheets
        api_client.send_pallets(final_payloads)
        print(f"✅ Đã gửi tổng cộng {len(final_payloads)} pallet lên Google Sheets!")
    else:
        print("⚠️ Không tìm thấy mã QR hợp lệ nào trong toàn bộ folder.")

except Exception as e:
    print(f"❌ Lỗi khi gửi dữ liệu: {e}")

print("\n--- HOÀN THÀNH TOÀN BỘ HỆ THỐNG ---")