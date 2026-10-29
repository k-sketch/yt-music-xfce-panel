#!/usr/bin/env bash
# Instalador de YT Music para el panel de XFCE.
#
#   ./install.sh          instala y, al terminar, borra los archivos de
#                         instalación (ya no hacen falta)
#   ./install.sh --keep   instala pero deja los archivos donde están
#
# Para desinstalar más adelante:  ~/.local/share/ytm-panel/uninstall.sh
set -euo pipefail
cd "$(dirname "$0")"
SRC_DIR="$(pwd)"                        # esta carpeta (la que se borra al final)

KEEP=0
if [[ "${1:-}" == "--keep" ]]; then KEEP=1; fi

APP_DIR="$HOME/.local/share/ytm-panel"  # donde queda instalado el popup
DESKTOP_DIR="/usr/share/xfce4/panel/plugins"

# --- Teclas multimedia ------------------------------------------------------
# Cada tecla se conecta a una orden que le "habla" a YT Music por D-Bus.
# Si YT Music no está abierto, la orden no hace nada (no molesta a otros
# reproductores).
KEYS_CHANNEL="xfce4-keyboard-shortcuts"
MPRIS_CALL="dbus-send --session --type=method_call --dest=org.mpris.MediaPlayer2.ytmpanel /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player"

bind_key() {            # uso: bind_key TECLA MÉTODO [ARGUMENTO]
  local key="$1" method="$2" arg="${3:-}"
  local prop="/commands/custom/$key"
  local cmd="$MPRIS_CALL.$method${arg:+ $arg}"
  local current

  if current="$(xfconf-query -c "$KEYS_CHANNEL" -p "$prop" 2>/dev/null)"; then
    if [[ "$current" != *org.mpris.MediaPlayer2.ytmpanel* ]]; then
      # La tecla ya hacía otra cosa (la configuraste tú): no la pisamos.
      echo "  - $key ya tenía otra acción asignada; la dejo como estaba"
      return
    fi
    xfconf-query -c "$KEYS_CHANNEL" -p "$prop" -s "$cmd" || return 0
  else
    xfconf-query -c "$KEYS_CHANNEL" -p "$prop" -n -t string -s "$cmd" || {
      echo "  - no pude asignar $key"
      return 0
    }
  fi
  echo "  - $key  ->  $method"
}

stop_running() {        # cierra el popup y mpv si estaban abiertos
  pkill -f ytm_panel.py 2>/dev/null || true
  pkill -f ytm-panel-mpv.sock 2>/dev/null || true
}

# ============================================================================
# 1. ¿Tenemos lo necesario para compilar?
# ============================================================================
PKG=libxfce4panel-2.0                   # (XFCE 4.14 o más nuevo)
pkg-config --exists "$PKG" 2>/dev/null || PKG=libxfce4panel-1.0   # (XFCE 4.12)
if ! pkg-config --exists "$PKG"; then
  echo "No encuentro libxfce4panel. Esto es lo que dice pkg-config:"
  pkg-config --print-errors "$PKG" || true
  echo
  echo "Instala lo necesario para compilar y vuelve a intentarlo:"
  echo "  sudo apt install build-essential pkg-config libgtk-3-dev \\"
  echo "                   libxfce4panel-2.0-dev libxfce4ui-2-dev"
  exit 1
fi

# ============================================================================
# 2. Compilar el plugin (en una carpeta temporal que se borra sola)
# ============================================================================
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT

gcc -shared -fPIC -O2 -Wall -o "$BUILD/libytmplugin.so" plugin/ytm-plugin.c \
    $(pkg-config --cflags --libs "$PKG")

cp plugin/ytmplugin.desktop "$BUILD/"
if [[ "$PKG" == "libxfce4panel-1.0" ]]; then    # XFCE 4.12 no usa esa línea
  sed -i '/X-XFCE-API/d' "$BUILD/ytmplugin.desktop"
fi

# ============================================================================
# 3. Copiar todo a su lugar definitivo
# ============================================================================
stop_running
LIBDIR="$(pkg-config --variable=libdir "$PKG")"
sudo install -Dm755 "$BUILD/libytmplugin.so" "$LIBDIR/xfce4/panel/plugins/libytmplugin.so"
sudo install -Dm644 "$BUILD/ytmplugin.desktop" "$DESKTOP_DIR/ytmplugin.desktop"
install -Dm755 ytm_panel.py "$APP_DIR/ytm_panel.py"
install -Dm755 uninstall.sh "$APP_DIR/uninstall.sh"   # para poder desinstalar luego

# ============================================================================
# 4. Conectar las teclas multimedia del teclado
# ============================================================================
echo
echo "Teclas multimedia:"
if command -v xfconf-query >/dev/null && command -v dbus-send >/dev/null; then
  bind_key XF86AudioPlay    PlayPause
  bind_key XF86AudioPause   Pause
  bind_key XF86AudioStop    Stop
  bind_key XF86AudioNext    Next
  bind_key XF86AudioPrev    Previous
  bind_key XF86AudioForward Seek int64:10000000      # +10 segundos
  bind_key XF86AudioRewind  Seek int64:-10000000     # -10 segundos
else
  echo "  - no encontré xfconf-query o dbus-send; sin teclas multimedia"
fi

# ============================================================================
# 5. Avisos si falta algo para que funcione
# ============================================================================
echo
for cmd in mpv yt-dlp; do
  command -v "$cmd" >/dev/null || echo "AVISO: falta '$cmd'  ->  sudo apt install mpv yt-dlp"
done
python3 -c "import gi" 2>/dev/null ||
  echo "AVISO: falta python3-gi  ->  sudo apt install python3-gi gir1.2-gtk-3.0"
python3 -c "import ytmusicapi" 2>/dev/null ||
  echo "AVISO: falta ytmusicapi  ->  pip install --user --break-system-packages ytmusicapi"

# ============================================================================
# 6. Recargar el panel
# ============================================================================
xfce4-panel -r
echo
echo "Listo. Ahora: clic derecho en el panel -> Panel -> Añadir nuevos elementos -> YT Music"

# ============================================================================
# 7. Borrar los archivos de instalación (ya están instalados, no hacen falta)
# ============================================================================
if [[ $KEEP -eq 1 ]]; then
  echo "Dejé los archivos en: $SRC_DIR"
  exit 0
fi

# Medida de seguridad: solo borramos si de verdad es la carpeta del proyecto
if [[ ! -f "$SRC_DIR/plugin/ytm-plugin.c" || ! -f "$SRC_DIR/ytm_panel.py" \
      || "$SRC_DIR" == "$HOME" || "$SRC_DIR" == "/" ]]; then
  exit 0
fi

# Si es una copia de git (alguien que está desarrollando), mejor preguntar
if [[ -d "$SRC_DIR/.git" ]]; then
  read -r -p "Esta carpeta es un repositorio git. ¿Borrar los archivos de instalación igual? [s/N] " ans || ans=""
  [[ "$ans" =~ ^[sSyY]$ ]] || { echo "Dejé los archivos en: $SRC_DIR"; exit 0; }
fi

# Borramos solo los archivos del proyecto (no cualquier otra cosa que haya en
# la carpeta) y, si la carpeta queda vacía, también la carpeta.
cd "$HOME"
rm -rf "$SRC_DIR/plugin" "$SRC_DIR/.git"
rm -f "$SRC_DIR"/{README.md,LICENSE,.gitignore,install.sh,uninstall.sh,ytm_panel.py}
rmdir "$SRC_DIR" 2>/dev/null || true
echo "Archivos de instalación eliminados. Para desinstalar: $APP_DIR/uninstall.sh"
