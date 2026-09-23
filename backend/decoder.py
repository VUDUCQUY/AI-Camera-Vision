"""
backend/decoder.py
Giải mã QR nhiều tầng cho crop do YOLO cắt ra (hoặc cả ảnh), dừng ngay khi đọc được:

  1. zxing-cpp trên ảnh xám gốc                     ~2ms — đa số crop xong ở đây
  2. WeChat CNN + super-resolution                  chỉ khi có opencv-contrib + model trong weights/wechat
  3. zxing-cpp trên các biến thể tiền xử lý         nhiễu, mờ nhẹ, tối/lóa, mã rất nhỏ (camera 2K)
  4. Khử nhòe chuyển động (Wiener)                  theo hướng nhòe ước lượng từ gradient

Tầng 3-4 chạy trên bản thu nhỏ nếu crop quá to, và bỏ các mã quá ngắn (thường là đọc sai từ nhiễu).
Thiếu zxing-cpp thì OpenCV QRCodeDetector thay zxing ở mọi tầng (chậm và kém hơn).
"""
import logging
from pathlib import Path
from typing import Iterator, List, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

Result = Tuple[str, np.ndarray]  # (nội dung, 4 góc Nx2 theo toạ độ ảnh gốc)

# ============================================================== CẤU HÌNH
# Crop có cạnh dài nhỏ hơn mức này được coi là "mã nhỏ" → thử thêm các biến thể phóng to mạnh
SMALL_CROP_SIDE = 400
# Crop lớn hơn mức này (px, cạnh dài) được thu nhỏ trước khi chạy tầng 3-4
# (YOLO bắt nhầm cả khung hình 2000px từng tốn ~10s/crop)
MAX_SIDE_FOR_HEAVY_STAGES = 800
# Mã đọc ra ở tầng 3-4 phải dài ít nhất chừng này ký tự
# (mã sai quan sát được đều là 4 chữ số: '8178', '6434', '6432'; mã thật dài >= 10)
MIN_LEN_AFTER_PREPROCESS = 6
# Độ bất đẳng hướng của gradient (min/max) trên mức này → ảnh không nhòe theo hướng rõ rệt, bỏ khử nhòe
DEBLUR_MAX_ANISOTROPY = 0.7
# Bộ tham số khử nhòe, xếp theo tỉ lệ cứu được trên ảnh test (cao → thấp):
# (lệch góc so với hướng ước lượng, độ dài vệt nhòe px, hằng số nhiễu Wiener K)
DEBLUR_BANK = (
    [(0, L, K) for L in (11, 15, 19, 9, 23, 27) for K in (0.005, 0.03)]
    + [(d, L, K) for d in (15, -15) for L in (11, 15) for K in (0.005, 0.03)]
)

# ============================================================== BỘ ĐỌC
# Chính: zxing-cpp (nhanh, chịu nhiễu tốt hơn OpenCV)
try:
    import zxingcpp
    _ZX_FORMAT = zxingcpp.BarcodeFormat.QRCode
except ImportError:
    zxingcpp = None
    logger.warning("Chưa cài zxing-cpp (pip install zxing-cpp) — chỉ dùng OpenCV")

# Phụ: WeChat QR (CNN + super-resolution), cần opencv-contrib + model
_WECHAT_DIR = Path(__file__).resolve().parents[1] / "weights" / "wechat"


def _make_wechat():
    files = [_WECHAT_DIR / f for f in ("detect.prototxt", "detect.caffemodel", "sr.prototxt", "sr.caffemodel")]
    if not hasattr(cv2, "wechat_qrcode_WeChatQRCode") or not all(f.exists() for f in files):
        return None
    try:
        return cv2.wechat_qrcode_WeChatQRCode(*map(str, files))
    except cv2.error as e:
        logger.debug(f"WeChat QR không khởi tạo được: {e}")
        return None


def _make_opencv_detector():
    try:
        return cv2.QRCodeDetectorAruco()
    except AttributeError:
        return cv2.QRCodeDetector()


_WECHAT = _make_wechat()
_OPENCV = _make_opencv_detector()


def _read_zxing(gray: np.ndarray, scale: float = 1.0) -> List[Result]:
    """Đọc QR bằng zxing-cpp. `scale`: hệ số ảnh đã bị phóng → quy toạ độ về ảnh gốc."""
    if zxingcpp is None:
        return []
    out = []
    for r in zxingcpp.read_barcodes(gray, formats=_ZX_FORMAT):
        if r.valid and r.text.strip():
            p = r.position
            pts = np.array([[p.top_left.x, p.top_left.y], [p.top_right.x, p.top_right.y],
                            [p.bottom_right.x, p.bottom_right.y], [p.bottom_left.x, p.bottom_left.y]],
                           dtype=np.float32) / scale
            out.append((r.text, pts))
    return out


def _read_wechat(img: np.ndarray, scale: float = 1.0) -> List[Result]:
    if _WECHAT is None:
        return []
    texts, points = _WECHAT.detectAndDecode(img)
    return [(t, np.asarray(p, dtype=np.float32).reshape(-1, 2) / scale)
            for t, p in zip(texts, points) if t and t.strip()]


def _read_opencv(gray: np.ndarray, scale: float = 1.0) -> List[Result]:
    try:
        ok, texts, points, _ = _OPENCV.detectAndDecodeMulti(gray)
    except cv2.error as e:
        logger.debug(f"OpenCV detector error: {e}")
        return []
    if not ok or points is None:
        return []
    return [(t, np.asarray(p, dtype=np.float32).reshape(-1, 2) / scale)
            for t, p in zip(texts, points) if t and t.strip()]


def _drop_short(results: List[Result]) -> List[Result]:
    return [(t, p) for t, p in results if len(t.strip()) >= MIN_LEN_AFTER_PREPROCESS]


# ============================================================== XỬ LÝ ẢNH
def _to_gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


def _upscale(gray: np.ndarray, f: float, interpolation: int = cv2.INTER_CUBIC) -> np.ndarray:
    return cv2.resize(gray, None, fx=f, fy=f, interpolation=interpolation)


def _unsharp(gray: np.ndarray, amount: float = 1.5, sigma: float = 1.5) -> np.ndarray:
    blur = cv2.GaussianBlur(gray, (0, 0), sigma)
    return cv2.addWeighted(gray, 1 + amount, blur, -amount, 0)


def _limit_side(img: np.ndarray, max_side: int) -> Tuple[np.ndarray, float]:
    """Thu nhỏ để cạnh dài <= max_side. Trả về (ảnh, hệ số thu nhỏ <= 1)."""
    h, w = img.shape[:2]
    if max(h, w) <= max_side:
        return img, 1.0
    f = max_side / max(h, w)
    return cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA), f


def _motion_psf(length: int, angle: float) -> np.ndarray:
    """Kernel nhòe chuyển động: đoạn thẳng dài `length` px, nghiêng `angle` độ."""
    size = (length + 4) | 1
    c = size // 2
    k = np.zeros((size, size), np.float32)
    k[c, c - length // 2:c + length // 2 + 1] = 1
    k = cv2.warpAffine(k, cv2.getRotationMatrix2D((c, c), angle, 1.0), (size, size))
    return k / k.sum()


def _blur_direction(gray: np.ndarray) -> Tuple[int, float]:
    """
    Ước lượng hướng nhòe: nhòe chuyển động làm mất gradient DỌC theo hướng chuyển động.
    Trả về (góc 0..165, độ bất đẳng hướng = năng lượng min/max; càng nhỏ càng nhòe rõ).
    """
    g = gray.astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1)
    energy = []
    for a in range(0, 180, 15):
        r = np.deg2rad(a)
        d = gx * np.cos(r) - gy * np.sin(r)  # trục y ảnh hướng xuống
        energy.append((float(np.mean(d * d)), a))
    lo, hi = min(energy), max(energy)
    return lo[1], lo[0] / max(hi[0], 1e-6)


# ============================================================== BIẾN THỂ (ảnh xám, hệ số phóng)
def _tiny_qr_variants(gray: np.ndarray) -> Iterator[Tuple[np.ndarray, float]]:
    """
    Mã rất nhỏ (~1.5px/ô): phóng to mạnh rồi nhị phân hoá / làm nét.
    4 biến thể này (chọn bằng set-cover trên ảnh camera thật) phủ mọi ca cứu được.
    """
    lan = cv2.INTER_LANCZOS4
    up3 = _upscale(gray, 3, lan)
    yield cv2.threshold(cv2.GaussianBlur(up3, (0, 0), 1.2), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1], 3.0
    up5 = cv2.GaussianBlur(_upscale(gray, 5, lan), (0, 0), 2.0)
    yield cv2.adaptiveThreshold(up5, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 2), 5.0
    yield _unsharp(_upscale(gray, 6), 2.0, 3.6), 6.0
    yield _unsharp(_upscale(gray, 8, lan), 1.0, 4.8), 8.0


def _preprocess_variants(img: np.ndarray) -> Iterator[Tuple[np.ndarray, float]]:
    """
    Biến thể tiền xử lý theo thứ tự rẻ → đắt. Chỉ giữ những biến thể thực sự cứu được
    ảnh khó: nhiễu muối tiêu, mã nhỏ/xa, mờ, tối/lóa.
    """
    gray = _to_gray(img)
    yield cv2.medianBlur(gray, 3), 1.0                      # nhiễu muối tiêu
    if max(gray.shape[:2]) < SMALL_CROP_SIDE:                # mã nhỏ/xa (camera 2K)
        yield from _tiny_qr_variants(gray)
    yield _unsharp(gray), 1.0                                # mờ nhẹ
    yield cv2.createCLAHE(3.0, (8, 8)).apply(gray), 1.0      # thiếu sáng / lóa
    up = _upscale(gray, 2)
    yield up, 2.0
    blur = cv2.GaussianBlur(up, (5, 5), 0)
    yield cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1], 2.0
    yield cv2.adaptiveThreshold(up, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5), 2.0


def _deblur_variants(img: np.ndarray) -> Iterator[Tuple[np.ndarray, float]]:
    """
    Khử nhòe chuyển động bằng Wiener deconvolution theo hướng đã ước lượng.
    Mỗi kernel cho 2 bản: lọc median (khử vân ringing) và bản thô.
    Phổ ảnh tính 1 lần, dùng lại cho mọi kernel.
    """
    gray = _to_gray(img)
    angle, anisotropy = _blur_direction(gray)
    if anisotropy > DEBLUR_MAX_ANISOTROPY:  # không nhòe theo hướng rõ rệt (thường là YOLO bắt nhầm)
        return

    pad = 32
    h, w = gray.shape[:2]
    H, W = cv2.getOptimalDFTSize(h + 2 * pad), cv2.getOptimalDFTSize(w + 2 * pad)
    src = cv2.copyMakeBorder(gray, pad, H - h - pad, pad, W - w - pad, cv2.BORDER_REPLICATE)
    G = np.fft.rfft2(src.astype(np.float32) / 255.0)

    kernel_fft = {}
    for delta, length, K in DEBLUR_BANK:
        key = ((angle + delta) % 180, length)
        if key not in kernel_fft:
            k = _motion_psf(length, key[0])
            kp = np.zeros((H, W), np.float32)
            kp[:k.shape[0], :k.shape[1]] = k
            kernel_fft[key] = np.fft.rfft2(np.roll(kp, (-(k.shape[0] // 2), -(k.shape[1] // 2)), (0, 1)))
        Hk = kernel_fft[key]
        f = np.fft.irfft2(G * np.conj(Hk) / (np.abs(Hk) ** 2 + K), s=(H, W))
        restored = np.clip(f[pad:pad + h, pad:pad + w] * 255, 0, 255).astype(np.uint8)
        yield cv2.medianBlur(restored, 3), 1.0
        yield restored, 1.0


# ============================================================== API
class QRDecoder:
    """Giải mã QR nhiều tầng (xem docstring đầu file)."""

    def decode_image(self, image) -> List[str]:
        """Ảnh (ndarray BGR hoặc đường dẫn) → danh sách nội dung QR."""
        return [r[0] for r in self.decode_image_with_points(image)]

    def decode_image_with_points(self, image) -> List[Result]:
        """Ảnh → [(nội dung, 4 góc theo toạ độ ảnh gốc), ...]."""
        img = self._ensure_numpy_image(image)
        if img is None or img.size == 0:
            return []
        for results in self._stages(img):
            results = self._dedupe(results)
            if results:
                return results
        return []

    def decode_folder(self, folder) -> List[tuple]:
        """Thư mục ảnh → [(tên file, [nội dung QR...]), ...]."""
        folder = Path(folder)
        extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
        image_files = sorted(p for p in folder.iterdir() if p.suffix.lower() in extensions)
        return [(p.name, self.decode_image(p)) for p in image_files]

    @staticmethod
    def _stages(img: np.ndarray) -> Iterator[List[Result]]:
        """Chạy lần lượt từng tầng; biến thể chỉ được tính khi tầng trước thất bại."""
        read = _read_zxing if zxingcpp is not None else _read_opencv
        yield read(_to_gray(img))
        yield _read_wechat(img)
        small, shrink = _limit_side(img, MAX_SIDE_FOR_HEAVY_STAGES)  # toạ độ quy về gốc qua `shrink`
        for variant, scale in _preprocess_variants(small):
            yield _drop_short(read(variant, scale * shrink))
        for variant, scale in _deblur_variants(small):
            yield _drop_short(read(variant, scale * shrink))

    @staticmethod
    def _dedupe(results: List[Result]) -> List[Result]:
        seen, out = set(), []
        for text, pts in results:
            if text not in seen:
                seen.add(text)
                out.append((text, pts))
        return out

    @staticmethod
    def _ensure_numpy_image(image):
        if isinstance(image, (str, Path)):
            return cv2.imdecode(np.fromfile(str(image), dtype=np.uint8), cv2.IMREAD_COLOR)
        return image
