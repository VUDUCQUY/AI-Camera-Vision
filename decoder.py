"""
decoder.py
QR code detection and decoding using OpenCV ONLY — no pyzbar, no system DLLs.

Uses cv2.QRCodeDetectorAruco (OpenCV >= 4.8, bundled in opencv-python wheel).
Falls back to the classic cv2.QRCodeDetector for older builds.
"""

import logging
from pathlib import Path
from typing import List

import cv2

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pick the best available OpenCV QR detector at import time
# ---------------------------------------------------------------------------
def _make_detector():
    """Return the most capable QR detector available in this OpenCV build."""
    try:
        det = cv2.QRCodeDetectorAruco()
        logger.debug("Using cv2.QRCodeDetectorAruco")
        return det
    except AttributeError:
        logger.debug("Falling back to cv2.QRCodeDetector")
        return cv2.QRCodeDetector()


_DETECTOR = _make_detector()


class QRDecoder:
    """Detects and decodes all QR codes found in an image file."""

    def decode_image(self, image_path) -> List[str]:
        image_path = Path(image_path)

        if not image_path.exists():
            logger.error("Image not found: %s", image_path)
            return []

        img = cv2.imread(str(image_path))
        if img is None:
            logger.error("Failed to load image: %s", image_path)
            return []

        # Pass 1: colour image
        payloads = self._detect_all(img)

        # Pass 2: grayscale
        if not payloads:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            payloads = self._detect_all(gray)

        # Pass 3: upscale small images
        if not payloads:
            h, w = img.shape[:2]
            if max(h, w) < 800:
                scale = 800 / max(h, w)
                big = cv2.resize(img, None, fx=scale, fy=scale,
                                 interpolation=cv2.INTER_CUBIC)
                payloads = self._detect_all(big)

        if payloads:
            logger.debug("Decoded %d QR code(s) from %s", len(payloads), image_path.name)
        else:
            logger.warning("No QR codes found in %s", image_path.name)

        return payloads

    def decode_folder(self, folder) -> List[tuple]:
        folder = Path(folder)
        extensions = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}

        image_files = sorted(
            p for p in folder.iterdir() if p.suffix.lower() in extensions
        )

        if not image_files:
            logger.warning("No supported images found in folder: %s", folder)

        results = []
        for img_path in image_files:
            payloads = self.decode_image(img_path)
            results.append((img_path.name, payloads))

        return results

    @staticmethod
    def _detect_all(img) -> List[str]:
        """Run detectAndDecodeMulti and return non-empty decoded strings."""
        try:
            retval, decoded_list, _, _ = _DETECTOR.detectAndDecodeMulti(img)
        except cv2.error as exc:
            logger.debug("detectAndDecodeMulti error: %s", exc)
            return []

        if not retval or decoded_list is None:
            return []

        return [s for s in decoded_list if s and s.strip()]
