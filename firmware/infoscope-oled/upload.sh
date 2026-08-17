#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SKETCH_DIR="$SCRIPT_DIR/infoscope_oled"
PORT=${1:-/dev/ttyUSB0}
ARDUINO_CLI=${ARDUINO_CLI:-arduino-cli}

test -c "$PORT" || { echo "ESP32 serial device not found: $PORT" >&2; exit 1; }
"$ARDUINO_CLI" compile --fqbn esp32:esp32:esp32 --output-dir "$SKETCH_DIR/build" "$SKETCH_DIR"
"$ARDUINO_CLI" upload --fqbn esp32:esp32:esp32 --port "$PORT" --input-dir "$SKETCH_DIR/build" "$SKETCH_DIR"
