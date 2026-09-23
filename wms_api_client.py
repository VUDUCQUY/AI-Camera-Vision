"""
wms_api_client.py
Client gửi pallet từ CLI (main.py) lên WMS API (wms_api.py, route POST /pallets).
Nếu server bật đăng nhập, đặt cùng biến WMS_BASIC_AUTH="user:mật_khẩu" ở máy chạy CLI.
"""
import logging
import os
from typing import List

import requests

logger = logging.getLogger(__name__)


class WMSApiClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        user, _, password = os.environ.get("WMS_BASIC_AUTH", "").partition(":")
        self.auth = (user, password) if user else None

    def send_pallets(self, payloads: List[dict]) -> None:
        """Gửi nhiều pallet cùng lúc lên /pallets — mỗi pallet 1 row trên Sheets."""
        self._post(f"{self.base_url}/pallets", payloads)

    def _post(self, url: str, data) -> None:
        try:
            response = requests.post(url, json=data, auth=self.auth, timeout=10)
            if response.status_code == 200:
                logger.info("WMS API → OK: %s", response.json())
            else:
                logger.error("WMS API → Failed (%s): %s", response.status_code, response.text)
        except Exception as e:
            logger.error("WMS API → Connection error: %s", e)