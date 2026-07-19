#!/usr/bin/env bash
set -euo pipefail

version="${GPU45_CODEX_CLI_VERSION:-0.144.6}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "install-codex-reference.sh must run as root" >&2
  exit 1
fi
if ! id gpu45-benchmark >/dev/null 2>&1; then
  echo "gpu45-benchmark service account is missing" >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to install Codex CLI" >&2
  exit 1
fi

current="$(codex --version 2>/dev/null | awk '{print $2}' || true)"
if [[ "$current" != "$version" ]]; then
  npm install --global "@openai/codex@$version"
fi

install -d -m 0750 -o gpu45-benchmark -g gpu45-benchmark \
  /var/lib/gpu45-benchmark \
  /var/lib/gpu45-benchmark/.codex \
  /var/lib/gpu45-benchmark/codex-reference

echo "Codex CLI $(codex --version) is installed for the GPU45 reference runner."
echo "Authenticate once with:"
echo "sudo -u gpu45-benchmark env CODEX_HOME=/var/lib/gpu45-benchmark/.codex codex login --device-auth"
