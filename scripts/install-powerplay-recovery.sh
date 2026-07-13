#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
GPU=/sys/class/drm/card1/device
POWERPLAY_DIR=/etc/gpu45/powerplay
STOCK_TABLE="$POWERPLAY_DIR/v620-stock.pp_table"
EXPECTED_SHA=a6fc019fdada096422629293bee778e8857af3330fd2dc2de42dd9d9d921b1c8

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
install -d -m 0755 "$POWERPLAY_DIR" /var/lib/gpu45/powerplay-guard

if [ ! -f "$STOCK_TABLE" ]; then
  cat "$GPU/pp_table" > "$STOCK_TABLE"
  chmod 0644 "$STOCK_TABLE"
fi
actual_sha=$(sha256sum "$STOCK_TABLE" | awk '{print $1}')
if [ "$actual_sha" != "$EXPECTED_SHA" ]; then
  echo "stock PowerPlay checksum mismatch: $actual_sha" >&2
  exit 1
fi

install -m 0755 "$ROOT/scripts/gpu45-powerplay.py" /usr/local/sbin/gpu45-powerplay
install -m 0755 "$ROOT/scripts/gpu45-powerplay-hard-reboot.sh" /usr/local/sbin/gpu45-powerplay-hard-reboot.sh
install -m 0755 "$ROOT/scripts/gpu45-powerplay-guard.sh" /usr/local/sbin/gpu45-powerplay-guard
install -m 0755 "$ROOT/scripts/gpu45-powerplay-apply.sh" /usr/local/sbin/gpu45-powerplay-apply
install -m 0755 "$ROOT/scripts/gpu45-powerplay-boot-recovery.sh" /usr/local/sbin/gpu45-powerplay-boot-recovery.sh
install -m 0644 "$ROOT/scripts/gpu45-powerplay-boot-recovery.service" /etc/systemd/system/gpu45-powerplay-boot-recovery.service
systemctl daemon-reload
systemctl enable gpu45-powerplay-boot-recovery.service
echo "PowerPlay recovery guard installed with stock checksum $actual_sha"
