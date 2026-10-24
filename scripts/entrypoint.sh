#!/bin/sh
# Start printarr. Runs as the non-root user; tini (PID 1) forwards signals to this process.
set -eu

data_dir=$(dirname "${PRINTARR_DB_PATH:-/data/printarr.db}")
output_dir="${PRINTARR_OUTPUT_DIR:-/data/output}"

if [ ! -d "$data_dir" ] || [ ! -w "$data_dir" ]; then
    echo "printarr: data folder $data_dir is not writable by uid $(id -u)." >&2
    echo "printarr: on the host, make the folder owned by uid 1000 (chown -R 1000:1000)." >&2
    exit 1
fi
mkdir -p "$output_dir" "$data_dir/backups"

echo "printarr: starting on port 8000, data in $data_dir"
# One worker only: the ticket scheduler runs inside this process.
# On SIGTERM, uvicorn stops accepting requests and waits up to 20 s for work in progress.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "8000" \
    --workers 1 \
    --timeout-graceful-shutdown 20
