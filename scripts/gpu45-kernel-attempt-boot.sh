#!/bin/sh
set -eu

STATE_DIR=${GPU45_SOFT_UCLK_STATE_DIR:-/var/lib/gpu45/soft-uclk}
MARKER="$STATE_DIR/kernel-attempt.json"
OBSERVATION="$STATE_DIR/kernel-observation.json"

[ -f "$MARKER" ] || exit 0
/usr/local/sbin/gpu45-soft-uclk kernel-observe --marker "$MARKER" --output "$OBSERVATION" --kernel "$(uname -r)" >/dev/null
if grep -q '"state": "returned-to-fallback"' "$OBSERVATION"; then
  cp "$OBSERVATION" "$STATE_DIR/last-kernel-fallback.json"
  rm -f "$MARKER"
  echo "gpu45 kernel attempt: returned to fallback; automatic retry disabled" >&2
elif grep -q '"state": "booted-target"' "$OBSERVATION"; then
  echo "gpu45 kernel attempt: target kernel booted and awaits validation" >&2
else
  cp "$OBSERVATION" "$STATE_DIR/last-kernel-unexpected.json"
  rm -f "$MARKER"
  echo "gpu45 kernel attempt: unexpected kernel boot; automatic retry disabled" >&2
fi
