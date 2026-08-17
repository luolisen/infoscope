#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec mosquitto -c "$SCRIPT_DIR/mosquitto.conf" -v
