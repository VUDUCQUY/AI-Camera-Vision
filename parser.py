"""
parser.py
Parses raw QR string payloads into structured CartonData objects.

QR format:  carton_id|product_code|lot_batch|expiry
Expiry in:  MM-YYYY   →  stored as YYYY_MM_DD (day forced to 01)
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional, Any

logger = logging.getLogger(__name__)

_EXPIRY_RE = re.compile(r"^(\d{2})-(\d{4})$")


@dataclass
class CartonData:
    """Structured representation of a single carton QR scan."""

    carton_id: str
    product_code: str
    lot_batch: str
    expiry_date: str  # YYYY_MM_DD
    is_exception: bool = False
    raw_data: str = ""

class QRParser:
    """Parses a raw QR string into a CartonData instance."""

    DELIMITER = "|"
    EXPECTED_FIELDS = 4

    def parse(self, raw: str) -> CartonData | None:
        """
        Parse a raw QR payload string.

        Args:
            raw: The decoded QR string, e.g. "C001|MILK01|L2026|12-2026".

        Returns:
            CartonData on success, None on parse failure.
        """
        parts = raw.strip().split(self.DELIMITER)

        if len(parts) != self.EXPECTED_FIELDS:
            return CartonData(
                carton_id="UNKNOWN",
                product_code="UNKNOWN",
                lot_batch="UNKNOWN",
                expiry_date="UNKNOWN",
                is_exception=True,
                raw_data=raw
            )
        carton_id, product_code, lot_batch, expiry_raw = (p.strip() for p in parts)

        expiry_date = self._parse_expiry(expiry_raw)
        if expiry_date is None:
            logger.error("Invalid expiry date format '%s' in QR: '%s'", expiry_raw, raw)
            return None

        return CartonData(
            carton_id=carton_id,
            product_code=product_code,
            lot_batch=lot_batch,
            expiry_date=expiry_date,
            is_exception=False,
            raw_data=raw
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_expiry(expiry_raw: str) -> str | None:
        """
        Convert MM-YYYY  →  YYYY_MM_DD (day = 01).

        Returns formatted string or None if pattern does not match or month is invalid.
        """
        m = _EXPIRY_RE.match(expiry_raw)
        if not m:
            return None
        month, year = m.group(1), m.group(2)
        if not (1 <= int(month) <= 12):
            return None
        return f"{year}_{month}_01"
