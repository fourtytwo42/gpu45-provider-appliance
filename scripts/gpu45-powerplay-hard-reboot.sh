#!/bin/sh
set -eu

STATE_DIR=${GPU45_POWERPLAY_STATE_DIR:-/var/lib/gpu45/powerplay-guard}
mkdir -p "$STATE_DIR"
date -u +%Y-%m-%dT%H:%M:%SZ > "$STATE_DIR/failsafe-fired-at"
sync
echo s > /proc/sysrq-trigger
sleep 2
echo u > /proc/sysrq-trigger
sleep 2
echo b > /proc/sysrq-trigger
