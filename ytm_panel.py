#!/usr/bin/env python3
"""
YT Music Panel - el popup del reproductor

  - El plugin del panel (plugin/ytm-plugin.c) es solo el boton. Cuando le
    haces clic, ejecuta este archivo y le dice en que punto de la pantalla
    debe aparecer el popup
  - Este archivo dibuja la ventana, busca canciones en YouTube Music y le
    pasa el audio a mpv

Solo hay una copia corriendo a la vez, la musica sigue sonando aunque lo ocultes

"""
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango

# ytmusicapi se instala aparte; si falta, se avisa
try:
    from ytmusicapi import YTMusic
except ImportError:
    YTMusic = None


# ========
# Ajustes
# ========
# Archivo por donde hablamos con mpv

SOCK_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
                         "ytm-panel-mpv.sock")
WIN_W = 420          # ancho del popup (igual que POPUP_WIDTH en el plugin)
COVER_SIZE = 96      # tamaño de la portada, en pixeles
LIST_H = 250         # alto de la lista de resultados
MAX_RESULTS = 25     # cuantas canciones pedir en cada busqueda
REOPEN_GUARD = 0.6   # segundos; se explica en App.do_command_line


def fmt_time(seconds):
    """Convierte segundos en texto tipo '3:07'."""
    seconds = int(max(0, seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


# =====
# Mpv
# =====

class Mpv:
    """
    Arranca mpv en segundo plano y lo controla a traves de un socket

    """
    # numero -> nombre
    OBSERVED = {1: "playlist-pos", 2: "pause", 3: "time-pos", 4: "duration"}

    def __init__(self, on_prop):
        self.on_prop = on_prop      # funcion a la que avisamos de cada cambio
        self._quit_orphan()

        try:
            self.proc = subprocess.Popen(
                ["mpv", "--idle=yes", "--no-video", "--force-window=no",
                 "--ytdl-format=bestaudio/best",
                 f"--input-ipc-server={SOCK_PATH}"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            raise RuntimeError("mpv no esta instalado (sudo apt install mpv yt-dlp)")

        # mpv tarda un momento en crear el socket, reintentamos
        # durante unos 5 segundos hasta poder conectarnos

        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        for _ in range(50):
            try:
                self.sock.connect(SOCK_PATH)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.1)
        else:
            raise RuntimeError("no se pudo conectar con mpv")

        # Un hilo aparte se queda escuchando a mpv
        threading.Thread(target=self._reader, daemon=True).start()
        for prop_id, name in self.OBSERVED.items():
            self.cmd("observe_property", prop_id, name)

    @staticmethod
    def _quit_orphan():
        """Si quedo un mpv "huerfano" (sonando solo), lo apagamos"""
        if not os.path.exists(SOCK_PATH):
            return
        old = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            old.connect(SOCK_PATH)
            old.sendall(b'{"command":["quit"]}\n')
            time.sleep(0.3)
        except OSError:
            pass
        finally:
            old.close()
        try:
            os.remove(SOCK_PATH)
        except OSError:
            pass

    def cmd(self, *args):
        """ Le manda una orden a mpv """
        try:
            self.sock.sendall((json.dumps({"command": list(args)}) + "\n").encode())
        except OSError:
            pass

    def _reader(self):
        """
        Trabaja en segundo plano: lee los mensajes de mpv y los pasa a la ventana
        Hay que pasarlos con GLib.idle_add porque solo el hilo principal puede tocar la interfaz

        """
        buf = b""
        while True:
            try:
                data = self.sock.recv(4096)
            except OSError:
                return
            if not data:
                return
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("event") == "property-change":
                    GLib.idle_add(self.on_prop, msg["name"], msg.get("data"))

    def quit(self):
        self.cmd("quit")
        try:
            self.proc.terminate()
        except OSError:
            pass


# ============================================================================
# Ventana del popup
# ============================================================================
class PlayerWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(title="YT Music")
        self.app = app

        # Que se vea como popup: sin bordes, sin barra de titulo, sin aparecer
        # en la barra de tareas y siempre por encima
        self.set_size_request(WIN_W, -1)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_skip_taskbar_hint(True)
        self.set_keep_above(True)
        self.set_decorated(False)
        self.set_resizable(False)
        self.connect("delete-event", lambda *_: self.hide_popup() or True)
        self.connect("key-press-event", self._on_key)
        self.connect("notify::is-active", self._on_active_changed)

        # --- Cosas que recordamos sobre el popup ---
        self.popup_pos = None       # Donde nos pide el panel aparecer
        self.hidden_at = 0.0        # A que hora lo ocultamos por ultima vez
        self.was_active = False     # ¿tuvo el foco alguna vez desde que se abrio?
        self._layout_pending = False

        # --- Cosas que recordamos sobre la música ---
        self.queue = []             # Canciones de la ultima busqueda
        self.pos = -1               # Cual suena ahora (-1 = ninguna)
        self.duration = 0.0         # duracion de la cancion actual, en segundos
        self.dragging = False       # ¿Se esta arrastrando la barra de tiempo?
        self.seek_target = None
        self._last_sec = -1         # Refrescar la barra solo una vez por segundo
        self._search_id = 0         # Ignorar busquedas viejas que lleguen tarde
        self.covers = {}            # portadas ya descargadas (para no repetir)
        self.current_cover = None

        self.ytm = YTMusic() if YTMusic else None
        self.mpv = None
        self._build_ui()

        if not self.ytm:
            self.set_status("Falta ytmusicapi (pip install ytmusicapi)")
        try:
            self.mpv = Mpv(self._on_mpv_prop)
        except RuntimeError as e:
            self.set_status(f"Error: {e}")

    # -------------------
    # Armar la interfaz
    # -------------------

    def _build_ui(self):

        # Un marco fino alrededor, ya que la ventana no tiene bordes

        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.OUT)
        self.add(frame)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_border_width(6)
        frame.add(box)

        box.pack_start(self._build_search_bar(), False, False, 0)
        box.pack_start(self._build_results_list(), False, False, 0)
        box.pack_start(self._build_player(), False, False, 0)

        # Linea para avisos y errores; no se ve mientras esta vacia

        self.lbl_status = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.lbl_status.set_no_show_all(True)
        box.pack_start(self.lbl_status, False, False, 0)

    def _build_search_bar(self):
        """Arriba de todo: el cuadro de busqueda y el boton para salir"""
        row = Gtk.Box(spacing=4)
        self.entry = Gtk.SearchEntry(placeholder_text="Buscar canción o artista…")
        self.entry.connect("activate", self._on_search)          # al pulsar Enter
        self.entry.connect("button-press-event", self._on_entry_click)

        btn_quit = Gtk.Button(label="✕", relief=Gtk.ReliefStyle.NONE)
        btn_quit.set_tooltip_text("Cerrar el reproductor y detener la música")
        btn_quit.connect("clicked", lambda *_: self.app.quit_all())

        row.pack_start(self.entry, True, True, 0)
        row.pack_end(btn_quit, False, False, 0)
        return row

    def _build_results_list(self):
        """
        La lista de resultados. Cada fila tiene dos columnas: a la izquierda
        el titulo con el artista, y a la derecha la duracion

        """
        self.store = Gtk.ListStore(str, str)        # (texto con formato, duracion)
        self.tree = Gtk.TreeView(model=self.store, headers_visible=False)

        # La columna del titulo se estira y se corta con "…" si no cabe
        col_title = Gtk.TreeViewColumn(
            "", Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END), markup=0)
        col_title.set_expand(True)
        # La de la duracion ocupa solo lo necesario y va alineada a la derecha
        col_dur = Gtk.TreeViewColumn(
            "", Gtk.CellRendererText(xalign=1.0, xpad=6), text=1)
        self.tree.append_column(col_title)
        self.tree.append_column(col_dur)
        self.tree.connect("row-activated", lambda t, path, c: self.play_index(path[0]))

        self.list_sw = Gtk.ScrolledWindow(shadow_type=Gtk.ShadowType.IN)
        self.list_sw.set_min_content_height(LIST_H)
        self.list_sw.add(self.tree)
        self._start_hidden(self.list_sw)            # no se ve hasta que se busque algo
        return self.list_sw

    def _build_player(self):
        """
        El reproductor de abajo: la portada a la izquierda y, a la derecha,
        el titulo, los botones y la barra de tiempo

        """
        self.player = Gtk.Box(spacing=10)

        self.cover = Gtk.Image(valign=Gtk.Align.CENTER)
        self.cover.set_size_request(COVER_SIZE, COVER_SIZE)
        self._set_cover_placeholder()
        self.player.pack_start(self.cover, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                        valign=Gtk.Align.CENTER)
        self.lbl_now = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        right.pack_start(self.lbl_now, False, False, 0)
        right.pack_start(self._build_controls(), False, False, 0)
        right.pack_start(self._build_seek_bar(), False, False, 0)
        self.player.pack_start(right, True, True, 0)

        self._start_hidden(self.player)             # no se ve hasta que suene algo
        return self.player

    def _build_controls(self):
        """Los cuatro botones: anterior, play/pausa, siguiente y repetir."""
        row = Gtk.Box(spacing=4)

        def icon_button(icon, tip, callback):
            b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
            b.set_tooltip_text(tip)
            b.connect("clicked", callback)
            return b

        b_prev = icon_button("media-skip-backward-symbolic", "Anterior",
                             lambda *_: self._mpv("playlist-prev"))
        self.b_play = icon_button("media-playback-start-symbolic",
                                  "Reproducir / Pausa", lambda *_: self._toggle_play())
        b_next = icon_button("media-skip-forward-symbolic", "Siguiente",
                             lambda *_: self._mpv("playlist-next"))

        # "Repetir" queda hundido mientras este activo
        b_loop = Gtk.ToggleButton()
        b_loop.set_image(Gtk.Image.new_from_icon_name(
            "media-playlist-repeat-symbolic", Gtk.IconSize.BUTTON))
        b_loop.set_tooltip_text("Repetir canción")
        b_loop.connect("toggled", lambda b: self._mpv(
            "set_property", "loop-file", "inf" if b.get_active() else "no"))

        for b in (b_prev, self.b_play, b_next, b_loop):
            row.pack_start(b, False, False, 0)
        return row

    def _build_seek_bar(self):
        """Tiempo que lleva | barra para saltar a cualquier punto | duracion total"""
        row = Gtk.Box(spacing=6)
        self.lbl_elapsed = Gtk.Label(label="0:00")
        self.lbl_total = Gtk.Label(label="0:00")
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 1)
        self.scale.set_draw_value(False)
        self.scale.connect("button-press-event", self._on_seek_press)
        self.scale.connect("button-release-event", self._on_seek_release)
        self.scale.connect("change-value", self._on_seek_change)
        row.pack_start(self.lbl_elapsed, False, False, 0)
        row.pack_start(self.scale, True, True, 0)
        row.pack_start(self.lbl_total, False, False, 0)
        return row

    @staticmethod
    def _start_hidden(widget):
        """
        Deja una parte de la interfaz armada pero escondida. Basta llamar a widget.show() para que aparezca con todo lo que lleva dentro

        """
        widget.show_all()
        widget.hide()
        widget.set_no_show_all(True)

    def set_status(self, text):
        """Muestra un aviso abajo del todo (o lo esconde si el texto está vacío)."""
        self.lbl_status.set_text(text)
        self.lbl_status.set_visible(bool(text))
        self._relayout()
        return False

    # -------------------------------------
    # Mostrar, ocultar y colocar el popup
    # -------------------------------------
    def _on_key(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.hide_popup()

    def hide_popup(self):
        # Anotamos la hora: la usamos para evitar que se reabra solo (ver App)
        self.hidden_at = time.monotonic()
        self.was_active = False
        self.hide()

    def _on_active_changed(self, *_):
        """
        Si haces clic en cualquier otra cosa, el popup pierde el foco y se esconde solo

        """
        if self.is_active():
            self.was_active = True
        elif self.was_active and self.get_visible():
            self.hide_popup()

    def show_at(self, pos):
        """Muestra el popup en el lugar que indico el panel (ver _place)"""
        self.popup_pos = pos or self._pointer_pos()
        self.was_active = False
        self.show_all()
        self._place()
        self.present_with_time(Gtk.get_current_event_time())
        self.entry.grab_focus()         # para poder escribir de inmediato
        self._relayout()

    @staticmethod
    def _pointer_pos():
        """Plan B si abres el programa a mano (sin plugin): junto al raton"""
        display = Gdk.Display.get_default()
        _s, px, py = display.get_default_seat().get_pointer().get_position()
        mon = display.get_monitor_at_point(px, py).get_geometry()
        lower = py > mon.y + mon.height // 2
        return (px - WIN_W // 2, py - 1 if lower else py + 1, px, py, 1, 1)

    def _relayout(self):
        """
        Pide recolocar la ventana cuando cambia de tamaño.
        Si varias partes lo piden a la vez, se hace una sola vez

        """
        if not self._layout_pending:
            self._layout_pending = True
            GLib.idle_add(self._place)

    def _place(self):
        """
        El plugin pregunta al panel donde va una ventana de WIN_W de ancho y 1 de alto
        Aqui solo se corrige por el alto real del popup: si el panel esta
        abajo (y < py), la ventana tiene que crecer hacia arriba
        """
        self._layout_pending = False
        if self.popup_pos is None or not self.get_visible():
            return False
        x, y, px, py, _pw, _ph = self.popup_pos
        _min, nat = self.get_preferred_size()
        w, h = max(WIN_W, nat.width), nat.height
        mon = Gdk.Display.get_default().get_monitor_at_point(px, py).get_geometry()

        ny = y + 1 - h if y < py else y
        # Nos aseguramos de no salirnos de la pantalla
        nx = max(mon.x, min(x, mon.x + mon.width - w))
        ny = max(mon.y, min(ny, mon.y + mon.height - h))
        self.move(nx, ny)
        return False

    # -------------
    # Busqueda
    # -------------
    def _on_entry_click(self, *_):
        """Si haces clic en la barra, vuelve a aparecer la lista de la ultima busqueda"""
        if self.queue and not self.list_sw.get_visible():
            self.list_sw.show()
            self._relayout()
        return False

    def _on_search(self, entry):
        query = entry.get_text().strip()
        if not query or not self.ytm:
            return
        self.set_status("Buscando…")
        self._search_id += 1
        # La busqueda va en un hilo aparte para que la ventana no se congele
        threading.Thread(target=self._search_worker,
                         args=(query, self._search_id), daemon=True).start()

    def _search_worker(self, query, search_id):
        """(Segundo plano) Pregunta a YouTube Music y deja listos los resultados."""
        try:
            results = self.ytm.search(query, filter="songs", limit=MAX_RESULTS)
        except Exception as e:
            GLib.idle_add(self.set_status, f"Error de búsqueda: {e}")
            return

        items = []
        for r in results:
            if not r.get("videoId"):
                continue
            thumbs = r.get("thumbnails") or []
            cover = thumbs[-1]["url"] if thumbs else None
            if cover:   # Cambiar el tamaño en la URL para una imagen mas nitida
                cover = re.sub(r"=w\d+-h\d+", "=w300-h300", cover)
            items.append({
                "id": r["videoId"],
                "title": r.get("title", "?"),
                "artist": ", ".join(a["name"] for a in (r.get("artists") or [])),
                "dur": r.get("duration") or "",
                "cover": cover,
            })
        GLib.idle_add(self._show_results, items, search_id)

    def _show_results(self, items, search_id):
        # Si mientras tanto lanzaste otra busqueda, esta ya no sirve
        if search_id != self._search_id:
            return False
        self.queue = items
        self.store.clear()
        esc = GLib.markup_escape_text
        for it in items:
            self.store.append([
                f"<b>{esc(it['title'])}</b>\n<small>{esc(it['artist'])}</small>",
                it["dur"]])
        self.list_sw.set_visible(bool(items))
        self.set_status("" if items else "Sin resultados")
        return False

    # ------------------------------------------------------------------
    # Reproducir y controlar
    # ------------------------------------------------------------------

    def _mpv(self, *args):
        """Atajo para mandarle una orden a mpv"""
        if self.mpv:
            self.mpv.cmd(*args)

    def play_index(self, idx):
        """
        Reproduce la cancion numero idx. Metemos todos los resultados en la
        lista de mpv, asi "siguiente" y "anterior" funcionan solos.
        """
        if not self.mpv or not self.queue:
            return
        self.mpv.cmd("stop")
        for it in self.queue:
            self.mpv.cmd("loadfile",
                         f"https://www.youtube.com/watch?v={it['id']}", "append")
        self.mpv.cmd("set_property", "playlist-pos", idx)
        self.list_sw.hide()         # vista compacta: busqueda + reproductor
        self._relayout()

    def _toggle_play(self):
        if self.pos < 0 and self.queue:
            self.play_index(0)      # no suena nada: empezamos por la primera
        else:
            self._mpv("cycle", "pause")

    def _seek_to(self, seconds):
        self._mpv("seek", seconds, "absolute")

    # -----------------
    # Barra de tiempo
    # -----------------

    def _on_seek_press(self, *_):
        self.dragging = True
        return False

    def _on_seek_change(self, _scale, _scroll, value):
        value = max(0.0, min(value, self.duration))
        self.lbl_elapsed.set_text(fmt_time(value))
        if self.dragging:
            self.seek_target = value                    # se aplica al soltar
        else:
            self._seek_to(value)                         # con las flechas del teclado
        return False

    def _on_seek_release(self, *_):
        if self.seek_target is not None:
            self._seek_to(self.seek_target)
            self.seek_target = None
        self.dragging = False
        return False

    def _set_duration(self, dur):
        self.duration = float(dur) if dur else 0.0
        self.scale.set_range(0, self.duration or 1)
        self.lbl_total.set_text(fmt_time(self.duration))

    def _reset_progress(self):
        """Pone la barra de tiempo en cero (al cambiar de cancion)."""
        self._last_sec = -1
        self._set_duration(0)
        self.scale.set_value(0)
        self.lbl_elapsed.set_text("0:00")

    # ------------
    # Portada
    # -----------

    def _set_cover_placeholder(self):
        """Icono de musica generico mientras carga la portada"""
        self.cover.set_from_icon_name("audio-x-generic", Gtk.IconSize.DIALOG)
        self.cover.set_pixel_size(COVER_SIZE // 2)

    def _load_cover(self, url):
        self.current_cover = url
        if not url:
            self._set_cover_placeholder()
        elif url in self.covers:                        # ya la teniamos descargada
            self._show_cover(url, self.covers[url])
        else:
            self._set_cover_placeholder()
            threading.Thread(target=self._cover_worker, args=(url,),
                             daemon=True).start()

    def _cover_worker(self, url):
        """(Segundo plano) Descarga la imagen y la deja del tamaño justo."""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=10).read()
            loader = GdkPixbuf.PixbufLoader()
            loader.write(data)
            loader.close()
            pix = loader.get_pixbuf().scale_simple(
                COVER_SIZE, COVER_SIZE, GdkPixbuf.InterpType.BILINEAR)
        except Exception:
            return                      # sin portada, queda el icono
        GLib.idle_add(self._show_cover, url, pix)

    def _show_cover(self, url, pix):
        self.covers[url] = pix
        # Si ya cambiaste de cancion mientras bajaba, no mostramos la vieja
        if url == self.current_cover:
            self.cover.set_pixel_size(-1)
            self.cover.set_from_pixbuf(pix)
        return False

    # -----------------------------
    # Lo que mpv comunica
    # -----------------------------
    def _on_mpv_prop(self, name, data):
        if name == "playlist-pos":              # cambio de cancion
            self.pos = data if isinstance(data, int) else -1
            if 0 <= self.pos < len(self.queue):
                it = self.queue[self.pos]
                self.lbl_now.set_text(f"{it['title']} — {it['artist']}")
                self.tree.set_cursor(Gtk.TreePath(self.pos))
                self.set_status("")
                self._load_cover(it["cover"])
                self.player.show()
            else:                               # ya no suena nada: solo la busqueda
                self.player.hide()
                self._load_cover(None)
            self._reset_progress()
            self._relayout()

        elif name == "pause":                   # pausa / reanudar
            icon = ("media-playback-start-symbolic" if data
                    else "media-playback-pause-symbolic")
            self.b_play.set_image(
                Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))

        elif name == "duration":                # duracion
            self._set_duration(data)

        elif name == "time-pos" and not self.dragging:
            sec = int(data or 0)
            if sec != self._last_sec:
                self._last_sec = sec
                self.scale.set_value(sec)
                self.lbl_elapsed.set_text(fmt_time(sec))
        return False


# ===============
# La aplicacion 
# ===============

class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.local.ytmpanel",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    @staticmethod
    def _parse_pos(args):
        """Lee los numeros que manda el plugin tras '--pos' (donde aparecer)"""
        if "--pos" not in args:
            return None
        try:
            i = args.index("--pos")
            vals = tuple(int(v) for v in args[i + 1:i + 7])
        except ValueError:
            return None
        return vals if len(vals) == 6 else None

    def do_command_line(self, cmdline):
        """
        Se ejecuta cada vez que el plugin lanza este programa
        La primera vez crea la ventana; las siguientes llegan a la
        copia que ya esta abierta y solo la muestran u ocultan

        """
        pos = self._parse_pos(cmdline.get_arguments())

        if self.win is None:                                    # primera vez
            self.win = PlayerWindow(self)
            self.hold()         # mantenerlo abierto
            for sig in (signal.SIGTERM, signal.SIGINT):
                GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self._on_signal)
            self.win.show_at(pos)
        elif self.win.get_visible():                            # estaba abierto: cerrar
            self.win.hide_popup()
        elif time.monotonic() - self.win.hidden_at < REOPEN_GUARD:
            # Al hacer clic en el icono con el popup abierto, primero se
            # cierra solo y despues llega este clic
            # Sin esta pausa se volveria a abrir al instante
            pass
        else:                                                   # estaba cerrado: abrir
            self.win.show_at(pos)
        return 0

    def _on_signal(self):
        self.quit_all()
        return False

    def quit_all(self):
        """Apaga todo: la musica y el programa."""
        if self.win and self.win.mpv:
            self.win.mpv.quit()
        self.release()
        self.quit()


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
