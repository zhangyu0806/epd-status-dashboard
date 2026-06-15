#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${EPD_UPLOADER_APP_DIR:-/opt/epd-status-dashboard}"
IMAGE_URL="${EPD_IMAGE_URL:-http://127.0.0.1:8088/status.png}"
INTERVAL="${EPD_INTERVAL_SECONDS:-600}"
LOG_FILE="${EPD_UPLOADER_LOG:-$APP_DIR/logs/epd-upload.log}"

mkdir -p "$(dirname "$LOG_FILE")"
cd "$APP_DIR"
exec "$APP_DIR/.venv/bin/python" "$APP_DIR/windows_epd_upload.py" \
  --daemon \
  --image-url "$IMAGE_URL" \
  --interval-seconds "$INTERVAL" \
  --log-file "$LOG_FILE"
