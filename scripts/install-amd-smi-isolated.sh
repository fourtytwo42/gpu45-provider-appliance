#!/bin/sh
set -eu

VERSION=26.0.0.70000-38~22.04
EXPECTED_SHA256=abe78905d58797fcd0d866231f1feba6b977d93d89b411e3bb80a953a3d0aab5
PACKAGE=${1:-/var/cache/apt/archives/amd-smi-lib_${VERSION}_amd64.deb}
PREFIX=${GPU45_AMD_SMI_PREFIX:-/opt/amd-smi-gpu45-7.0.0}
WRAPPER=${GPU45_AMD_SMI_WRAPPER:-/usr/local/bin/amd-smi-gpu45}

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ -f "$PACKAGE" ] || { echo "AMD SMI package not found: $PACKAGE" >&2; exit 1; }
actual_sha=$(sha256sum "$PACKAGE" | awk '{print $1}')
[ "$actual_sha" = "$EXPECTED_SHA256" ] || { echo "AMD SMI package checksum mismatch: $actual_sha" >&2; exit 1; }

temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT INT TERM
dpkg-deb -x "$PACKAGE" "$temporary"
source_root="$temporary/opt/rocm-7.0.0"
[ -x "$source_root/libexec/amdsmi_cli/amdsmi_cli.py" ] || { echo "AMD SMI CLI missing from package" >&2; exit 1; }

rm -rf "$PREFIX.new"
mkdir -p "$PREFIX.new"
cp -a "$source_root/." "$PREFIX.new/"
rm -rf "$PREFIX"
mv "$PREFIX.new" "$PREFIX"

cat > "$WRAPPER" <<EOF
#!/bin/sh
export LD_LIBRARY_PATH="$PREFIX/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
export PYTHONPATH="$PREFIX/share/amd_smi\${PYTHONPATH:+:\$PYTHONPATH}"
exec /usr/bin/python3 "$PREFIX/libexec/amdsmi_cli/amdsmi_cli.py" "\$@"
EOF
chmod 0755 "$WRAPPER"
"$WRAPPER" version
