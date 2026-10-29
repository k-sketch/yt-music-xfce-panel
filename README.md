# YT Music para el panel de XFCE

Plugin para `xfce4-panel` que permite **buscar y reproducir música de YouTube Music** desde un popup del panel: se abre al hacer clic en el icono, se coloca pegado al panel y se cierra al perder el foco. La música sigue sonando en segundo plano

No necesita cuenta ni inicio de sesión.

## Características

- Búsqueda de canciones en YouTube Music, sin cuenta
- Lista de resultados con la duración
- Controles: anterior, play/pausa, siguiente y repetir canción
- Barra de tiempo para saltar a cualquier punto de la canción
- Portada de la canción que suena
- Teclas multimedia del teclado (play/pausa, siguiente, anterior, stop, adelantar y retroceder)
- Popup compacto: solo la barra de búsqueda si no suena nada; al reproducir, portada a la izquierda y controles a la derecha
- Clic central sobre el icono del panel: play/pausa sin abrir el popup
- Funciona con el panel arriba, abajo o en un lateral
- Se anuncia como reproductor estándar (MPRIS), así que también responde a `playerctl` y a otras herramientas

## Requisitos

- XFCE 4.12 o superior, sobre X11.
- Debian, Ubuntu, Linux Mint o derivadas (los comandos usan `apt`).

Dependencias de ejecución:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 mpv yt-dlp
pip install --user --break-system-packages ytmusicapi
```

> En Debian 12+/Ubuntu 23.04+ `pip` bloquea instalaciones globales; por eso se usa `--user --break-system-packages`. Instalar con `--user` no toca los paquetes del sistema. Si prefieres un entorno virtual, consulta [Solución de problemas](#solución-de-problemas).

Dependencias de compilación (solo para instalar el plugin):

```bash
sudo apt install build-essential pkg-config libgtk-3-dev \
                 libxfce4panel-2.0-dev libxfce4ui-2-dev
```

Las teclas multimedia usan `xfconf-query` (viene con XFCE) y `dbus-send` (viene con D-Bus); normalmente no hay que instalar nada

## Instalación

```bash
git clone https://github.com/k-sketch/yt-music-xfce-panel.git
cd yt-music-xfce-panel
./install.sh
```

El script:

1. Compila el plugin y lo copia a `/usr` (pide `sudo`)
2. Instala el popup en `~/.local/share/ytm-panel/`
3. Conecta las teclas multimedia de tu teclado
4. Reinicia el panel
5. **Borra los archivos de instalación**, que ya no hacen falta

Después: clic derecho en el panel → **Panel** → **Añadir nuevos elementos** → **YT Music**.

Notas sobre el borrado:

- Solo se eliminan los archivos del proyecto; si en esa carpeta hay otras cosas tuyas, no se tocan
- Si la carpeta es un repositorio git (`.git`), el instalador **pregunta** antes de borrar, por si estás desarrollando
- Para instalar y conservar los archivos: `./install.sh --keep`

## Uso

| Acción                          | Resultado                                    |
| ------------------------------- | -------------------------------------------- |
| Clic en el icono                | Abre/cierra el popup                         |
| Clic central en el icono        | Play/pausa                                   |
| `Enter` en la barra de búsqueda | Busca                                        |
| Doble clic en un resultado      | Reproduce esa canción (y sigue con la lista) |
| Clic en la barra de búsqueda    | Vuelve a mostrar la lista de resultados      |
| `Esc` o clic fuera              | Cierra el popup (la música sigue)            |
| Botón `✕`                       | Cierra el reproductor y detiene la música    |

### Teclas multimedia

El instalador asigna estas teclas (solo las que no tengas ya configuradas):

| Tecla              | Acción            |
| ------------------ | ----------------- |
| `XF86AudioPlay`    | Play/pausa        |
| `XF86AudioPause`   | Pausa             |
| `XF86AudioStop`    | Detener           |
| `XF86AudioNext`    | Siguiente canción |
| `XF86AudioPrev`    | Canción anterior  |
| `XF86AudioForward` | Adelantar 10 s    |
| `XF86AudioRewind`  | Retroceder 10 s   |

Solo actúan mientras YT Music está abierto; si no lo está, no hacen nada, así que no interfieren con otros reproductores. Puedes ver o cambiar las asignaciones en **Configuración → Teclado → Atajos de aplicación**.

## Desinstalar

```bash
~/.local/share/ytm-panel/uninstall.sh
```

Quita el plugin, el popup y las teclas multimedia que puso el instalador (las que cambiaste tú se respetan).

## Cómo funciona

```
 ┌────────────────────┐   --pos x y …    ┌─────────────────────┐   socket IPC   ┌──────┐
 │ Plugin del panel   │ ───────────────► │ ytm_panel.py        │ ─────────────► │ mpv  │
 │ (C, ytm-plugin.c)  │                  │ (Python + GTK3)     │ ◄───────────── │      │
 └────────────────────┘                  └─────────────────────┘    eventos     └──────┘
   botón + posición                         interfaz, búsqueda        reproduce el audio
   (como el reloj)                          (ytmusicapi), portadas    (vía yt-dlp)
                                                    ▲
                      teclas multimedia ── D-Bus ───┘
                      (MPRIS: playerctl, xfconf…)
```

- **`plugin/ytm-plugin.c`**: el elemento del panel. Es solo un botón. Al hacer clic pide al panel (`xfce_panel_plugin_position_widget`, la misma función del reloj) dónde debe ir el popup y lanza el script con esa posición.
- **`ytm_panel.py`**: aplicación GTK de instancia única. Cada clic en el plugin alterna mostrar/ocultar. Busca con [`ytmusicapi`](https://github.com/sigma67/ytmusicapi), controla `mpv` y se anuncia por D-Bus como reproductor MPRIS.
- **`mpv`**: reproduce el audio (resuelto con `yt-dlp`) y se controla por su socket IPC (`$XDG_RUNTIME_DIR/ytm-panel-mpv.sock`).
- **Teclas multimedia**: `install.sh` asocia cada tecla (vía `xfconf-query`) a una orden `dbus-send` dirigida a `org.mpris.MediaPlayer2.ytmpanel`.

## Solución de problemas

**Las teclas multimedia no hacen nada**

1. Comprueba que YT Music esté abierto (haz clic en el icono una vez).
2. Prueba la orden a mano; si esto pausa/reanuda, el problema son las asignaciones de teclas:
   ```bash
   dbus-send --session --type=method_call --dest=org.mpris.MediaPlayer2.ytmpanel \
     /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.PlayPause
   ```
3. Revisa **Configuración → Teclado → Atajos de aplicación**: debe haber una entrada para tu tecla. Si el instalador dijo que «ya tenía otra acción asignada», esa tecla la controla otra cosa y se respetó; cámbiala allí si quieres usarla con YT Music.
4. Si tienes el plugin de **PulseAudio** (`xfce4-pulseaudio-plugin`) con las teclas multimedia activadas, puede estar capturando las mismas teclas. Desactiva esa opción en sus propiedades.
5. Cierra sesión y vuelve a entrar si las teclas se asignaron en esta misma sesión y aún no responden.
6. Si tu teclado usa otra tecla para pausar, averigua su nombre con `xev` y asígnala a mano con la orden del paso 2.

**`./install.sh` dice que falta libxfce4panel aunque está instalado**
Falta una dependencia de su archivo `.pc`. Mira el error real con:

```bash
pkg-config --print-errors --cflags --libs libxfce4panel-2.0
```

Lo más común es instalar `libxfce4ui-2-dev` (y, si lo pide, `libxfce4util-dev` o `libxfce4windowing-dev`).

**En el popup aparece «mpv no está instalado» o `[Errno 2]`**

```bash
sudo apt install mpv yt-dlp
```

**Aparece «Falta ytmusicapi»**

```bash
pip install --user --break-system-packages ytmusicapi
```

Con un entorno virtual (opcional): crea uno con `python3 -m venv --system-site-packages ~/.local/share/ytm-panel/venv`, instala ahí `ytmusicapi` y haz que `ytm_panel.py` se relance con ese Python (el plugin lo ejecuta con `python3`).

**Las canciones no suenan o `yt-dlp` da error**
El `yt-dlp` de los repositorios suele quedarse viejo y YouTube cambia a menudo. Actualízalo:

```bash
sudo apt remove yt-dlp
pip install --user -U --break-system-packages yt-dlp
```

**La música sigue sonando después de cerrar el popup**
Es lo esperado: el popup se oculta pero la música continúa. Para detenerla usa el botón `✕`, o:

```bash
pkill -f ytm_panel.py
```

**El popup no se cierra al hacer clic fuera**
Depende de que tu gestor de ventanas le dé el foco al abrirse. Si no ocurre, abre un issue indicando tu gestor de ventanas y versión de XFCE.

## Limitaciones

- Solo X11; no está pensado para Wayland
- No hay inicio de sesión: no se pueden usar tus listas ni dar «me gusta»
- Reproduce los resultados de la búsqueda como cola; no hay cola personalizable
- Las teclas multimedia solo funcionan con el popup abierto en segundo plano (el programa tiene que estar en marcha)
- Desarrollado y probado en Debian 13 con XFCE 4.20

## Aviso legal

Este proyecto no está afiliado ni respaldado por Google ni YouTube. Usa la API no oficial `ytmusicapi` y `yt-dlp`; el uso de estos servicios está sujeto a los términos de YouTube. Úsalo bajo tu responsabilidad y para uso personal

## Licencia

[MIT](LICENSE)
