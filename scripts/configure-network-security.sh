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
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https curl gnupg avahi-daemon ufw
if ! apt-cache show caddy >/dev/null 2>&1; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt -o /etc/apt/sources.list.d/caddy-stable.list
  chmod 0644 /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
  apt-get update
fi
apt-get install -y caddy

install -d -m 0755 /etc/caddy /var/lib/gpu45
install -m 0644 "$repo_root/deploy/caddy/Caddyfile" /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl enable --now avahi-daemon caddy

install -m 0644 "$repo_root/deploy/systemd/gpu45-image-api.service" /etc/systemd/system/gpu45-image-api.service
install -m 0644 "$repo_root/deploy/systemd/gpu45-whisper-api.service" /etc/systemd/system/gpu45-whisper-api.service
install -m 0644 "$repo_root/deploy/systemd/qwen3-tts-api.service" /etc/systemd/system/qwen3-tts-api.service
install -m 0644 "$repo_root/deploy/systemd/wan2-video-api.service" /etc/systemd/system/wan2-video-api.service
install -m 0755 "$repo_root/scripts/gpu45-llm-server" /usr/local/bin/gpu45-llm-server
systemctl daemon-reload

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
