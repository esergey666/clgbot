FROM debian:bookworm-slim AS telegram-api-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates cmake g++ git gperf make libssl-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone --recursive --depth 1 https://github.com/tdlib/telegram-bot-api.git . \
    && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/opt/telegram-bot-api \
    && cmake --build build --target install -j 2 \
    && strip /opt/telegram-bot-api/bin/telegram-bot-api


FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV OMP_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV NUMEXPR_NUM_THREADS=1
ENV OCR_ENGINE=rapidocr
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libdmtx0b \
        tesseract-ocr \
        tesseract-ocr-eng \
        tini \
    && ldconfig \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --prefer-binary -r requirements.txt

COPY . .
COPY --from=telegram-api-builder /opt/telegram-bot-api/bin/telegram-bot-api /usr/local/bin/telegram-bot-api

RUN chmod +x /app/start.sh \
    && mkdir -p /app/data/telegram-bot-api /tmp/telegram-bot-api

ENTRYPOINT ["tini", "--"]
CMD ["/bin/sh", "/app/start.sh"]
