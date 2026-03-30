"""
pallet_manager.py
Core pallet grouping, deduplication, business-rule validation, and JSON generation.
"""

import json
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Optional

from parser import CartonData

logger = logging.getLogger(__name__)

WAREHOUSE_CODE = "SGL"
STATION = "ST01"
CAMERA_ID = "CAM-STATION-01"
CONFIDENCE_SCORE = 1.0


class PalletManager:

    def __init__(self) -> None:
        self._carton_ids: list[str] = []
        self._seen_ids: set[str] = set()
        self._product_codes: list[str] = []
        self._lot_batches: list[str] = []
        self._expiry_dates: list[str] = []
        self._finalized: bool = False
        self._exceptions: list[str] = []

    @property
    def carton_count(self) -> int:
        return len(self._carton_ids)

    @property
    def is_finalized(self) -> bool:
        return self._finalized

    def add_carton(self, carton: CartonData) -> bool:
        """
        Attempt to add a carton to the current pallet.

        Returns:
            True  → carton added successfully.
            False → duplicate (silently ignored after logging).

        Raises:
            RuntimeError: if the pallet has already been finalized.
        """
        if carton.is_exception:
            self._exceptions.append(carton.raw_data)
            logger.warning(f"Captured exception QR: {carton.raw_data}")
            return True
        if self._finalized:
            raise RuntimeError("Cannot add cartons to a finalized pallet.")

        if carton.carton_id in self._seen_ids:
            logger.info("DUPLICATE ignored → carton_id=%s", carton.carton_id)
            return False

        # Business-rule checks (warn but still add)
        self._check_consistency(carton)

        self._carton_ids.append(carton.carton_id)
        self._seen_ids.add(carton.carton_id)
        self._product_codes.append(carton.product_code)
        self._lot_batches.append(carton.lot_batch)
        self._expiry_dates.append(carton.expiry_date)

        logger.info(
            "ADDED carton → id=%s  product=%s  lot=%s  expiry=%s",
            carton.carton_id,
            carton.product_code,
            carton.lot_batch,
            carton.expiry_date,
        )
        return True

    def finalize(self, output_path: str | Path = "output.json") -> dict:
        """
        Finalize the pallet, write JSON to *output_path*, and return the dict.

        Raises:
            ValueError: if the pallet is empty.
            RuntimeError: if already finalized.
        """
        if self._finalized:
            raise RuntimeError("Pallet has already been finalized.")
        if not self._carton_ids:
            raise ValueError("Cannot finalize an empty pallet.")

        self._finalized = True
        payload = self._build_payload()

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)

        logger.info("Pallet finalized → %s  (total_cartons=%d)", output_path, payload["total_cartons"])
        return payload

    def summary(self) -> str:
        """Return a one-line human-readable pallet status string."""
        if not self._carton_ids:
            return "Pallet is empty."
        return (
            f"Pallet — {self.carton_count} carton(s) | "
            f"products: {set(self._product_codes)} | "
            f"lots: {set(self._lot_batches)}"
        )

    def _check_consistency(self, carton: CartonData) -> None:
        """Warn if new carton breaks product_code or lot_batch consistency.
        if self._product_codes and carton.product_code != self._product_codes[0]:
            logger.warning(
                "INCONSISTENT product_code: existing='%s', new='%s' (carton_id=%s)",
                self._product_codes[0],
                carton.product_code,
                carton.carton_id,
            )
        if self._lot_batches and carton.lot_batch != self._lot_batches[0]:
            logger.warning(
                "INCONSISTENT lot_batch: existing='%s', new='%s' (carton_id=%s)",
                self._lot_batches[0],
                carton.lot_batch,
                carton.carton_id,
            )
        """
    def _build_payload(self) -> dict:
        now = datetime.now()
        pallet_id = self._generate_pallet_id(now)
        min_expiry = min(self._expiry_dates)

        # Use most-common value (first seen) for product_code / lot_batch
        unique_product_codes = list(set(self._product_codes))
        unique_lot_batches = list(set(self._lot_batches))

        return {
            "pallet_id": pallet_id,
            "warehouse_code": WAREHOUSE_CODE,
            "station": STATION,
            "carton_id": self._carton_ids,
            "total_cartons": len(self._carton_ids),
            "product_code": unique_product_codes,
            "lot_batch": unique_lot_batches,
            "min_expiry_date": min_expiry,
            "scan_timestamp": now.strftime("%Y_%m_%dT%H:%M:%S"),
            "camera_id": CAMERA_ID,
            "confidence_score": CONFIDENCE_SCORE,
            "exceptions": self._exceptions
        }

    @staticmethod
    def _generate_pallet_id(now: Optional[datetime] = None) -> str:
        if now is None:
            now = datetime.now()
        date_str = now.strftime("%Y%m%d")
        seq = random.randint(0, 9999)
        return f"{WAREHOUSE_CODE}-{date_str}-{STATION}-{seq:04d}"
