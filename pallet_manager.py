"""
pallet_manager.py
Core pallet grouping, deduplication, business-rule validation, and JSON generation.
"""
import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

from parser import CartonData

logger = logging.getLogger(__name__)

# Các hằng số cấu hình hệ thống
WAREHOUSE_CODE = "SGL"
STATION = "ST01"
CAMERA_ID = "CAM-STATION-01"
CONFIDENCE_SCORE = 1.0


def _generate_pallet_id(now: Optional[datetime] = None) -> str:
    if now is None:
        now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    seq = random.randint(0, 9999)
    return f"{WAREHOUSE_CODE}-{date_str}-{STATION}-{seq:04d}"


class _Pallet:

    def __init__(self, product_code: str) -> None:
        self.product_code = product_code
        self._carton_ids: List[str] = []  # Danh sách mã thùng (carton)
        self._lot_batches: List[str] = []  # Danh sách các số lô (lot)
        self._expiry_dates: List[str] = []  # Danh sách hạn sử dụng

    @property
    def carton_count(self) -> int:
        return len(self._carton_ids)

    def add(self, carton: CartonData) -> None:
        """Thêm một thùng hàng mới vào pallet."""
        if self._lot_batches and carton.lot_batch != self._lot_batches[0]:
            logger.warning(
                "LỆCH LÔ [%s]: Lô cũ='%s', Lô mới='%s' (Mã thùng=%s)",
                self.product_code, self._lot_batches[0], carton.lot_batch, carton.carton_id
            )
        self._carton_ids.append(carton.carton_id)
        self._lot_batches.append(carton.lot_batch)
        self._expiry_dates.append(carton.expiry_date)

    def build_payload(self, now: datetime, current_exceptions: List[str]) -> dict:
        pallet_id = _generate_pallet_id(now)
        main_lot = self._lot_batches[0] if self._lot_batches else ""

        return {
            "pallet_id": pallet_id,
            "warehouse_code": WAREHOUSE_CODE,
            "station": STATION,
            "carton_id": list(self._carton_ids),
            "total_cartons": len(self._carton_ids),
            "product_code": self.product_code,
            "lot_batch": main_lot,
            "min_expiry_date": min(self._expiry_dates) if self._expiry_dates else "",
            "scan_timestamp": now.strftime("%Y_%m_%dT%H:%M:%S"),
            "camera_id": CAMERA_ID,
            "confidence_score": CONFIDENCE_SCORE,
            "exceptions": current_exceptions  # Đính kèm danh sách lỗi quét (nếu có)
        }

    def summary(self) -> str:
        """Tóm tắt thông tin pallet để in ra màn hình console."""
        unique_lots = set(self._lot_batches)
        return f"  [SP: {self.product_code}] SL: {self.carton_count} | Lô: {unique_lots}"


class PalletManager:
    """Lớp quản lý chính: Điều phối việc phân loại hàng vào nhiều pallet khác nhau."""
    def __init__(self) -> None:
        self._pallets: Dict[str, _Pallet] = {}  # Từ điển lưu trữ: product_code -> Đối tượng _Pallet
        self._seen_ids: set = set()  # Tập hợp lưu mã thùng để chặn trùng lặp
        self._exceptions: List[str] = []  # Lưu các mã QR không hợp lệ/lỗi quét
        self._finalized: bool = False  # Trạng thái đã chốt dữ liệu hay chưa

    @property
    def carton_count(self) -> int:
        """Tổng số thùng hàng đã quét thành công trên tất cả các pallet."""
        return sum(p.carton_count for p in self._pallets.values())

    @property
    def pallet_count(self) -> int:
        """Tổng số lượng pallet đã được tạo ra."""
        return len(self._pallets)

    def add_carton(self, carton: CartonData) -> Union[bool, str]:
        """Tiếp nhận thùng hàng từ Parser và đưa vào đúng pallet theo product_code."""
        if self._finalized:
            raise RuntimeError("Hệ thống đã chốt sổ, không thể thêm hàng.")

        if carton.is_exception:
            self._exceptions.append(carton.raw_data)
            logger.warning(f"PHÁT HIỆN QR LỖI: {carton.raw_data}")
            return "EXCEPTION"

        if carton.carton_id in self._seen_ids:
            logger.info(f"MÃ THÙNG TRÙNG (Bỏ qua): {carton.carton_id}")
            return "DUPLICATE"

        if carton.product_code not in self._pallets:
            self._pallets[carton.product_code] = _Pallet(carton.product_code)

        self._pallets[carton.product_code].add(carton)
        self._seen_ids.add(carton.carton_id)

        logger.info("ĐÃ THÊM -> ID: %s | SP: %s", carton.carton_id, carton.product_code)
        return True

    def finalize(self, output_path: Union[str, Path] = "output.json") -> List[dict]:
        if self._finalized:
            raise RuntimeError("Dữ liệu đã được finalize rồi.")
        if not self._pallets:
            raise ValueError("Không có hàng hóa nào để chốt sổ.")

        self._finalized = True
        now = datetime.now()

        payloads = [p.build_payload(now, self._exceptions) for p in self._pallets.values()]

        full_output = {
            "pallets": payloads,
            "exceptions": self._exceptions,
            "summary": {
                "total_pallets": len(payloads),
                "total_cartons": self.carton_count,
                "total_exceptions": len(self._exceptions)
            }
        }

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(full_output, fh, indent=2, ensure_ascii=False)

        return payloads

    def summary(self) -> str:
        """In báo cáo tổng kết ra màn hình khi kết thúc phiên làm việc."""
        if not self._pallets: return "Dữ liệu trống."
        lines = [f"Tổng cộng: {self.pallet_count} Pallets, {self.carton_count} Thùng hàng:"]
        for p in self._pallets.values():
            lines.append(p.summary())
        if self._exceptions:
            lines.append(f"! Cảnh báo: Có {len(self._exceptions)} mã QR lỗi.")
        return "\n".join(lines)