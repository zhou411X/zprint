"""Asynchronous Shell selection, with Screenshot portal v2 fallback."""

import uuid

from gi.repository import Gio, GLib

BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
REQUEST = "org.freedesktop.portal.Request"
SHELL_PATH = "/io/github/zprint/Shell"
SHELL_IFACE = "io.github.zprint.Shell"


class ScreenshotRequest:
    def __init__(self, callback, prefer_shell=False):
        self.callback = callback
        self.connection = None
        self.subscription = 0
        self.timer = 0
        self.path = None
        self.done = False
        self.cancellable = Gio.Cancellable()
        self.prefer_shell = prefer_shell
        self.shell_token = None

    def start(self):
        Gio.bus_get(Gio.BusType.SESSION, self.cancellable, self._connected)

    def _connected(self, source, result):
        try:
            self.connection = Gio.bus_get_finish(result)
        except GLib.Error as error:
            self._finish(None, str(error))
            return
        if self.done:
            return
        if self.prefer_shell:
            self.shell_token = uuid.uuid4().hex
            self.timer = GLib.timeout_add_seconds(180, self._timeout)
            self.connection.call("org.gnome.Shell", SHELL_PATH, SHELL_IFACE, "Capture",
                                 GLib.Variant("(s)", (self.shell_token,)), GLib.VariantType.new("(s)"),
                                 Gio.DBusCallFlags.NO_AUTO_START, 180000, self.cancellable, self._shell_called)
        else:
            self._start_portal()

    def _shell_called(self, connection, result):
        try:
            uri, = connection.call_finish(result).unpack()
        except GLib.Error as error:
            if self.done:
                return
            unavailable = (Gio.DBusError.UNKNOWN_METHOD, Gio.DBusError.UNKNOWN_OBJECT,
                           Gio.DBusError.UNKNOWN_INTERFACE, Gio.DBusError.SERVICE_UNKNOWN,
                           Gio.DBusError.NAME_HAS_NO_OWNER)
            if any(error.matches(Gio.dbus_error_quark(), code) for code in unavailable):
                # An absent/older extension still supports the original portal flow.
                self.shell_token = None
                GLib.source_remove(self.timer)
                self.timer = 0
                self._start_portal()
            else:
                self._close()
                self._finish(None, str(error))
            return
        self._finish(uri or None, None)

    def _start_portal(self):
        token = "zprint_" + uuid.uuid4().hex
        sender = self.connection.get_unique_name()[1:].replace(".", "_")
        self.path = f"{PATH}/request/{sender}/{token}"
        # Subscribe before calling Screenshot: even an immediate response is safe.
        self.subscription = self.connection.signal_subscribe(
            BUS, REQUEST, "Response", self.path, None,
            Gio.DBusSignalFlags.NONE, self._response)
        self.timer = GLib.timeout_add_seconds(180, self._timeout)
        self.connection.call(
            BUS, PATH, "org.freedesktop.portal.Screenshot", "Screenshot",
            GLib.Variant("(sa{sv})", ("", {
                "handle_token": GLib.Variant("s", token),
                "interactive": GLib.Variant("b", True),
                "modal": GLib.Variant("b", False),
            })), GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE,
            10000, self.cancellable, self._called)

    def _called(self, connection, result):
        try:
            returned_path, = connection.call_finish(result).unpack()
            if not self.done and returned_path != self.path:
                connection.signal_unsubscribe(self.subscription)
                self.path = returned_path
                self.subscription = connection.signal_subscribe(
                    BUS, REQUEST, "Response", self.path, None,
                    Gio.DBusSignalFlags.NONE, self._response)
        except GLib.Error as error:
            self._finish(None, str(error))

    def _response(self, connection, sender, path, interface, signal, parameters):
        code, results = parameters.unpack()
        if code == 0:
            uri = results.get("uri")
            self._finish(uri, None if uri else "系统截图没有返回图片")
        elif code == 1:
            self._finish(None, None)
        else:
            self._finish(None, "系统截图失败，请检查桌面截图服务")

    def _close(self):
        if self.connection and self.shell_token:
            self.connection.call("org.gnome.Shell", SHELL_PATH, SHELL_IFACE, "CancelCapture",
                                 GLib.Variant("(s)", (self.shell_token,)), None,
                                 Gio.DBusCallFlags.NO_AUTO_START, 3000, None, self._closed)
        if self.connection and self.path:
            self.connection.call(BUS, self.path, REQUEST, "Close", None, None,
                                 Gio.DBusCallFlags.NONE, 3000, None, self._closed)

    @staticmethod
    def _closed(connection, result):
        try:
            connection.call_finish(result)
        except GLib.Error:
            # The portal may already have removed a completed request.
            pass

    def cancel(self):
        self._close()
        self.cancellable.cancel()
        self._finish(None, None)

    def _timeout(self):
        self.timer = 0
        self._close()
        self._finish(None, "截图等待超时，请重试")
        return GLib.SOURCE_REMOVE

    def _finish(self, uri, error):
        if self.done:
            return
        self.done = True
        if self.subscription:
            self.connection.signal_unsubscribe(self.subscription)
            self.subscription = 0
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        self.callback(uri, error)
