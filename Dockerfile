FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PRINTARR_DB_PATH=/data/printarr.db \
    PRINTARR_OUTPUT_DIR=/data/output

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY docs ./docs

RUN useradd --create-home --uid 1000 printarr \
    && mkdir -p /data \
    && chown printarr:printarr /data
USER printarr

VOLUME ["/data"]
EXPOSE 8000

# One worker only: the ticket scheduler runs inside this process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"
