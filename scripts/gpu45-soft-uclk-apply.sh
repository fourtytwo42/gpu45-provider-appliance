#!/bin/sh
set -eu

GPU=${GPU45_GPU_DEVICE_PATH:-/sys/class/drm/card1/device}
STATE_DIR=${GPU45_SOFT_UCLK_STATE_DIR:-/var/lib/gpu45/soft-uclk}
MARKER="$STATE_DIR/experiment-armed.json"
SERVICES="gpu45-responses-proxy.service llama-openai.service qwen3-tts-api.service gpu45-image-api.service wan2-video-api.service gpu45-whisper-api.service"
RESOURCE_DB=${GPU45_RESOURCE_DB:-/var/lib/gpu45/resource-manager.db}
AMD_SMI=${GPU45_AMD_SMI:-/usr/local/bin/amd-smi-gpu45}

restore_services() {
  [ -f "$STATE_DIR/services-before.txt" ] || return 0
  while IFS= read -r service; do
    [ -n "$service" ] && systemctl start "$service" 2>/dev/null || true
  done < "$STATE_DIR/services-before.txt"
}

restore_stock_state() {
  timeout 20 "$AMD_SMI" set -l AUTO -g 0 >/dev/null 2>&1 || true
  /usr/local/sbin/gpu45-powerplay-guard cancel >/dev/null 2>&1 || true
  rm -f "$MARKER"
  restore_services
}

apply_clock() {
  clock=$1
  stage=${2:-current-stack}
  guard_seconds=${3:-900}
  /usr/local/sbin/gpu45-soft-uclk marker \
    --output "$MARKER" \
    --clock "$clock" \
    --stage "$stage" \
    --driver "$(modinfo amdgpu | sed -n 's/^version:[[:space:]]*//p' | head -1)" \
    --kernel "$(uname -r)" >/dev/null

  /usr/local/sbin/gpu45-powerplay-guard arm "$guard_seconds" "soft-uclk-${clock}-${stage}"
  if ! timeout 20 "$AMD_SMI" set -l MANUAL -g 0 > "$STATE_DIR/set-manual.log" 2>&1; then
    restore_stock_state
    echo "AMD SMI could not enable manual performance mode" >&2
    exit 3
  fi
  if ! timeout 20 "$AMD_SMI" set -L mclk max "$clock" -g 0 > "$STATE_DIR/set-limit.log" 2>&1; then
    cat "$STATE_DIR/set-limit.log" >&2
    restore_stock_state
    echo "AMD SMI rejected the ${clock} MHz memory soft limit" >&2
    exit 4
  fi
  echo "AMD SMI accepted ${clock} MHz; failsafe remains armed pending measured-load verification"
}

start_experiment() {
  clock=${1:-}
  stage=${2:-current-stack}
  guard_seconds=${3:-900}
  case "$clock" in 1025|1050) ;; *) echo "clock must be 1025 or 1050 MHz" >&2; exit 2 ;; esac
  [ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
  [ -x "$AMD_SMI" ] || { echo "AMD SMI wrapper is unavailable" >&2; exit 1; }
  [ ! -f "$MARKER" ] || { echo "another soft-UCLK experiment is armed" >&2; exit 1; }

  if [ -f "$RESOURCE_DB" ]; then
    active=$(sqlite3 "$RESOURCE_DB" "select count(*) from leases where status in ('active','queued');")
    [ "$active" = "0" ] || { echo "refusing with $active active or queued GPU leases" >&2; exit 1; }
  fi

  mkdir -p "$STATE_DIR"
  : > "$STATE_DIR/services-before.txt"
  for service in $SERVICES; do
    if systemctl is-active --quiet "$service"; then
      echo "$service" >> "$STATE_DIR/services-before.txt"
      systemctl stop "$service"
    fi
  done
  used=99999999999
  for _ in $(seq 1 90); do
    used=$(cat "$GPU/mem_info_vram_used" 2>/dev/null || echo 99999999999)
    [ "$used" -lt 2000000000 ] && break
    sleep 1
  done
  if [ "$used" -ge 2000000000 ]; then
    restore_services
    echo "VRAM did not return below 2 GB: $used" >&2
    exit 1
  fi
  apply_clock "$clock" "$stage" "$guard_seconds"
}

case "${1:-status}" in
  apply) shift; start_experiment "$@" ;;
  reset) [ "$(id -u)" -eq 0 ] || exit 1; restore_stock_state; echo "soft-UCLK experiment reset" ;;
  status)
    [ -f "$MARKER" ] && cat "$MARKER" || echo '{"state":"disarmed"}'
    cat "$GPU/pp_dpm_mclk"
    "$AMD_SMI" metric --clock --json || true
    ;;
  *) echo "usage: $0 {apply CLOCK [STAGE] [GUARD_SECONDS]|reset|status}" >&2; exit 2 ;;
esac
