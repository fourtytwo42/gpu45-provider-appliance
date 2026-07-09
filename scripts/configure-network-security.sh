#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
trusted_subnet=${GPU45_TRUSTED_SUBNET:-192.168.50.0/24}

if [[ "${EUID}" -ne 0 ]]; then
  echo "configure-network-security.sh must run as root" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y caddy avahi-daemon ufw

install -d -m 0755 /etc/caddy /var/lib/gpu45
install -m 0644 "$repo_root/deploy/caddy/Caddyfile" /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl enable --now avahi-daemon caddy

ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow from "$trusted_subnet" to any port 22 proto tcp comment 'GPU45 SSH'
ufw allow from "$trusted_subnet" to any port 443 proto tcp comment 'GPU45 console HTTPS'
ufw allow from "$trusted_subnet" to any port 30001 proto tcp comment 'GPU45 Responses API'
ufw --force enable

for _ in $(seq 1 30); do
  root_ca=/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt
  if [[ -f "$root_ca" ]]; then
    install -m 0644 "$root_ca" /var/lib/gpu45/caddy-root.crt
    break
  fi
  sleep 1
done

echo "GPU45 network security configured for $trusted_subnet"
