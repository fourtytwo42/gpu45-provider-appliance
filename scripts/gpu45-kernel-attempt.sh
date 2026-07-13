#!/bin/sh
set -eu

STATE_DIR=${GPU45_SOFT_UCLK_STATE_DIR:-/var/lib/gpu45/soft-uclk}
MARKER="$STATE_DIR/kernel-attempt.json"
OBSERVATION="$STATE_DIR/kernel-observation.json"
TARGET_KERNEL=${GPU45_TARGET_KERNEL:-6.8.0-124-generic}
FALLBACK_KERNEL=${GPU45_FALLBACK_KERNEL:-5.15.0-185-generic}
TARGET_ENTRY="Advanced options for Ubuntu>Ubuntu, with Linux $TARGET_KERNEL"
RESOURCE_DB=${GPU45_RESOURCE_DB:-/var/lib/gpu45/resource-manager.db}

prepare() {
  stage=${1:-kernel-6.8-current-driver}
  [ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
  [ "$(uname -r)" = "$FALLBACK_KERNEL" ] || { echo "prepare must run from fallback kernel $FALLBACK_KERNEL" >&2; exit 1; }
  [ ! -f "$MARKER" ] || { echo "a kernel attempt is already pending" >&2; exit 1; }
  [ -f "/boot/vmlinuz-$TARGET_KERNEL" ] && [ -f "/boot/initrd.img-$TARGET_KERNEL" ] || { echo "target kernel boot files are missing" >&2; exit 1; }
  modinfo -k "$TARGET_KERNEL" amdgpu >/dev/null
  grep -Fq "GRUB_DEFAULT=\"Advanced options for Ubuntu>Ubuntu, with Linux $FALLBACK_KERNEL\"" /etc/default/grub || {
    echo "GRUB fallback is not pinned to $FALLBACK_KERNEL" >&2
    exit 1
  }
  if [ -f "$RESOURCE_DB" ]; then
    active=$(sqlite3 "$RESOURCE_DB" "select count(*) from leases where status in ('active','queued');")
    [ "$active" = "0" ] || { echo "refusing with $active active or queued GPU leases" >&2; exit 1; }
  fi
  mkdir -p "$STATE_DIR"
  rm -f "$OBSERVATION"
  /usr/local/sbin/gpu45-soft-uclk kernel-marker --output "$MARKER" --target "$TARGET_KERNEL" --fallback "$FALLBACK_KERNEL" --stage "$stage" >/dev/null
  grub-reboot "$TARGET_ENTRY"
  grub-editenv list | grep -Fq "next_entry=$TARGET_ENTRY" || { rm -f "$MARKER"; echo "GRUB one-time entry was not recorded" >&2; exit 1; }
  echo "scheduled one-time boot: $TARGET_ENTRY"
}

confirm() {
  [ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
  [ "$(uname -r)" = "$TARGET_KERNEL" ] || { echo "target kernel is not running" >&2; exit 1; }
  [ -f "$MARKER" ] && [ -f "$OBSERVATION" ] || { echo "kernel attempt state is incomplete" >&2; exit 1; }
  grep -q '"state": "booted-target"' "$OBSERVATION" || { echo "target boot was not observed" >&2; exit 1; }
  cp "$OBSERVATION" "$STATE_DIR/last-kernel-success.json"
  rm -f "$MARKER"
  echo "confirmed one-time kernel boot; GRUB fallback remains $FALLBACK_KERNEL"
}

case "${1:-status}" in
  prepare) shift; prepare "$@" ;;
  confirm) confirm ;;
  status)
    [ -f "$MARKER" ] && cat "$MARKER" || echo '{"state":"not-scheduled"}'
    [ -f "$OBSERVATION" ] && cat "$OBSERVATION" || true
    grub-editenv list
    ;;
  *) echo "usage: $0 {prepare [STAGE]|confirm|status}" >&2; exit 2 ;;
esac
