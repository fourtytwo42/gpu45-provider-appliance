#!/bin/sh
set -eu

TARGET_KERNEL=${GPU45_TARGET_KERNEL:-6.8.0-124-generic}
FALLBACK_KERNEL=${GPU45_FALLBACK_KERNEL:-5.15.0-185-generic}
OLD_NAME=amdgpu
OLD_VERSION=6.12.12-2164967.22.04
NEW_NAME=amdgpu-gpu45
NEW_VERSION=6.16.13-2341068.22.04
EXPECTED_PACKAGE_SHA256=9d1f0686a3edf890f0a2f668cf719da14534da40d9da440512a1bf3b0730d419
PACKAGE=${GPU45_AMDGPU_EXPERIMENT_PACKAGE:-/home/hendo420/amdgpu-7.2.4-evaluation/amdgpu-dkms.deb}
SOURCE_DIR="/usr/src/$NEW_NAME-$NEW_VERSION"
STATE_DIR=${GPU45_SOFT_UCLK_EVALUATION_DIR:-/var/lib/gpu45/soft-uclk-evaluation}/amdgpu-30.30.4
BACKUP_DIR="$STATE_DIR/target-backup"

fallback_hashes() {
  sha256sum \
    "/boot/initrd.img-$FALLBACK_KERNEL" \
    "$(modinfo -k "$FALLBACK_KERNEL" -n amdgpu)"
}

prepare_source() {
  [ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
  [ -f "$PACKAGE" ] || { echo "driver package not found: $PACKAGE" >&2; exit 1; }
  package_sha=$(sha256sum "$PACKAGE" | awk '{print $1}')
  [ "$package_sha" = "$EXPECTED_PACKAGE_SHA256" ] || { echo "driver package checksum mismatch: $package_sha" >&2; exit 1; }
  [ -d "/lib/modules/$TARGET_KERNEL/build" ] || { echo "target kernel headers are missing" >&2; exit 1; }

  temporary=$(mktemp -d)
  trap 'rm -rf "$temporary"' EXIT INT TERM
  dpkg-deb -x "$PACKAGE" "$temporary"
  extracted=$(find "$temporary/usr/src" -mindepth 1 -maxdepth 1 -type d -name 'amdgpu-*' | head -1)
  [ -n "$extracted" ] || { echo "driver source missing from package" >&2; exit 1; }
  rm -rf "$SOURCE_DIR"
  cp -a "$extracted" "$SOURCE_DIR"
  sed -i \
    -e "s/^PACKAGE_NAME=.*/PACKAGE_NAME=\"$NEW_NAME\"/" \
    -e 's/^AUTOINSTALL=.*/AUTOINSTALL="no"/' \
    "$SOURCE_DIR/dkms.conf"

  dkms status -m "$NEW_NAME" -v "$NEW_VERSION" >/dev/null 2>&1 || dkms add -m "$NEW_NAME" -v "$NEW_VERSION"
  dkms build -m "$NEW_NAME" -v "$NEW_VERSION" -k "$TARGET_KERNEL"
  mkdir -p "$STATE_DIR"
  fallback_hashes > "$STATE_DIR/fallback-before.sha256"
  sha256sum "$PACKAGE" > "$STATE_DIR/package.sha256"
  echo "experimental AMDGPU built for $TARGET_KERNEL"
}

restore_target() {
  set +e
  dkms uninstall -m "$NEW_NAME" -v "$NEW_VERSION" -k "$TARGET_KERNEL"
  dkms install -m "$OLD_NAME" -v "$OLD_VERSION" -k "$TARGET_KERNEL"
  if [ -d "$BACKUP_DIR/updates-dkms" ]; then
    rm -rf "/lib/modules/$TARGET_KERNEL/updates/dkms"
    cp -a "$BACKUP_DIR/updates-dkms" "/lib/modules/$TARGET_KERNEL/updates/dkms"
  fi
  [ -f "$BACKUP_DIR/initrd.img" ] && cp -a "$BACKUP_DIR/initrd.img" "/boot/initrd.img-$TARGET_KERNEL"
  depmod "$TARGET_KERNEL"
  set -e
  fallback_hashes > "$STATE_DIR/fallback-after-restore.sha256"
  diff -u "$STATE_DIR/fallback-before.sha256" "$STATE_DIR/fallback-after-restore.sha256"
  printf '%s\n' restored > "$STATE_DIR/state"
  echo "restored original AMDGPU modules and initramfs for $TARGET_KERNEL"
}

install_target() {
  [ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
  dkms status -m "$NEW_NAME" -v "$NEW_VERSION" -k "$TARGET_KERNEL" | grep -q built || {
    echo "experimental driver has not been built" >&2
    exit 1
  }
  rm -rf "$BACKUP_DIR"
  mkdir -p "$BACKUP_DIR"
  cp -a "/lib/modules/$TARGET_KERNEL/updates/dkms" "$BACKUP_DIR/updates-dkms"
  cp -a "/boot/initrd.img-$TARGET_KERNEL" "$BACKUP_DIR/initrd.img"
  fallback_hashes > "$STATE_DIR/fallback-before-install.sha256"

  trap 'restore_target' EXIT INT TERM
  dkms uninstall -m "$OLD_NAME" -v "$OLD_VERSION" -k "$TARGET_KERNEL"
  dkms install -m "$NEW_NAME" -v "$NEW_VERSION" -k "$TARGET_KERNEL"
  update-initramfs -u -k "$TARGET_KERNEL"
  depmod "$TARGET_KERNEL"
  modinfo -k "$TARGET_KERNEL" amdgpu | grep -q "^version:[[:space:]]*6.16.13"
  fallback_hashes > "$STATE_DIR/fallback-after-install.sha256"
  diff -u "$STATE_DIR/fallback-before-install.sha256" "$STATE_DIR/fallback-after-install.sha256"
  printf '%s\n' installed > "$STATE_DIR/state"
  trap - EXIT INT TERM
  echo "experimental AMDGPU installed only for $TARGET_KERNEL"
}

case "${1:-status}" in
  prepare) prepare_source ;;
  install) install_target ;;
  restore) [ "$(id -u)" -eq 0 ] || exit 1; restore_target ;;
  status)
    echo "fallback kernel: $FALLBACK_KERNEL"
    modinfo -k "$FALLBACK_KERNEL" amdgpu | sed -n '1,3p'
    echo "target kernel: $TARGET_KERNEL"
    modinfo -k "$TARGET_KERNEL" amdgpu | sed -n '1,3p'
    dkms status | grep -E 'amdgpu|nct6687d' || true
    [ -f "$STATE_DIR/state" ] && cat "$STATE_DIR/state" || true
    ;;
  *) echo "usage: $0 {prepare|install|restore|status}" >&2; exit 2 ;;
esac
