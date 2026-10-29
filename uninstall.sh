#!/usr/bin/env bash
# Desinstala YT Music: quita el plugin, el popup y las teclas multimedia.
# install.sh deja una copia de este archivo en ~/.local/share/ytm-panel/
set -euo pipefail

APP_DIR="$HOME/.local/share/ytm-panel"
DESKTOP_DIR="/usr/share/xfce4/panel/plugins"
KEYS_CHANNEL="xfce4-keyboard-shortcuts"

# 1. Cerrar el popup y la música si estaban abiertos
pkill -f ytm_panel.py 2>/dev/null || true
pkill -f ytm-panel-mpv.sock 2>/dev/null || true

# 2. Quitar el plugin del sistema
sudo find /usr/lib /usr/lib64 -name libytmplugin.so -delete 2>/dev/null || true
sudo rm -f "$DESKTOP_DIR/ytmplugin.desktop"

# 3. Quitar las teclas multimedia, pero solo las que puso este instalador
#    (si alguna la cambiaste tú, se respeta)
if command -v xfconf-query >/dev/null; then
  for key in XF86AudioPlay XF86AudioPause XF86AudioStop XF86AudioNext \
             XF86AudioPrev XF86AudioForward XF86AudioRewind; do
    prop="/commands/custom/$key"
    current="$(xfconf-query -c "$KEYS_CHANNEL" -p "$prop" 2>/dev/null || true)"
    if [[ "$current" == *org.mpris.MediaPlayer2.ytmpanel* ]]; then
      xfconf-query -c "$KEYS_CHANNEL" -p "$prop" -r || true
    fi
  done
fi

# 4. Borrar el popup instalado y recargar el panel
rm -rf "$APP_DIR"
xfce4-panel -r
echo "YT Music desinstalado."
