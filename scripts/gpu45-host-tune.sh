#!/bin/sh
set -eu

GPU=/sys/class/drm/card1/device
TUNING_FILE=${GPU45_TUNING_PATH:-/etc/gpu45/gpu-tuning.json}

for _ in $(seq 1 30); do
  if [ -e "$GPU/power_dpm_force_performance_level" ] && [ -e "$GPU/pp_od_clk_voltage" ]; then
    break
  fi
  sleep 1
done

if [ ! -e "$GPU/power_dpm_force_performance_level" ] || [ ! -e "$GPU/pp_od_clk_voltage" ]; then
  echo "gpu45 host tuning skipped: GPU control files are not ready under $GPU" >&2
  exit 0
fi

write_gpu_control() {
  value=$1
  target=$2
  label=$3

  if [ ! -w "$target" ]; then
    echo "gpu45 host tuning warning: $label is not writable at $target" >&2
    return 0
  fi
  if ! echo "$value" > "$target"; then
    echo "gpu45 host tuning warning: failed to write $label=$value to $target" >&2
  fi
}

if [ -f "$TUNING_FILE" ]; then
  if python3 - "$TUNING_FILE" <<'PY'
import json, sys
from pathlib import Path

try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    data = {}
raise SystemExit(0 if data.get("enabled", True) is False else 1)
PY
  then
    write_gpu_control auto "$GPU/power_dpm_force_performance_level" "perf_level"
    echo "gpu45 host tuning disabled; restored automatic GPU performance level" >&2
    exit 0
  fi
  eval "$(python3 - "$TUNING_FILE" <<'PY'
import json, shlex, sys
from pathlib import Path

try:
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    data = {}

def emit(name, value):
    if value is None:
        print(f"{name}=")
    else:
        print(f"{name}={shlex.quote(str(value))}")

emit("PERF_LEVEL", data.get("performanceLevel", "manual"))
emit("VDDGFX_OFFSET_MV", data.get("vddgfxOffsetMv", -40))
emit("POWER_DPM_STATE", data.get("powerDpmState"))
emit("POWER_PROFILE", data.get("powerProfile"))
emit("MCLK_LEVEL", data.get("mclkLevel"))
emit("PP_TABLE_PATH", data.get("ppTablePath"))
PY
)"
else
  PERF_LEVEL=manual
  VDDGFX_OFFSET_MV=-40
  POWER_DPM_STATE=
  POWER_PROFILE=
  MCLK_LEVEL=
  PP_TABLE_PATH=
fi

if [ -n "${PP_TABLE_PATH:-}" ] && [ -r "$PP_TABLE_PATH" ] && [ -w "$GPU/pp_table" ]; then
  cp "$PP_TABLE_PATH" "$GPU/pp_table" || echo "gpu45 host tuning warning: unable to write soft pp_table" >&2
fi
if [ -n "${POWER_DPM_STATE:-}" ] && [ -w "$GPU/power_dpm_state" ]; then
  write_gpu_control "$POWER_DPM_STATE" "$GPU/power_dpm_state" "power_dpm_state"
fi
write_gpu_control "${PERF_LEVEL:-manual}" "$GPU/power_dpm_force_performance_level" "perf_level"
if [ -n "${POWER_PROFILE:-}" ] && [ -w "$GPU/pp_power_profile_mode" ]; then
  write_gpu_control "$POWER_PROFILE" "$GPU/pp_power_profile_mode" "power_profile"
fi
if [ -n "${MCLK_LEVEL:-}" ]; then
  write_gpu_control "$MCLK_LEVEL" "$GPU/pp_dpm_mclk" "mclk_level"
fi
write_gpu_control "vo ${VDDGFX_OFFSET_MV:--40}" "$GPU/pp_od_clk_voltage" "vddgfx_offset"
write_gpu_control c "$GPU/pp_od_clk_voltage" "overdrive_commit"
