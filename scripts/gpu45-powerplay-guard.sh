#!/bin/sh
set -eu

STATE_DIR=${GPU45_POWERPLAY_STATE_DIR:-/var/lib/gpu45/powerplay-guard}
MARKER="$STATE_DIR/experiment-armed.json"
UNIT=gpu45-powerplay-failsafe

arm() {
  seconds=${1:-600}
  reason=${2:-powerplay-experiment}
  case "$seconds" in
    ''|*[!0-9]*) echo "timeout must be an integer number of seconds" >&2; exit 2 ;;
  esac
  if [ "$seconds" -lt 30 ]; then
    echo "timeout must be at least 30 seconds" >&2
    exit 2
  fi

  mkdir -p "$STATE_DIR"
  systemctl stop "$UNIT.timer" "$UNIT.service" 2>/dev/null || true
  systemctl reset-failed "$UNIT.timer" "$UNIT.service" 2>/dev/null || true
  python3 - "$MARKER" "$seconds" "$reason" <<'PY'
import json, os, socket, sys, time
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "armedAtEpoch": int(time.time()),
    "deadlineEpoch": int(time.time()) + int(sys.argv[2]),
    "host": socket.gethostname(),
    "reason": sys.argv[3],
    "state": "armed",
}
temporary = path.with_suffix(".tmp")
temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, path)
PY
  systemd-run \
    --quiet \
    --unit="$UNIT" \
    --on-active="${seconds}s" \
    --timer-property=AccuracySec=1s \
    /usr/local/sbin/gpu45-powerplay-hard-reboot.sh
  echo "armed $UNIT.timer for ${seconds}s"
}

cancel() {
  systemctl stop "$UNIT.timer" "$UNIT.service" 2>/dev/null || true
  systemctl reset-failed "$UNIT.timer" "$UNIT.service" 2>/dev/null || true
  rm -f "$MARKER"
  echo "cancelled $UNIT.timer"
}

status() {
  if [ -f "$MARKER" ]; then
    cat "$MARKER"
  else
    echo '{"state":"disarmed"}'
  fi
  systemctl --no-pager --full status "$UNIT.timer" 2>/dev/null || true
}

case "${1:-status}" in
  arm) shift; arm "$@" ;;
  cancel) cancel ;;
  status) status ;;
  *) echo "usage: $0 {arm [seconds] [reason]|cancel|status}" >&2; exit 2 ;;
esac
