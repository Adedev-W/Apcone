FROM alpine:3.20

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/scanner-venv/bin:${PATH}"

WORKDIR /service

RUN apk add --no-cache \
    ghostscript \
    ocrmypdf \
    python3 \
    py3-pip \
    qpdf \
    tesseract-ocr \
    tesseract-ocr-data-eng

RUN python3 -m venv /opt/scanner-venv \
    && /opt/scanner-venv/bin/pip install --no-cache-dir \
        grpcio==1.81.0 \
        protobuf==6.33.6

COPY app/proto ./app/proto
COPY scanner_service ./scanner_service

EXPOSE 50051

CMD ["python", "-m", "scanner_service.server"]
