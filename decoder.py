import logging
from pathlib import Path
from typing import List, Tuple
import cv2
import numpy as np

logger = logging.getLogger(__name__)


def _make_detector():
    try:
        det = cv2.QRCodeDetectorAruco()
        logger.debug("Using cv2.QRCodeDetectorAruco")
        return det
    except AttributeError:
        logger.debug("Falling back to cv2.QRCodeDetector")
        return cv2.QRCodeDetector()


_DETECTOR = _make_detector()


def _preprocess_variants(img: np.ndarray) -> List[np.ndarray]:
    """
    Sinh ra nhiều biến thể tiền xử lý từ 1 ảnh crop.
    Mục tiêu: tăng tỉ lệ decode QR bị tối / mờ / nghiêng sáng / nhỏ.
    """
    variants = []

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()
    h, w = gray.shape[:2]

    # 1. Ảnh xám gốc
    variants.append(gray)

    # 2. Làm nét (Sharpening) — rất quan trọng khi crop bị mờ
    kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    sharpened = cv2.filter2D(gray, -1, kernel)
    variants.append(sharpened)

    # 3. Cân bằng sáng thích nghi (CLAHE)
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
    clahe_img = clahe.apply(gray)
    variants.append(clahe_img)

    # 4. Thử nhiều ngưỡng nhị phân khác nhau (Threshold Grid Search)
    for thresh_val in [100, 127, 150]:
        _, t_img = cv2.threshold(gray, thresh_val, 255, cv2.THRESH_BINARY)
        variants.append(t_img)
        # Đảo ngược của từng ngưỡng
        variants.append(cv2.bitwise_not(t_img))

    # 5. Phép toán hình thái học (Morphological Ops) — rất tốt cho mã bị lóa hoặc đứt nét
    kernel = np.ones((3,3), np.uint8)
    variants.append(cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)) # Nối nét
    variants.append(cv2.morphologyEx(gray, cv2.MORPH_OPEN, kernel))  # Tách nét

    # 6. Biến thể xoay (Rotation)
    for angle in [90, 180, 270]:
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(gray, M, (w, h))
        variants.append(rotated)

    # 7. Siêu phân giải kết hợp làm nét (Dành cho mã nhỏ/xa)
    if max(h, w) < 800:
        big = cv2.resize(gray, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
        variants.append(big)
        # Làm nét ảnh phóng to
        k_sharp = np.array([[-1,-1,-1], [-1,11,-1], [-1,-1,-1]])
        variants.append(cv2.filter2D(big, -1, k_sharp))

    return variants


class QRDecoder:
    """Hệ thống giải mã QR đa tầng để đạt tỉ lệ nhận diện tối đa."""

    def decode_image_with_points(self, image) -> List[Tuple[str, np.ndarray]]:
        """Trả về [(nội dung, tọa độ), ...], thử nhiều biến thể preprocessing."""
        img = self._ensure_numpy_image(image)
        if img is None:
            return []

        results: List[Tuple[str, np.ndarray]] = []

        for variant in _preprocess_variants(img):
            new = self._detect_with_details(variant)
            results = self._merge_results(results, new)
            # Dừng sớm nếu đã decode đủ
            if len(results) >= 99:
                break

        return results

    def _detect_with_details(self, img: np.ndarray) -> List[Tuple[str, np.ndarray]]:
        results = []
        
        # Danh sách các bộ phát hiện (Detector) để thử lần lượt
        detectors = [
            _DETECTOR, # Thường là QRCodeDetectorAruco (nếu có)
            cv2.QRCodeDetector() # Bộ chuẩn của OpenCV
        ]

        for det in detectors:
            try:
                # 1. Thử trực tiếp trên ảnh variant
                ok, decoded_list, points_list, _ = det.detectAndDecodeMulti(img)
                if ok and decoded_list:
                    for p, pts in zip(decoded_list, points_list):
                        if p and p.strip():
                            results.append((p, pts))
                
                if results: break # Nếu đã tìm thấy thì dừng lại cho nhanh

                # 2. Thử thêm một bước giãn nở (Dilate) nếu chưa ra - rất tốt cho QR bị mờ hoặc nét mỏng
                kernel = np.ones((3,3), np.uint8)
                dilated = cv2.dilate(img, kernel, iterations=1)
                ok, decoded_list, points_list, _ = det.detectAndDecodeMulti(dilated)
                if ok and decoded_list:
                    for p, pts in zip(decoded_list, points_list):
                        if p and p.strip():
                            results.append((p, pts))
                
                if results: break

            except Exception as e:
                logger.debug(f"Detector error: {e}")
        
        return results

    def _merge_results(self, base, new_found):
        existing = {r[0] for r in base}
        for item in new_found:
            if item[0] not in existing:
                base.append(item)
                existing.add(item[0])
        return base

    def decode_image(self, image) -> List[str]:
        return [r[0] for r in self.decode_image_with_points(image)]

    def _ensure_numpy_image(self, image):
        if isinstance(image, (str, Path)):
            return cv2.imdecode(np.fromfile(str(image), dtype=np.uint8), cv2.IMREAD_COLOR)
        return image

    def decode_folder(self, folder) -> List[tuple]:
        folder = Path(folder)
        extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        image_files = sorted(
            p for p in folder.iterdir() if p.suffix.lower() in extensions
        )
        return [(p.name, self.decode_image(p)) for p in image_files]