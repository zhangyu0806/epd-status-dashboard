#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${EPD_STATUS_APP_DIR:-/opt/epd-status-dashboard}"
CONFIG="${EPD_STATUS_CONFIG:-$APP_DIR/config.yaml}"
OUTPUT="${EPD_STATUS_OUTPUT:-$APP_DIR/public/status.png}"

mkdir -p "$(dirname "$OUTPUT")"
cd "$APP_DIR"
exec "$APP_DIR/.venv/bin/python" "$APP_DIR/generate.py" --config "$CONFIG" --output "$OUTPUT"
