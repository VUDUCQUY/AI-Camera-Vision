# ---------- 1) Build giao diện React ----------
FROM node:22-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN CI=true npm run build

# ---------- 2) Backend Python (CPU) ----------
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    YOLO_CONFIG_DIR=/tmp/Ultralytics
# libgl1 + libglib2.0-0: cần cho opencv-python
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# torch bản CPU (nhẹ hơn bản CUDA ~10 lần), rồi mới tới các thư viện còn lại
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ backend/
COPY weights/best_v2.pt weights/best_v1_original.pt weights/
COPY --from=frontend /fe/build frontend/build

# Chạy bằng user thường, dữ liệu ghi vào /app/uploads và /app/data (gắn volume)
RUN useradd --create-home app && mkdir -p uploads data && chown -R app:app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1
# 1 worker: model YOLO + bộ đệm frame stream nằm trong RAM của process
CMD ["python", "-m", "uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
