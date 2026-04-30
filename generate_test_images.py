"""
generate_test_images.py
Utility script that creates sample QR-code images under ./images/ so you can
run the main system without a physical scanner or real warehouse photos.

Run once before running main.py:
    python generate_test_images.py
"""

from pathlib import Path

import qrcode
import numpy as np
import cv2

# ──────────────────────────────────────────────────────────────────────────────
# Test data: (filename, [list of QR payloads in that image])
# ──────────────────────────────────────────────────────────────────────────────
TEST_SCENARIOS = [
    # Image 1: two unique cartons
    (
        "image_01.png",
        [
            "C001|MILK01|L2026|12-2026",
            "C002|MILK01|L2026|12-2026",
        ],
    ),
    # Image 2: one new carton + duplicate of C001
    (
        "image_02.png",
        [
            "C001|MILK01|L2026|12-2026",   # duplicate → should be ignored
            "C003|MILK01|L2026|11-2026",
        ],
    ),
    # Image 3: single carton with earlier expiry
    (
        "image_03.png",
        [
            "C004|MILK01|L2026|06-2026",
        ],
    ),
    # Image 4: carton with inconsistent product (triggers warning)
    (
        "image_04.png",
        [
            "C005|JUICE02|L2026|12-2026",
        ],
    ),
]


def make_multi_qr_image(payloads: list[str], output_path: Path) -> None:
    """Render multiple QR codes side-by-side into one PNG."""
    cell_size = 200   # pixels per QR cell (square)
    padding = 20

    qr_images = []
    for payload in payloads:
        qr = qrcode.QRCode(box_size=5, border=2)
        qr.add_data(payload)
        qr.make(fit=True)
        pil_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        # Resize to uniform cell
        arr = np.array(pil_img)
        arr = cv2.resize(arr, (cell_size, cell_size), interpolation=cv2.INTER_AREA)
        qr_images.append(arr)

    total_w = len(qr_images) * cell_size + (len(qr_images) + 1) * padding
    total_h = cell_size + 2 * padding

    canvas = np.full((total_h, total_w, 3), 240, dtype=np.uint8)  # light-grey bg

    for i, qr_arr in enumerate(qr_images):
        x = padding + i * (cell_size + padding)
        y = padding
        canvas[y : y + cell_size, x : x + cell_size] = qr_arr

    bgr = cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(output_path), bgr)
    print(f"  Created: {output_path}  ({len(payloads)} QR code(s))")


def main() -> None:
    out_folder = Path("images")
    out_folder.mkdir(exist_ok=True)

    print("Generating test QR images …\n")
    for filename, payloads in TEST_SCENARIOS:
        make_multi_qr_image(payloads, out_folder / filename)

    print("\nDone. Run the main system with:")
    print("  python main.py --folder ./images")


if __name__ == "__main__":
    main()
