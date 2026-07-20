#!/usr/bin/env bash
set -euo pipefail

if ! id gpu45 >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/gpu45 --shell /usr/sbin/nologin --user-group gpu45
fi
usermod -a -G hendo420,video,render gpu45

if ! id gpu45-music >/dev/null 2>&1; then
  useradd --system --home-dir /var/lib/gpu45/music --shell /usr/sbin/nologin --user-group gpu45-music
fi
usermod -a -G gpu45,video,render gpu45-music

install -d -o gpu45 -g gpu45 -m 0750 /var/lib/gpu45
chown -R gpu45:gpu45 /var/lib/gpu45
install -d -o gpu45-music -g gpu45-music -m 0750 /var/lib/gpu45/music
install -d -o gpu45-music -g gpu45-music -m 0750 /models/music
chgrp gpu45 /etc/gpu45
chmod 0750 /etc/gpu45
find /etc/gpu45 -maxdepth 1 -type f -name '*.env' -exec chown root:gpu45 {} + -exec chmod 0640 {} +
find /etc/gpu45 -maxdepth 1 -type f -name '*.json' -exec chown root:gpu45 {} + -exec chmod 0660 {} +

install -d -o root -g hendo420 -m 2775 /models/.trash
find /models -xdev -type d -user hendo420 -exec chmod g+rwx {} +

cat >/etc/sudoers.d/gpu45-appliance <<'EOF'
Cmnd_Alias GPU45_SERVICE_CONTROL = /usr/bin/systemctl restart llama-openai.service, /usr/bin/systemctl restart gpu45-v620-fan-controller.service, /usr/bin/systemctl start --no-block gpu45-backup.service, /usr/bin/systemctl start --no-block gpu45-backup-verify.service
gpu45 ALL=(root) NOPASSWD: GPU45_SERVICE_CONTROL
EOF
chmod 0440 /etc/sudoers.d/gpu45-appliance
visudo -cf /etc/sudoers.d/gpu45-appliance
