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

# ── Local modules ──────────────────────────────────────────────────────────────
from decoder import QRDecoder
from pallet_manager import PalletManager
from parser import QRParser
from utils import configure_logging, print_banner, print_section, wait_for_space

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="QR-based warehouse palletizing system",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--folder",
        type=str,
        default="./images",
        help="Path to folder containing QR-code images.",
    )
    ap.add_argument(
        "--output",
        type=str,
        default="output.json",
        help="Path for the output JSON file.",
    )
    ap.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    return ap.parse_args()


def process_folder(folder: Path, decoder: QRDecoder, parser: QRParser, pallet: PalletManager) -> None:
    """Walk all images in *folder* and populate *pallet*."""

    image_results = decoder.decode_folder(folder)

    if not image_results:
        logger.warning("No images found in folder: %s", folder)
        return

    total_images = len(image_results)
    print_section(f"Processing {total_images} image(s) from '{folder}'")

    for idx, (filename, payloads) in enumerate(image_results, start=1):
        print(f"\n  [{idx}/{total_images}] Image: {filename}")

        if not payloads:
            print("    ⚠  No QR codes detected.")
            continue

        for raw in payloads:
            carton = parser.parse(raw)
            if carton is None:
                print(f"    ✗  Failed to parse QR payload: '{raw}'")
                continue

            added = pallet.add_carton(carton)
            if added:
                print(f"    ✓  Added   → {carton.carton_id}  [{carton.product_code} / {carton.lot_batch} / exp:{carton.expiry_date}]")
            else:
                print(f"    ↩  Dup     → {carton.carton_id} (skipped)")

    print()
    print(f"  {pallet.summary()}")


def main() -> None:
    args = parse_args()
    configure_logging(getattr(logging, args.log_level))

    print_banner("QR Warehouse Palletizing System  v1.0")

    folder = Path(args.folder)
    if not folder.exists() or not folder.is_dir():
        logger.error("Image folder does not exist or is not a directory: %s", folder)
        sys.exit(1)

    decoder = QRDecoder()
    parser = QRParser()
    pallet = PalletManager()

    # ── Phase 1: scan all images ───────────────────────────────────────────────
    process_folder(folder, decoder, parser, pallet)

    if pallet.carton_count == 0:
        logger.error("No cartons were added to the pallet. Nothing to finalize.")
        sys.exit(1)

    # ── Phase 2: wait for SPACE ────────────────────────────────────────────────
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
