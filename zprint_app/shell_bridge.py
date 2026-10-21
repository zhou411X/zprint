"""Small, versioned-by-extension bridge; never uses org.gnome.Shell.Eval."""

import json
from gi.repository import Gio, GLib


def call(method, signature, values):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    result = bus.call_sync("org.gnome.Shell", "/io/github/zprint/Shell",
                           "io.github.zprint.Shell", method,
                           GLib.Variant(signature, values), None,
                           Gio.DBusCallFlags.NO_AUTO_START, 1000, None)
    return result.unpack()


def get_capture(key):
    try:
        result, = call("GetCapture", "(s)", (key,))
        return json.loads(result) if result else None
    except (GLib.Error, ValueError):
        return None


def prepare(token, width, height):
    result, = call("Prepare", "(sii)", (token, width, height))
    return json.loads(result)


def dismiss(token):
    try:
        call("Dismiss", "(s)", (token,))
    except GLib.Error:
        pass  # Disabling the extension must not prevent closing an editor.
