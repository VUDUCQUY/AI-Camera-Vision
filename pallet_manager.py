"""
pallet_manager.py
Quản lý nhiều pallet cùng lúc — mỗi product_code tạo 1 pallet riêng.
Lot_batch khác nhau vẫn gộp chung vào cùng pallet của product đó.

Business rules:
  - Duplicate carton_id (toàn cục)  → skip, log INFO
  - product_code mới                → tự tạo pallet mới
  - lot_batch khác trong cùng pallet→ log WARNING, vẫn thêm vào
"""

import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from parser import CartonData

logger = logging.getLogger(__name__)

WAREHOUSE_CODE   = "SGL"
STATION          = "ST01"
CAMERA_ID        = "CAM-STATION-01"
CONFIDENCE_SCORE = 1.0


# ── Single pallet ─────────────────────────────────────────────────────────────

class _Pallet:
    """Internal: một pallet đơn cho 1 product_code."""

    def __init__(self, product_code: str) -> None:
        self.product_code   = product_code
        self._carton_ids:   List[str] = []
        self._lot_batches:  List[str] = []
        self._expiry_dates: List[str] = []

    @property
    def carton_count(self) -> int:
        return len(self._carton_ids)

    def add(self, carton: CartonData) -> None:
        """Thêm carton (duplicate check đã xử lý bên ngoài)."""
        if self._lot_batches and carton.lot_batch != self._lot_batches[0]:
            logger.warning(
                "LOT MISMATCH trong pallet '%s' — existing='%s', new='%s' (carton_id=%s) → vẫn thêm",
                self.product_code,
                self._lot_batches[0],
                carton.lot_batch,
                carton.carton_id,
            )
        self._carton_ids.append(carton.carton_id)
        self._lot_batches.append(carton.lot_batch)
        self._expiry_dates.append(carton.expiry_date)

    def build_payload(self, now: datetime) -> dict:
        pallet_id = _generate_pallet_id(now)
        return {
            "pallet_id":        pallet_id,
            "warehouse_code":   WAREHOUSE_CODE,
            "station":          STATION,
            "carton_id":        list(self._carton_ids),
            "total_cartons":    len(self._carton_ids),
            "product_code":     self.product_code,
            "lot_batch":        self._lot_batches[0] if self._lot_batches else "",
            "min_expiry_date":  min(self._expiry_dates) if self._expiry_dates else "",
            "scan_timestamp":   now.strftime("%Y_%m_%dT%H:%M:%S"),
            "camera_id":        CAMERA_ID,
            "confidence_score": CONFIDENCE_SCORE,
        }

    def summary(self) -> str:
        lots = set(self._lot_batches)
        return (
            f"  product='{self.product_code}'  "
            f"cartons={self.carton_count}  "
            f"lots={lots}"
        )


# ── Multi-pallet manager ───────────────────────────────────────────────────────

class PalletManager:
    """
    Quản lý nhiều pallet — mỗi product_code = 1 pallet.
    Giao diện công khai tương thích với main.py cũ.
    """

    def __init__(self) -> None:
        self._pallets:   Dict[str, _Pallet] = {}   # product_code → _Pallet
        self._seen_ids:  set  = set()               # global dedup
        self._finalized: bool = False

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def carton_count(self) -> int:
        return sum(p.carton_count for p in self._pallets.values())

    @property
    def pallet_count(self) -> int:
        return len(self._pallets)

    @property
    def is_finalized(self) -> bool:
        return self._finalized

    # ── Add carton ────────────────────────────────────────────────────────────

    def add_carton(self, carton: CartonData) -> "bool | str":
        """
        Thêm carton vào pallet đúng product_code.
        Tự tạo pallet mới nếu product_code chưa từng gặp.

        Returns:
            True        → thêm thành công
            "DUPLICATE" → carton_id đã tồn tại, bỏ qua
        Raises:
            RuntimeError nếu đã finalized.
        """
        if self._finalized:
            raise RuntimeError("Không thể thêm carton sau khi đã finalize.")

        # Global duplicate check
        if carton.carton_id in self._seen_ids:
            logger.info("DUPLICATE bỏ qua → carton_id=%s", carton.carton_id)
            return "DUPLICATE"

        # Lấy hoặc tạo pallet cho product_code này
        if carton.product_code not in self._pallets:
            self._pallets[carton.product_code] = _Pallet(carton.product_code)
            logger.info("Tạo pallet mới cho product_code='%s'", carton.product_code)

        self._pallets[carton.product_code].add(carton)
        self._seen_ids.add(carton.carton_id)

        logger.info(
            "ADDED → carton_id=%s  product=%s  lot=%s  expiry=%s",
            carton.carton_id, carton.product_code,
            carton.lot_batch, carton.expiry_date,
        )
        return True

    # ── Finalize ──────────────────────────────────────────────────────────────

    def finalize(self, output_path: "str | Path" = "output.json") -> List[dict]:
        """
        Finalize tất cả pallet, ghi JSON, trả về list payload.

        Returns:
            List[dict] — mỗi phần tử là payload của 1 pallet.
        Raises:
            ValueError  nếu chưa có carton nào.
            RuntimeError nếu đã finalize rồi.
        """
        if self._finalized:
            raise RuntimeError("Đã finalize rồi.")
        if not self._pallets:
            raise ValueError("Chưa có carton nào để finalize.")

        self._finalized = True
        now = datetime.now()

        payloads = [p.build_payload(now) for p in self._pallets.values()]

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(payloads, fh, indent=2, ensure_ascii=False)

        logger.info(
            "Finalized %d pallet(s) → %s  (tổng %d carton)",
            len(payloads), output_path, self.carton_count,
        )
        return payloads

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self) -> str:
        if not self._pallets:
            return "Chưa có carton nào."
        lines = [f"Tổng {self.pallet_count} pallet(s), {self.carton_count} carton(s):"]
        for p in self._pallets.values():
            lines.append(p.summary())
        return "\n".join(lines)


# ── Helper ────────────────────────────────────────────────────────────────────

def _generate_pallet_id(now: Optional[datetime] = None) -> str:
    if now is None:
        now = datetime.now()
    date_str = now.strftime("%Y%m%d")
    seq = random.randint(0, 9999)
    return f"{WAREHOUSE_CODE}-{date_str}-{STATION}-{seq:04d}"