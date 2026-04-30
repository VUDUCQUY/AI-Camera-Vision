import requests
import logging
from typing import List

logger = logging.getLogger(__name__)


class WMSApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def send_pallet(self, payload: dict) -> None:
        """Gửi 1 pallet lên /pallet."""
        self._post(f"{self.base_url}/pallet", payload)

    def send_pallets(self, payloads: List[dict]) -> None:
        """Gửi nhiều pallet cùng lúc lên /pallets — mỗi pallet 1 row trên Sheets."""
        self._post(f"{self.base_url}/pallets", payloads)

    def _post(self, url: str, data) -> None:
        try:
            response = requests.post(url, json=data, timeout=10)
            if response.status_code == 200:
                logger.info("WMS API → OK: %s", response.json())
            else:
                logger.error("WMS API → Failed (%s): %s", response.status_code, response.text)
        except Exception as e:
            logger.error("WMS API → Connection error: %s", e)