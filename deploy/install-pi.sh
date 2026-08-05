#!/usr/bin/env bash
# Install or update PiKaraoke-Plus on the Raspberry Pi.
#
# Idempotent: running it again performs an update (reinstall from the local
# clone + service restart). Run as the service user (alexy) from anywhere;
# requires passwordless sudo for apt and systemd operations.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SONGS_DIR=/mnt/media/karaoke
# All karaoke exchange folders live under ONE subtree of the Samba-shared
# Notflex data root (K:\karaoke\... on the PC). Keeping them grouped — and
# tagged .nomedia — stops the Zidoo poster wall from scraping karaoke MP4s
# as movies, while the PC keeps seeing them through the same share.
KARAOKE_ROOT=/mnt/media/data/karaoke
BRIDGE_DIR="$KARAOKE_ROOT/analyse"
# Job exchange with the PC workshop (K:\karaoke\atelier) and the permanent
# library of converted songs (K:\karaoke\bibliotheque).
ATELIER_DIR="$KARAOKE_ROOT/atelier"
BIBLIO_DIR="$KARAOKE_ROOT/bibliotheque"
# Converted songs must appear in the scanned library; the scanner does not
# follow symlinks, so they are bind-mounted into the songs dir.
BIBLIO_MOUNT="$SONGS_DIR/bibliotheque"
DATA_DIR="$HOME/.pikaraoke"
ENV_FILE="$DATA_DIR/pikaraoke.env"
CONFIG_FILE="$DATA_DIR/config.ini"

# Pre-2026-08 layout (flat karaoke-* folders polluting the Notflex root).
OLD_BRIDGE_DIR=/mnt/media/data/karaoke-analyse
OLD_ATELIER_DIR=/mnt/media/data/karaoke-atelier
OLD_BIBLIO_DIR=/mnt/media/data/karaoke-bibliotheque

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

echo "== Migration from the flat karaoke-* layout (no-op once done) =="
sudo mkdir -p "$KARAOKE_ROOT"
# The old bibliotheque is bind-mounted into the songs dir: unmount before
# moving it, and drop its fstab line (the path changed).
if [ -d "$OLD_BIBLIO_DIR" ] && [ ! -d "$BIBLIO_DIR" ]; then
    if mountpoint -q "$BIBLIO_MOUNT"; then
        sudo umount "$BIBLIO_MOUNT"
    fi
    sudo mv "$OLD_BIBLIO_DIR" "$BIBLIO_DIR"
fi
sudo sed -i "\#${OLD_BIBLIO_DIR} #d" /etc/fstab
if [ -d "$OLD_BRIDGE_DIR" ] && [ ! -d "$BRIDGE_DIR" ]; then
    sudo mv "$OLD_BRIDGE_DIR" "$BRIDGE_DIR"
fi
if [ -d "$OLD_ATELIER_DIR" ] && [ ! -d "$ATELIER_DIR" ]; then
    sudo mv "$OLD_ATELIER_DIR" "$ATELIER_DIR"
fi

echo "== Data folders =="
# /mnt/media is root-owned: create as root, hand over to the service user.
sudo mkdir -p "$SONGS_DIR" "$BRIDGE_DIR" "$ATELIER_DIR/entree" "$ATELIER_DIR/etat" "$BIBLIO_DIR"
sudo chown -R "$USER:$USER" "$SONGS_DIR" "$KARAOKE_ROOT"
mkdir -p "$DATA_DIR"
# Belt and braces: media scanners honouring .nomedia (Zidoo, Kodi, Android)
# skip the whole karaoke subtree.
touch "$KARAOKE_ROOT/.nomedia"

sudo mkdir -p "$BIBLIO_MOUNT"
if ! grep -qF "$BIBLIO_DIR $BIBLIO_MOUNT" /etc/fstab; then
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

echo "== TV kiosk (cage + chromium) =="
# The screen service is started on demand from Controle-Pi, never at boot:
# install it but do not enable it.
sudo apt-get install -y -qq cage chromium-browser alsa-utils
sudo cp "$REPO_DIR/deploy/karaoke-ecran.service" /etc/systemd/system/karaoke-ecran.service

echo "== systemd service =="
sudo cp "$REPO_DIR/deploy/pikaraoke.service" /etc/systemd/system/pikaraoke.service
sudo systemctl daemon-reload
sudo systemctl enable pikaraoke
sudo systemctl restart pikaraoke

sleep 3
sudo systemctl --no-pager --lines=5 status pikaraoke
echo "PiKaraoke-Plus is up: http://$(hostname -I | awk '{print $1}'):5555"
