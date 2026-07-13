#!/bin/sh
set -eu

ROOT=${GPU45_SOFT_UCLK_EVALUATION_DIR:-/var/lib/gpu45/soft-uclk-evaluation}
STAMP=${1:-$(date -u +%Y%m%dT%H%M%SZ)}
DEST="$ROOT/baseline-$STAMP"
REPO=${GPU45_APPLIANCE_REPO:-/opt/gpu45-provider-appliance}

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
umask 077
mkdir -p "$DEST/boot" "$DEST/modules" "$DEST/config" "$DEST/systemd"

for version in 5.15.0-185-generic 6.8.0-124-generic; do
  for prefix in vmlinuz initrd.img config System.map; do
    source="/boot/$prefix-$version"
    [ -f "$source" ] && cp -a "$source" "$DEST/boot/"
  done
  module=$(modinfo -k "$version" -n amdgpu 2>/dev/null || true)
  if [ -n "$module" ] && [ -f "$module" ]; then
    mkdir -p "$DEST/modules/$version"
    cp -a "$module" "$DEST/modules/$version/"
  fi
done

cp -a /etc/gpu45 "$DEST/config/gpu45"
cp -a /etc/default/grub "$DEST/config/grub"
cp -a /etc/apt/sources.list "$DEST/config/sources.list" 2>/dev/null || true
cp -a /etc/apt/sources.list.d "$DEST/config/sources.list.d"
cp -a /etc/apt/preferences.d "$DEST/config/preferences.d"
for unit in gpu45-host-tune.service gpu45-provider-appliance.service gpu45-resource-manager.service gpu45-responses-proxy.service llama-openai.service; do
  systemctl cat "$unit" > "$DEST/systemd/$unit" 2>/dev/null || true
done

dpkg-query -W > "$DEST/packages.tsv"
dkms status > "$DEST/dkms-status.txt"
uname -a > "$DEST/uname.txt"
cat /proc/cmdline > "$DEST/cmdline.txt"
grub-editenv list > "$DEST/grubenv.txt"
cat /sys/class/drm/card1/device/pp_dpm_mclk > "$DEST/pp_dpm_mclk.txt"
cat /sys/class/drm/card1/device/pp_od_clk_voltage > "$DEST/pp_od_clk_voltage.txt"
cat /sys/class/drm/card1/device/power_dpm_force_performance_level > "$DEST/performance-level.txt"
journalctl -b -k --no-pager | grep -E 'amdgpu|SMU|RAS|ECC' > "$DEST/amdgpu-boot.log" || true

cd "$REPO"
git status --short --branch > "$DEST/git-status.txt"
git log -10 --oneline > "$DEST/git-log.txt"
git bundle create "$DEST/appliance.bundle" --all
find "$DEST" -type f -print0 | sort -z | xargs -0 sha256sum > "$DEST/SHA256SUMS"
printf '%s\n' "$DEST"
