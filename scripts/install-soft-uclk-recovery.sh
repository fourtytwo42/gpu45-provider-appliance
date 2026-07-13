#!/bin/sh
set -eu

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

install -m 0755 "$SOURCE_DIR/gpu45-soft-uclk.py" /usr/local/sbin/gpu45-soft-uclk
install -d -m 0755 /usr/local/libexec
install -m 0755 "$SOURCE_DIR/gpu45-amd-smi-direct.py" /usr/local/libexec/gpu45-amd-smi-direct.py
cat > /usr/local/sbin/gpu45-amd-smi-direct <<'EOF'
#!/bin/sh
PREFIX=/opt/amd-smi-gpu45-7.0.0
export LD_LIBRARY_PATH="$PREFIX/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PYTHONPATH="$PREFIX/share/amd_smi${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 /usr/local/libexec/gpu45-amd-smi-direct.py "$@"
EOF
chmod 0755 /usr/local/sbin/gpu45-amd-smi-direct
install -m 0755 "$SOURCE_DIR/gpu45-soft-uclk-inventory.sh" /usr/local/sbin/gpu45-soft-uclk-inventory
install -m 0755 "$SOURCE_DIR/gpu45-soft-uclk-apply.sh" /usr/local/sbin/gpu45-soft-uclk-apply
install -m 0755 "$SOURCE_DIR/gpu45-kernel-attempt.sh" /usr/local/sbin/gpu45-kernel-attempt
install -m 0755 "$SOURCE_DIR/gpu45-kernel-attempt-boot.sh" /usr/local/sbin/gpu45-kernel-attempt-boot.sh
install -m 0755 "$SOURCE_DIR/gpu45-soft-uclk-boot-recovery.sh" /usr/local/sbin/gpu45-soft-uclk-boot-recovery.sh
install -m 0644 "$SOURCE_DIR/gpu45-soft-uclk-boot-recovery.service" /etc/systemd/system/gpu45-soft-uclk-boot-recovery.service
install -m 0644 "$SOURCE_DIR/gpu45-kernel-attempt-boot.service" /etc/systemd/system/gpu45-kernel-attempt-boot.service
systemctl daemon-reload
systemctl enable gpu45-soft-uclk-boot-recovery.service
systemctl enable gpu45-kernel-attempt-boot.service
