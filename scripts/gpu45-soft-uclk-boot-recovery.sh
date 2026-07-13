#!/bin/sh
set -eu

GPU=${GPU45_GPU_DEVICE_PATH:-/sys/class/drm/card1/device}
STATE_DIR=${GPU45_SOFT_UCLK_STATE_DIR:-/var/lib/gpu45/soft-uclk}
MARKER="$STATE_DIR/experiment-armed.json"
RECOVERY="$STATE_DIR/last-recovery.json"

[ -f "$MARKER" ] || exit 0
echo "gpu45 soft-uclk recovery: unfinished experiment found" >&2

for _ in $(seq 1 60); do
  [ -r "$GPU/pp_dpm_mclk" ] && break
  sleep 1
done
[ -r "$GPU/pp_dpm_mclk" ] || { echo "gpu45 soft-uclk recovery: GPU sysfs unavailable" >&2; exit 1; }

printf '%s\n' auto > "$GPU/power_dpm_force_performance_level"
max_clock=$(sed -n 's/^[0-9][0-9]*: \([0-9][0-9]*\)Mhz.*$/\1/p' "$GPU/pp_dpm_mclk" | sort -n | tail -1)
[ "$max_clock" = "1000" ] || { echo "gpu45 soft-uclk recovery: expected 1000 MHz VBIOS ceiling, got $max_clock" >&2; exit 1; }

mkdir -p "$STATE_DIR"
python3 - "$MARKER" "$RECOVERY" "$max_clock" <<'PY'
import json, os, sys, time
from pathlib import Path

marker = Path(sys.argv[1])
output = Path(sys.argv[2])
payload = json.loads(marker.read_text(encoding="utf-8"))
payload.update({
    "state": "recovered",
    "recoveredAtEpoch": int(time.time()),
    "measuredMaxClockMHz": int(sys.argv[3]),
})
temporary = output.with_suffix(".tmp")
temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.replace(temporary, output)
PY

/usr/local/sbin/gpu45-powerplay-guard cancel >/dev/null 2>&1 || true
rm -f "$MARKER"
echo "gpu45 soft-uclk recovery: stock 1000 MHz ceiling verified" >&2
