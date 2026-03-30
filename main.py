"""
main.py
Entry point for the QR-based warehouse palletizing system.

Usage:
    python main.py --folder ./images
    python main.py --folder ./images --output output.json --log-level DEBUG
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import cv2
from ultralytics import YOLO

from decoder import QRDecoder
from pallet_manager import PalletManager
from parser import QRParser
from utils import configure_logging, print_banner, print_section, wait_for_space

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}
BBOX_PADDING = 8   # pixels added on each side of YOLO bbox before decoding


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="QR-based warehouse palletizing system",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--folder",    type=str, default="./images",      help="Folder containing QR-code images.")
    ap.add_argument("--output",    type=str, default="output.json",   help="Output JSON file path.")
    ap.add_argument("--log-level", type=str, default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"],    help="Logging verbosity.")
    return ap.parse_args()


def _pad_crop(img, x1: int, y1: int, x2: int, y2: int, pad: int = BBOX_PADDING):
    """Return a padded crop, clamped to image boundaries."""
    h, w = img.shape[:2]
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(w, x2 + pad)
    y2 = min(h, y2 + pad)
    return img[y1:y2, x1:x2]


def process_folder(
    folder: Path,
    model: YOLO,
    decoder: QRDecoder,
    parser: QRParser,
    pallet: PalletManager,
) -> None:
    """
    Pipeline per image:
      YOLO detect → bbox crop (+ padding) → decoder.decode_array() → parser → pallet
    """
    image_files = sorted(
        p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS
    )

    if not image_files:
        logger.warning("No images found in folder: %s", folder)
        return

    print_section(f"Processing {len(image_files)} image(s) from '{folder}'")

    for idx, img_path in enumerate(image_files, start=1):
        print(f"\n  [{idx}/{len(image_files)}] Image: {img_path.name}")

        img = cv2.imread(str(img_path))
        if img is None:
            logger.warning("Could not read image: %s", img_path.name)
            continue

        # ── YOLO detection ──────────────────────────────────────────────────
        results = model(img, verbose=False)

        all_boxes = []
        for r in results:
            if r.boxes is not None:
                all_boxes.extend(r.boxes.xyxy.cpu().numpy().tolist())

        if not all_boxes:
            print("    ⚠  No QR codes detected by YOLO.")
            continue

        # ── Per-bbox: crop → decode → parse → add ──────────────────────────
        for box in all_boxes:
            x1, y1, x2, y2 = map(int, box)
            crop = _pad_crop(img, x1, y1, x2, y2)

            payloads = decoder.decode_array(crop)

            if not payloads:
                logger.debug("Decode failed for bbox %s in %s", box, img_path.name)
                print("    ✗  Decode failed (bbox too blurry or small?)")
                continue

            for raw in payloads:
                carton = parser.parse(raw)
                if carton is None:
                    print(f"    ✗  Parse fail : '{raw}'")
                    continue

                added = pallet.add_carton(carton)
                if added:
                    print(f"    ✓  Added  → {carton.carton_id}"
                          f"  [{carton.product_code} / {carton.lot_batch} / exp:{carton.expiry_date}]")
                else:
                    print(f"    ↩  Dup    → {carton.carton_id} (skipped)")

    print()
    print(f"  {pallet.summary()}")


def main() -> None:
    args = parse_args()
    configure_logging(getattr(logging, args.log_level))
    print_banner("QR Warehouse Palletizing System  v1.0")

    folder = Path(args.folder)
    if not folder.exists() or not folder.is_dir():
        logger.error("Folder not found: %s", folder)
        sys.exit(1)

    # Load model ONCE here, not inside the loop
    model   = YOLO("best.pt")
    decoder = QRDecoder()
    parser  = QRParser()
    pallet  = PalletManager()

    # ── Phase 1: scan ──────────────────────────────────────────────────────────
    process_folder(folder, model, decoder, parser, pallet)

    if pallet.carton_count == 0:
        logger.error("No cartons were added to the pallet. Nothing to finalize.")
        sys.exit(1)

    # ── Phase 2: wait for operator confirmation ────────────────────────────────
    wait_for_space()

    # ── Phase 3: finalize & write JSON ────────────────────────────────────────
    try:
        payload = pallet.finalize(output_path=args.output)
    except (ValueError, RuntimeError) as exc:
        logger.error("Finalization failed: %s", exc)
        sys.exit(1)

    print_banner("Pallet Finalized ✓")
    print(json.dumps(payload, indent=2))
    print(f"\n  → Saved to: {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()