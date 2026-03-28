# QR Warehouse Palletizing System

A modular, production-like Python CLI that scans QR-code images, groups
cartons into a pallet, and outputs a structured JSON manifest on demand.

---

## Project Structure

```
qr_warehouse/
├── main.py                 # Entry point + program flow
├── decoder.py              # QR detection & decoding (OpenCV + pyzbar)
├── parser.py               # QR string → CartonData dataclass
├── pallet_manager.py       # Business logic, dedup, JSON generation
├── utils.py                # Logging setup, SPACE-key wait, print helpers
├── generate_test_images.py # One-off script to create sample QR images
├── requirements.txt
└── README.md
```

---

## Quick Start

### 1. Install system dependency for pyzbar

| OS | Command |
|----|---------|
| Ubuntu / Debian | `sudo apt install libzbar0` |
| macOS | `brew install zbar` |
| Windows | No extra step — wheel bundles zbar |

### 2. Install Python packages

```bash
pip install -r requirements.txt
```

### 3. Generate test images (optional but recommended)

```bash
python generate_test_images.py
```

This creates `./images/` with four PNG files, each containing one or two QR
codes representing the test cartons below.

### 4. Run the system

```bash
python main.py --folder ./images
```

When scanning is complete the console prints a summary and waits.  
Press **SPACE** (then Enter on Windows) to finalize the pallet.

The JSON manifest is saved to `output.json` (configurable via `--output`).

---

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--folder` | `./images` | Path to image folder |
| `--output` | `output.json` | Output JSON file path |
| `--log-level` | `INFO` | `DEBUG / INFO / WARNING / ERROR` |

---

## QR Code Format

```
carton_id|product_code|lot_batch|expiry
C001|MILK01|L2026|12-2026
```

| Field | Format |
|-------|--------|
| `carton_id` | Free string, must be unique |
| `product_code` | Free string |
| `lot_batch` | Free string |
| `expiry` | MM-YYYY → stored as YYYY_MM_DD |

---

## Output JSON Example

```json
{
  "pallet_id": "SGL-20260319-ST01-4821",
  "warehouse_code": "SGL",
  "station": "ST01",
  "carton_id": ["C001", "C002", "C003", "C004"],
  "total_cartons": 4,
  "product_code": "MILK01",
  "lot_batch": "L2026",
  "min_expiry_date": "2026_06_01",
  "scan_timestamp": "2026_03_19T14:32:10",
  "camera_id": "CAM-STATION-01",
  "confidence_score": 1.0
}
```

---

## Business Rules

| Rule | Behaviour |
|------|-----------|
| Duplicate `carton_id` | Silently skipped, logged as INFO |
| Inconsistent `product_code` | WARNING logged, carton still added |
| Inconsistent `lot_batch` | WARNING logged, carton still added |
| `min_expiry_date` | Minimum of all expiry dates |
| `scan_timestamp` | Time of SPACE key press |
| `confidence_score` | Always `1.0` |

---

## Running Tests

```bash
# Verify parser logic without images
python -c "
from parser import QRParser
p = QRParser()
print(p.parse('C001|MILK01|L2026|12-2026'))
print(p.parse('BAD|DATA'))  # returns None
"
```
