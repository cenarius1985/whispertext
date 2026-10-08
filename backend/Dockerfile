# Imagen única para api y worker (ADR-004): mismo código, distinto comando.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MEDIA_DIR=/data/media \
    MODELS_DIR=/data/models

# ffmpeg (wav→mp3, concat), tesseract spa+eng (OCR), piper (TTS)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        tesseract-ocr \
        tesseract-ocr-spa \
        tesseract-ocr-eng \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY wispertext ./wispertext

RUN mkdir -p /data/media /data/models
VOLUME ["/data/media", "/data/models"]

EXPOSE 8000
CMD ["uvicorn", "wispertext.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
