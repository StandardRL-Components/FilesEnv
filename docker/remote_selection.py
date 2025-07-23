# remote_location_pipe.py

import gi, os, json, urllib.parse
gi.require_version("Nautilus", "3.0")
gi.require_version("Gio",     "2.0")
from gi.repository import Nautilus, GObject, Gio

class LocationPipeLogger(GObject.GObject, Nautilus.LocationWidgetProvider):
    """
    1) On each folder change → write {"path":..., "view":...}.
    2) On any toggle of icon/list → write the SAME for the current path.
    """

    def __init__(self):
        super().__init__()
        self.pipe = os.path.join(os.environ['HOME'], ".hidden")
        self._last_path = None

        # Listen for global view-mode changes
        try:
            self.prefs = Gio.Settings.new("org.gnome.nautilus.preferences")
            self.prefs.connect("changed::default-folder-viewer", self._on_view_changed)
        except Exception:
            self.prefs = None

    def get_widget(self, uri, window):
        # Decode URI
        try:
            path = urllib.parse.urlparse(uri).path
        except Exception:
            path = uri

        self._last_path = path
        view = self._get_view_mode()

        self._write_pipe(path, view)
        return None

    def _on_view_changed(self, settings, key):
        # GSettings changed → view toggled
        if self._last_path is None:
            return
        view = self._get_view_mode()
        self._write_pipe(self._last_path, view)

    def _get_view_mode(self):
        # Read the current viewer setting
        try:
            dfv = self.prefs.get_string("default-folder-viewer")
            return dfv
        except Exception:
            return "unknown"

    def _write_pipe(self, path, view):
        msg = json.dumps({"path": path, "view": view})
        try:
            fd = os.open(self.pipe, os.O_WRONLY | os.O_NONBLOCK)
            with os.fdopen(fd, "w") as f:
                f.write(msg + "\n")
        except (FileNotFoundError, BlockingIOError):
            pass
        except Exception:
            pass
