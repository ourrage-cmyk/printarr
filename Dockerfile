# syntax=docker/dockerfile:1
# printarr image: the API, web UI and ticket worker in one process.
# Build stage makes wheels once, so the runtime stage needs no compiler.

FROM python:3.13-slim AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

FROM python:3.13-slim AS runtime
ARG VERSION=dev
LABEL org.opencontainers.image.title="printarr" \
      org.opencontainers.image.description="Receipt printer API and web UI for the Epson TM-T88V" \
      org.opencontainers.image.source="https://github.com/ourrage-cmyk/printarr" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PRINTARR_DB_PATH=/data/printarr.db \
    PRINTARR_OUTPUT_DIR=/data/output

# tini is PID 1: it forwards SIGTERM to uvicorn and reaps children.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels requirements.txt

WORKDIR /app
COPY app ./app
COPY scripts/entrypoint.sh /usr/local/bin/printarr-entrypoint
RUN chmod 0755 /usr/local/bin/printarr-entrypoint

# Runs as TrueNAS's app user, uid and gid 568. The data folder on the host must be owned by 568
# (see docs/deploy/truenas.md). Nothing is written outside /data: HOME points there, the code is
# read-only to this user, and temporary files use /tmp, which every user can write.
RUN groupadd --gid 568 printarr \
    && useradd --uid 568 --gid 568 --no-create-home --home-dir /data --shell /usr/sbin/nologin printarr \
    && mkdir -p /data \
    && chown 568:568 /data
ENV HOME=/data
USER 568:568

VOLUME ["/data"]
EXPOSE 8000
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/printarr-entrypoint"]
