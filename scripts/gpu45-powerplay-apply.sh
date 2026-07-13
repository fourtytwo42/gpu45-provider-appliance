#!/bin/sh
set -eu

GPU=${GPU45_GPU_DEVICE_PATH:-/sys/class/drm/card1/device}
STOCK_TABLE=${GPU45_STOCK_PP_TABLE:-/etc/gpu45/powerplay/v620-stock.pp_table}
RESOURCE_DB=${GPU45_RESOURCE_DB:-/var/lib/gpu45/resource-manager.db}
STATE_DIR=${GPU45_POWERPLAY_STATE_DIR:-/var/lib/gpu45/powerplay-guard}
SERVICES="llama-openai.service qwen3-tts-api.service gpu45-image-api.service wan2-video-api.service gpu45-whisper-api.service"

candidate=${1:-}
clock=${2:-}
guard_seconds=${3:-900}

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ -n "$candidate" ] && [ -f "$candidate" ] || { echo "candidate table is required" >&2; exit 2; }
case "$clock" in 1025|1050) ;; *) echo "clock must be 1025 or 1050 MHz" >&2; exit 2 ;; esac

/usr/local/sbin/gpu45-powerplay validate --stock "$STOCK_TABLE" --candidate "$candidate" --clock "$clock"

if [ -f "$RESOURCE_DB" ]; then
  active_leases=$(sqlite3 "$RESOURCE_DB" "select count(*) from leases where status in ('active','queued');")
  [ "$active_leases" = "0" ] || { echo "refusing with $active_leases active or queued GPU leases" >&2; exit 1; }
fi

for service in $SERVICES; do
  systemctl stop "$service" 2>/dev/null || true
done
for _ in $(seq 1 90); do
  used=$(cat "$GPU/mem_info_vram_used" 2>/dev/null || echo 99999999999)
  [ "$used" -lt 2000000000 ] && break
  sleep 1
done
[ "$used" -lt 2000000000 ] || { echo "VRAM did not return below 2 GB: $used" >&2; exit 1; }

/usr/local/sbin/gpu45-powerplay-guard arm "$guard_seconds" "uclk-${clock}-evaluation"
mkdir -p "$STATE_DIR"
cp "$candidate" "$STATE_DIR/armed-candidate.pp_table"

if ! timeout 20 cp "$candidate" "$GPU/pp_table"; then
  echo "PowerPlay upload failed; invoking SysRq recovery" >&2
  /usr/local/sbin/gpu45-powerplay-hard-reboot.sh
  exit 1
fi
sleep 3

if ! live_sha=$(cat "$GPU/pp_table" | sha256sum | awk '{print $1}'); then
  echo "PowerPlay readback failed; invoking SysRq recovery" >&2
  /usr/local/sbin/gpu45-powerplay-hard-reboot.sh
  exit 1
fi
candidate_sha=$(sha256sum "$candidate" | awk '{print $1}')
if [ "$live_sha" != "$candidate_sha" ]; then
  echo "PowerPlay readback checksum mismatch; invoking SysRq recovery" >&2
  /usr/local/sbin/gpu45-powerplay-hard-reboot.sh
  exit 1
fi
if ! grep -Eq "3: ${clock}Mhz" "$GPU/pp_dpm_mclk"; then
  echo "requested ${clock} MHz UCLK is unavailable after upload; invoking SysRq recovery" >&2
  /usr/local/sbin/gpu45-powerplay-hard-reboot.sh
  exit 1
fi

python3 - "$STATE_DIR/live-experiment.json" "$clock" "$candidate_sha" <<'PY'
import json, os, sys, time
from pathlib import Path

path = Path(sys.argv[1])
temporary = path.with_suffix(".tmp")
temporary.write_text(json.dumps({
    "clockMHz": int(sys.argv[2]),
    "tableSha256": sys.argv[3],
    "appliedAtEpoch": int(time.time()),
    "state": "testing",
}, indent=2) + "\n", encoding="utf-8")
os.replace(temporary, path)
PY
echo "PowerPlay candidate verified at ${clock} MHz; failsafe remains armed"
