#!/usr/bin/env bash
# Desinstala YT Music: quita el plugin y el popup.
# install.sh deja una copia de este archivo en ~/.local/share/ytm-panel/
set -euo pipefail

APP_DIR="$HOME/.local/share/ytm-panel"
DESKTOP_DIR="/usr/share/xfce4/panel/plugins"

# 1. Cerrar el popup y la música si estaban abiertos
pkill -f ytm_panel.py 2>/dev/null || true
pkill -f ytm-panel-mpv.sock 2>/dev/null || true

# 2. Quitar el plugin del sistema
sudo find /usr/lib /usr/lib64 -name libytmplugin.so -delete 2>/dev/null || true
sudo rm -f "$DESKTOP_DIR/ytmplugin.desktop"

# 3. Borrar el popup instalado y recargar el panel
rm -rf "$APP_DIR"
xfce4-panel -r
echo "YT Music desinstalado."
