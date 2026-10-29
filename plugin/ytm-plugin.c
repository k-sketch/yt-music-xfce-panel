/*
 * YT Music - plugin para el panel de XFCE
 *
 * Boton que se ve en el panel
 * Todo lo hace ytm_panel.py, que este plugin abre
 *
 *   - Clic izquierdo: abre o cierra el popup
 *   - Clic central:   play/pausa directo, sin abrir nada
*/

#include <gtk/gtk.h>
#include <libxfce4panel/libxfce4panel.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <string.h>

/* 
 * Ancho del popup
 * Debe ser igual a WIN_W en ytm_panel.py
*/

#define POPUP_WIDTH 420

/*
 * Abrir el popup
*/

static void
launch_popup (XfcePanelPlugin *plugin)
{
  GtkWidget *widget = GTK_WIDGET (plugin);
  GdkWindow *gdk_win = gtk_widget_get_window (widget);
  GtkAllocation alloc;
  gint px = 0, py = 0, x = 0, y = 0;
  GError *err = NULL;

  /* Donde esta ubicado el boton en la pantalla */
  if (gdk_win)
    gdk_window_get_origin (gdk_win, &px, &py);
  gtk_widget_get_allocation (widget, &alloc);
  px += alloc.x;
  py += alloc.y;

 /* Pregunta donde colocara la ventana de nuestro ancho (debajo, encima o al lado)
   * Se usa una ventana falsa para que el panel sepa que tamaño tiene
   * El alto real lo ajusta el script despues */

  GtkWidget *dummy = gtk_window_new (GTK_WINDOW_POPUP);
  gtk_widget_set_size_request (dummy, POPUP_WIDTH, 1);
  xfce_panel_plugin_position_widget (plugin, dummy, NULL, &x, &y);
  gtk_widget_destroy (dummy);

  /* Python3 ytm_panel.py --pos x y px py ancho alto  */
  gchar *script = g_build_filename (g_get_home_dir (),
                                    ".local/share/ytm-panel/ytm_panel.py", NULL);
  gchar *v[6];
  v[0] = g_strdup_printf ("%d", x);
  v[1] = g_strdup_printf ("%d", y);
  v[2] = g_strdup_printf ("%d", px);
  v[3] = g_strdup_printf ("%d", py);
  v[4] = g_strdup_printf ("%d", alloc.width);
  v[5] = g_strdup_printf ("%d", alloc.height);

  gchar *argv[] = { "python3", script, "--pos",
                    v[0], v[1], v[2], v[3], v[4], v[5], NULL };

  if (!g_spawn_async (NULL, argv, NULL, G_SPAWN_SEARCH_PATH,
                      NULL, NULL, NULL, &err))
    {
      g_warning ("YT Music: no se pudo abrir el popup: %s", err->message);
      g_error_free (err);
    }

  /* Limpieza de memoria */
  g_free (script);
  for (int i = 0; i < 6; i++)
    g_free (v[i]);
}

/*
 * Play/pausa con el clic central
*/
static void
toggle_pause (void)
{
  /* 
   * Mpv escucha ordenes en un archivo especial
   * Si mpv no esta abierto, la conexion falla
  */

  const gchar *runtime = g_get_user_runtime_dir ();
  gchar *path = g_build_filename (runtime ? runtime : "/tmp",
                                  "ytm-panel-mpv.sock", NULL);
  struct sockaddr_un addr;
  int fd = socket (AF_UNIX, SOCK_STREAM, 0);

  if (fd >= 0)
    {
      memset (&addr, 0, sizeof addr);
      addr.sun_family = AF_UNIX;
      g_strlcpy (addr.sun_path, path, sizeof addr.sun_path);

      if (connect (fd, (struct sockaddr *) &addr, sizeof addr) == 0)
        {
          const char *msg = "{\"command\":[\"cycle\",\"pause\"]}\n";
          if (write (fd, msg, strlen (msg)) < 0)
            g_warning ("YT Music: no se pudo hablar con mpv");
        }
      close (fd);
    }
  g_free (path);
}


/* Clic izquierdo: abrir/cerrar el popup */
static void
on_clicked (GtkButton *button, XfcePanelPlugin *plugin)
{
  launch_popup (plugin);
}

/* Click central */
static gboolean
on_button_press (GtkWidget *widget, GdkEventButton *event, gpointer data)
{
  if (event->button == 2)
    {
      toggle_pause ();
      return TRUE;
    }
  return FALSE;
}

/* Si cambias el grosor del panel, el icono se ajusta a ese tamaño. */
static gboolean
on_size_changed (XfcePanelPlugin *plugin, gint size, GtkWidget *image)
{
  gtk_image_set_pixel_size (GTK_IMAGE (image), MAX (size - 8, 16));
  gtk_widget_set_size_request (GTK_WIDGET (plugin), size, size);
  return TRUE;
}

/*
 * Crear el plugin
*/

static void
ytm_construct (XfcePanelPlugin *plugin)
{
  /* Boton sin marco con el icono de musica */

  GtkWidget *button = gtk_button_new ();
  GtkWidget *image = gtk_image_new_from_icon_name ("multimedia-audio-player",
                                                    GTK_ICON_SIZE_BUTTON);

  gtk_button_set_relief (GTK_BUTTON (button), GTK_RELIEF_NONE);
  gtk_button_set_image (GTK_BUTTON (button), image);
  gtk_widget_set_tooltip_text (button,
      "YT Music\nClic central: play/pausa");

  /* Conectamos los eventos al boton y al panel */

  g_signal_connect (button, "clicked", G_CALLBACK (on_clicked), plugin);
  g_signal_connect (button, "button-press-event",
                    G_CALLBACK (on_button_press), NULL);
  g_signal_connect (plugin, "size-changed",
                    G_CALLBACK (on_size_changed), image);

  gtk_container_add (GTK_CONTAINER (plugin), button);

  xfce_panel_plugin_add_action_widget (plugin, button);
  gtk_widget_show_all (GTK_WIDGET (plugin));
}

XFCE_PANEL_PLUGIN_REGISTER (ytm_construct);
