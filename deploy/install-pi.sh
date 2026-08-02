#!/usr/bin/env bash
# Install or update PiKaraoke-Plus on the Raspberry Pi.
#
# Idempotent: running it again performs an update (reinstall from the local
# clone + service restart). Run as the service user (alexy) from anywhere;
# requires passwordless sudo for apt and systemd operations.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SONGS_DIR=/mnt/media/karaoke
# Inside the Samba-shared Notflex data root so the PC sees it as K:\karaoke-analyse.
BRIDGE_DIR=/mnt/media/data/karaoke-analyse
# Job exchange with the PC workshop (K:\karaoke-atelier) and the permanent
# library of converted songs (K:\karaoke-bibliotheque).
ATELIER_DIR=/mnt/media/data/karaoke-atelier
BIBLIO_DIR=/mnt/media/data/karaoke-bibliotheque
DATA_DIR="$HOME/.pikaraoke"
ENV_FILE="$DATA_DIR/pikaraoke.env"
CONFIG_FILE="$DATA_DIR/config.ini"

echo "== System dependencies =="
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg

echo "== uv =="
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

echo "== Install pikaraoke from $REPO_DIR =="
uv tool install --force --reinstall "$REPO_DIR"

echo "== Data folders =="
# /mnt/media is root-owned: create as root, hand over to the service user.
sudo mkdir -p "$SONGS_DIR" "$BRIDGE_DIR" "$ATELIER_DIR/entree" "$ATELIER_DIR/etat" "$BIBLIO_DIR"
sudo chown -R "$USER:$USER" "$SONGS_DIR" "$BRIDGE_DIR" "$ATELIER_DIR" "$BIBLIO_DIR"
mkdir -p "$DATA_DIR"

# Converted songs live in the Samba share but must appear in the scanned
# library; the scanner does not follow symlinks, so bind-mount them in.
BIBLIO_MOUNT="$SONGS_DIR/bibliotheque"
sudo mkdir -p "$BIBLIO_MOUNT"
if ! grep -q "karaoke-bibliotheque" /etc/fstab; then
    echo "$BIBLIO_DIR $BIBLIO_MOUNT none bind,nofail,x-systemd.requires=/mnt/media 0 0" | sudo tee -a /etc/fstab > /dev/null
fi
mountpoint -q "$BIBLIO_MOUNT" || sudo mount "$BIBLIO_MOUNT"

# Admin password lives on the Pi only, never in the repo.
if [ ! -f "$ENV_FILE" ]; then
    echo "ADMIN_PASSWORD=Karaoke-2026" > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
fi

# Seed initial preferences on first install only (the web UI owns them after).
if [ ! -f "$CONFIG_FILE" ]; then
    printf '[USERPREFERENCES]\nenable_fair_queue = True\n' > "$CONFIG_FILE"
fi

echo "== systemd service =="
sudo cp "$REPO_DIR/deploy/pikaraoke.service" /etc/systemd/system/pikaraoke.service
sudo systemctl daemon-reload
sudo systemctl enable pikaraoke
sudo systemctl restart pikaraoke

sleep 3
sudo systemctl --no-pager --lines=5 status pikaraoke
echo "PiKaraoke-Plus is up: http://$(hostname -I | awk '{print $1}'):5555"
