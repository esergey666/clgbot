FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV OMP_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV NUMEXPR_NUM_THREADS=1
ENV OCR_ENGINE=rapidocr

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libdmtx0b \
        libdmtx-dev \
        tesseract-ocr \
        tesseract-ocr-eng \
    && ldconfig \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --force-reinstall --no-deps opencv-contrib-python-headless==4.11.0.86 \
    && python -c "from rapidocr import RapidOCR; RapidOCR()"

COPY . .

CMD ["python", "-m", "bot.main"]
