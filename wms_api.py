from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from typing import List, Optional
import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI()

# Khởi tạo kết nối Google Sheets 1 lần khi server start
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
CREDS = ServiceAccountCredentials.from_json_keyfile_name('test.json', SCOPE)
G_CLIENT = gspread.authorize(CREDS)
SHEET = G_CLIENT.open("WMS_Pallet").sheet1


class Pallet(BaseModel):
    pallet_id: str
    warehouse_code: str
    station: str
    carton_id: List[str]
    total_cartons: int
    product_code: str
    lot_batch: str
    min_expiry_date: str
    scan_timestamp: str
    camera_id: Optional[str] = ""
    status: Optional[str] = "COMPLETED"
    confidence_score: float = 1.0


def sync_to_sheets(pallet: Pallet):
    """Ghi 1 pallet lên 1 row trong Google Sheets."""
    try:
        row = [
            pallet.pallet_id,
            pallet.product_code,
            pallet.lot_batch,
            pallet.total_cartons,
            pallet.min_expiry_date,
            pallet.scan_timestamp,
            pallet.status or "COMPLETED",
            pallet.camera_id or "",
        ]
        SHEET.append_row(row)
        print(f"✅ Đã ghi Sheets: {pallet.pallet_id} ({pallet.product_code})")
    except Exception as e:
        print(f"❌ Lỗi Sheets: {e}")


@app.post("/pallet")
async def receive_pallet(pallet: Pallet, background_tasks: BackgroundTasks):
    """Nhận 1 pallet, ghi ngầm lên Sheets, trả về ngay."""
    print(f"📦 Nhận Pallet: {pallet.pallet_id} ({pallet.product_code})")

    if pallet.confidence_score < 0.8:
        pallet.status = "WARNING"

    background_tasks.add_task(sync_to_sheets, pallet)
    return {"status": "ok", "pallet_id": pallet.pallet_id, "message": "Đang đồng bộ ngầm..."}


@app.post("/pallets")
async def receive_pallets(pallets: List[Pallet], background_tasks: BackgroundTasks):
    """Nhận nhiều pallet cùng lúc — mỗi pallet ghi 1 row riêng lên Sheets."""
    print(f"📦 Nhận batch {len(pallets)} pallet(s)")

    for pallet in pallets:
        if pallet.confidence_score < 0.8:
            pallet.status = "WARNING"
        background_tasks.add_task(sync_to_sheets, pallet)

    return {
        "status": "ok",
        "received": len(pallets),
        "message": f"Đang đồng bộ ngầm {len(pallets)} pallet(s)...",
    }