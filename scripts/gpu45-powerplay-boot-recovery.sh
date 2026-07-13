#!/bin/sh
set -eu

GPU=${GPU45_GPU_DEVICE_PATH:-/sys/class/drm/card1/device}
STATE_DIR=${GPU45_POWERPLAY_STATE_DIR:-/var/lib/gpu45/powerplay-guard}
MARKER="$STATE_DIR/experiment-armed.json"
STOCK_TABLE=${GPU45_STOCK_PP_TABLE:-/etc/gpu45/powerplay/v620-stock.pp_table}
EXPECTED_SHA=a6fc019fdada096422629293bee778e8857af3330fd2dc2de42dd9d9d921b1c8

[ -f "$MARKER" ] || exit 0
echo "gpu45 powerplay recovery: unfinished experiment found; forcing stock table" >&2

for _ in $(seq 1 60); do
  [ -w "$GPU/pp_table" ] && break
  sleep 1
done
if [ ! -w "$GPU/pp_table" ]; then
  echo "gpu45 powerplay recovery: pp_table did not become writable" >&2
  exit 1
fi

actual_stock_sha=$(sha256sum "$STOCK_TABLE" | awk '{print $1}')
if [ "$actual_stock_sha" != "$EXPECTED_SHA" ]; then
  echo "gpu45 powerplay recovery: refusing unexpected stock checksum $actual_stock_sha" >&2
  exit 1
fi

cp "$STOCK_TABLE" "$GPU/pp_table"
sleep 2
live_sha=$(cat "$GPU/pp_table" | sha256sum | awk '{print $1}')
if [ "$live_sha" != "$EXPECTED_SHA" ]; then
  echo "gpu45 powerplay recovery: stock readback mismatch $live_sha" >&2
  exit 1
fi

mkdir -p "$STATE_DIR"
date -u +%Y-%m-%dT%H:%M:%SZ > "$STATE_DIR/last-stock-recovery-at"
systemctl stop gpu45-powerplay-failsafe.timer gpu45-powerplay-failsafe.service 2>/dev/null || true
systemctl reset-failed gpu45-powerplay-failsafe.timer gpu45-powerplay-failsafe.service 2>/dev/null || true
rm -f "$MARKER"
echo "gpu45 powerplay recovery: stock table restored and verified" >&2
