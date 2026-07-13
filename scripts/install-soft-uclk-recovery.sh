#!/bin/sh
set -eu

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

install -m 0755 "$SOURCE_DIR/gpu45-soft-uclk.py" /usr/local/sbin/gpu45-soft-uclk
install -m 0755 "$SOURCE_DIR/gpu45-soft-uclk-inventory.sh" /usr/local/sbin/gpu45-soft-uclk-inventory
install -m 0755 "$SOURCE_DIR/gpu45-soft-uclk-boot-recovery.sh" /usr/local/sbin/gpu45-soft-uclk-boot-recovery.sh
install -m 0644 "$SOURCE_DIR/gpu45-soft-uclk-boot-recovery.service" /etc/systemd/system/gpu45-soft-uclk-boot-recovery.service
systemctl daemon-reload
systemctl enable gpu45-soft-uclk-boot-recovery.service
